import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vlm_supervisor.core.iphone_client import IPhoneClient, MockIPhoneClient, make_client
from vlm_supervisor.core.models import Assessment
from vlm_supervisor.core.prompt_builder import build_prompt
from vlm_supervisor.core.run_logger import RunLogger
from vlm_supervisor.core.snapshot import load_snapshot, save_snapshot
from vlm_supervisor.core.supervisor import Supervisor

from .helpers import JPEG
from .test_prompt_builder import make_input


# ------------------------------------------------------------------ Phase 3

def test_snapshot_roundtrip(tmp_path):
    si = make_input()
    out = save_snapshot(si, str(tmp_path / "snap"))
    assert sorted(os.listdir(out)) == ["image.jpg", "metadata.json", "snapshot.json", "state_entry_image.jpg"]
    meta = json.load(open(os.path.join(out, "metadata.json")))
    assert meta["flexbe"]["last_outcome"]["outcome"] == "done" and meta["inputs"]["image"]["count"] == 1
    si2 = load_snapshot(out)
    assert si2.observation.image.data == JPEG and si2.state_entry_image.timestamp == 5.0
    assert si2.flexbe_context.graph["/Grasp/Close"].transitions == ["Check"]
    assert si2.flexbe_context.last_outcome.target == "Check"
    # 保存物から作った prompt が元と一致する (offline 再評価の再現性)
    assert build_prompt(si2).user_text == build_prompt(si).user_text


def test_run_logger(tmp_path):
    rl = RunLogger(root=str(tmp_path), run_id="r1")
    rl.append("events", {"type": "X"})
    rl.logger.info("hello")
    p = rl.save_snapshot(make_input())
    rl.close()
    assert os.path.basename(p).startswith("00001_10.500_STATE_OUTCOME")
    assert json.loads(open(tmp_path / "r1" / "events.jsonl").readline())["type"] == "X"
    assert "hello" in open(tmp_path / "r1" / "supervisor.log").read()
    assert os.readlink(tmp_path / "latest") == "r1"


# ------------------------------------------------------------------ Phase 4/5 with mock

def test_supervisor_evaluate_with_mock_records_history():
    mock = MockIPhoneClient([{"assessment": "semantic_failure", "reason": "closed beside the cup",
                              "confidence": 0.9, "intervention": "RECOVER"}])
    sup = Supervisor(client=mock, task_instruction="pick")
    r = sup.evaluate(make_input())
    assert r.response.ok and r.decision.assessment == Assessment.SEMANTIC_FAILURE
    assert r.flexbe_summary["last_outcome"]["outcome"] == "done"
    assert len(mock.requests) == 1 and len(mock.requests[0][0].images) == 2
    si = sup.build_input(make_input().observation)
    assert si.history[-1]["vlm_assessment"] == "semantic_failure"
    sup.reset_history()
    assert sup.build_input(make_input().observation).history == []
    json.dumps(r.to_dict(), default=str)


def test_supervisor_handles_request_failure():
    sup = Supervisor(client=MockIPhoneClient(fail_with="timeout"))
    r = sup.evaluate(make_input())
    assert not r.response.ok and not r.decision.valid and "timeout" in r.decision.parse_error


def test_make_client_reads_key_from_env(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    c = make_client({"client": "iphone", "api_key_env": "MY_KEY"})
    assert isinstance(c, IPhoneClient) and c._headers()["Authorization"] == "Bearer secret"
    assert isinstance(make_client({}), MockIPhoneClient)


# ------------------------------------------------------------------ Phase 4 HTTP

class _Handler(BaseHTTPRequestHandler):
    delay = 0.0
    last_body = None

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        if self.headers.get("Authorization") != "Bearer k":
            return self._send(401, {"error": "unauthorized"})
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": "gemma-test"}]})
        self._send(404, {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).last_body = body
        if self.headers.get("Authorization") != "Bearer k":
            return self._send(401, {"error": "unauthorized"})
        time.sleep(type(self).delay)
        content = '```json\n{"assessment": "in_progress", "reason": "moving", "confidence": 0.6}\n```'
        self._send(200, {"model": "gemma-test", "choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.fixture
def server():
    _Handler.delay = 0.0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_iphone_client_openai_chat(server):
    c = IPhoneClient(base_url=server, api_key="k", timeout_sec=5)
    assert c.health()["ok"] and c.resolve_model() == "gemma-test"
    sup = Supervisor(client=c)
    r = sup.evaluate(make_input())
    assert r.response.ok and r.decision.assessment == Assessment.IN_PROGRESS
    req = json.loads(_Handler.last_body)
    parts = req["messages"][1]["content"]
    assert req["model"] == "gemma-test" and req["temperature"] == 0.0
    assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_iphone_client_errors(server):
    r = IPhoneClient(base_url=server, api_key="wrong", model="m").evaluate(build_prompt(make_input()))
    assert not r.ok and r.error.startswith("http_401")

    _Handler.delay = 1.0
    r = IPhoneClient(base_url=server, api_key="k", model="m", timeout_sec=0.2).evaluate(build_prompt(make_input()))
    assert not r.ok and r.error == "timeout"

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    c = IPhoneClient(base_url=f"http://127.0.0.1:{port}", api_key="k", model="m")
    r = c.evaluate(build_prompt(make_input()))
    assert not r.ok and r.error.startswith("connection_refused")
    assert c.health()["ok"] is False


def test_iphone_client_supervisor_multipart(server):
    c = IPhoneClient(base_url=server, api_key="k", model="m", api="supervisor")
    c.evaluate(build_prompt(make_input()), {"task_instruction": "pick"})
    body = _Handler.last_body
    assert b'name="context"; filename="context.json"' in body and b'filename="image_1.jpg"' in body
