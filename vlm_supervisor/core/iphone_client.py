"""iPhone VLM との通信 (Phase 4). Supervisor 自身には通信処理を持たせない.

接続:  Linux 127.0.0.1:<port>  --USB (usbmuxd / iproxy or pymobiledevice3)-->  iPhone:8080
       Local_LLM_by_using_MobilePhone/scripts/iphone/proxy.sh 8080 8080 で転送する.

API mode:
  openai_chat : 現在の iPhone アプリが持つ POST /v1/chat/completions を使う (画像は data URL).
  supervisor  : 将来 iPhone 側に POST /v1/supervisor/evaluate を追加した場合の multipart 版
                (context.json + image_*.jpg). 現時点ではアプリ側未実装.

依存を増やさないため標準ライブラリ (urllib) のみ使用. API key はログに出さない.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .models import VLMResponse
from .prompt_builder import Prompt


class VLMClient:
    """Supervisor から見た VLM client の interface."""

    def evaluate(self, prompt: Prompt, context: Optional[Dict[str, Any]] = None) -> VLMResponse:
        raise NotImplementedError

    def health(self) -> Dict[str, Any]:
        return {"ok": True}


class MockIPhoneClient(VLMClient):
    """iPhone アプリ無しで開発するための固定応答 client.

    responses を与えると呼び出しごとに順番に返す (最後の要素を繰り返す).
    delay_sec / fail_with で timeout や通信失敗の挙動も模擬できる.
    """

    DEFAULT = {
        "assessment": "uncertain",
        "reason": "mock response",
        "confidence": 0.5,
        "intervention": "FOLLOW_GRAPH",
    }

    def __init__(self, responses: Optional[List[Any]] = None, delay_sec: float = 0.0,
                 fail_with: Optional[str] = None):
        self._responses = list(responses) if responses else [self.DEFAULT]
        self._i = 0
        self._delay = delay_sec
        self._fail_with = fail_with
        self.requests: List[Tuple[Prompt, Optional[Dict[str, Any]]]] = []

    def evaluate(self, prompt: Prompt, context: Optional[Dict[str, Any]] = None) -> VLMResponse:
        self.requests.append((prompt, context))
        t0 = time.monotonic()
        if self._delay:
            time.sleep(self._delay)
        if self._fail_with:
            return VLMResponse(ok=False, error=self._fail_with, latency_sec=time.monotonic() - t0, model="mock")
        r = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        text = r if isinstance(r, str) else json.dumps(r)
        return VLMResponse(ok=True, text=text, latency_sec=time.monotonic() - t0, model="mock")

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "mock": True}


class IPhoneClient(VLMClient):
    def __init__(self, base_url: str = "http://127.0.0.1:8080", api_key: Optional[str] = None,
                 model: Optional[str] = None, api: str = "openai_chat", timeout_sec: float = 60.0,
                 connect_timeout_sec: float = 3.0, max_tokens: int = 256, temperature: float = 0.0):
        if api not in ("openai_chat", "supervisor"):
            raise ValueError(f"unknown api mode: {api}")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.api = api
        self.timeout_sec = timeout_sec
        self.connect_timeout_sec = connect_timeout_sec
        self.max_tokens = max_tokens
        self.temperature = temperature

    # ------------------------------------------------------------- low level

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if content_type:
            h["Content-Type"] = content_type
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _request(self, method: str, path: str, body: Optional[bytes] = None,
                 content_type: Optional[str] = None, timeout: Optional[float] = None) -> Tuple[int, bytes]:
        req = urllib.request.Request(self.base_url + path, data=body, method=method,
                                     headers=self._headers(content_type))
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_sec) as resp:
            return resp.status, resp.read()

    def _call(self, method: str, path: str, body: Optional[bytes] = None,
              content_type: Optional[str] = None, timeout: Optional[float] = None
              ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """(json, error). error は timeout / connection_refused / http_<code>: ... / invalid_json 等."""
        try:
            _, data = self._request(method, path, body, content_type, timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            return None, f"http_{e.code}: {detail}"
        except (socket.timeout, TimeoutError):
            return None, "timeout"
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return None, "timeout"
            if isinstance(reason, ConnectionRefusedError):
                return None, "connection_refused (USB port forward / iPhone app not running?)"
            return None, f"connection_error: {reason}"
        except (ConnectionError, OSError) as e:
            return None, f"connection_error: {e}"
        try:
            return json.loads(data.decode("utf-8")), None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "invalid_json"

    # ------------------------------------------------------------- public

    def health(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"base_url": self.base_url}
        h, err = self._call("GET", "/health", timeout=self.connect_timeout_sec)
        out["health"] = h if err is None else {"error": err}
        if err is None:
            m, err2 = self._call("GET", "/v1/models", timeout=self.connect_timeout_sec)
            out["models"] = m if err2 is None else {"error": err2}
        out["ok"] = err is None
        return out

    def resolve_model(self) -> Optional[str]:
        if self.model:
            return self.model
        m, err = self._call("GET", "/v1/models", timeout=self.connect_timeout_sec)
        if err is None and m and m.get("data"):
            self.model = m["data"][0].get("id")
        return self.model

    def evaluate(self, prompt: Prompt, context: Optional[Dict[str, Any]] = None) -> VLMResponse:
        t0 = time.monotonic()
        if self.api == "supervisor":
            resp = self._evaluate_supervisor(prompt, context)
        else:
            resp = self._evaluate_openai(prompt)
        resp.latency_sec = time.monotonic() - t0
        return resp

    def _evaluate_openai(self, prompt: Prompt) -> VLMResponse:
        model = self.resolve_model()
        if not model:
            return VLMResponse(ok=False, error="no model (GET /v1/models failed or empty; set vlm.model)")
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt.user_text}]
        for img in prompt.images:
            url = f"data:{img.mime_type};base64," + base64.b64encode(img.data).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": url}})
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": content},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        data, err = self._call("POST", "/v1/chat/completions", json.dumps(body).encode("utf-8"),
                               "application/json")
        if err is not None:
            return VLMResponse(ok=False, error=err, model=model)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return VLMResponse(ok=False, error="unexpected_response_shape", model=model, raw=data)
        if isinstance(text, list):  # content parts で返る実装への保険
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        return VLMResponse(ok=True, text=text or "", model=data.get("model", model), raw=_strip_raw(data))

    def _evaluate_supervisor(self, prompt: Prompt, context: Optional[Dict[str, Any]]) -> VLMResponse:
        boundary = uuid.uuid4().hex
        fields: List[Tuple[str, str, str, bytes]] = []
        payload = {"system": prompt.system, "prompt": prompt.user_text, "context": context or {},
                   "image_labels": prompt.image_labels, "model": self.model,
                   "max_tokens": self.max_tokens, "temperature": self.temperature}
        fields.append(("context", "context.json", "application/json", json.dumps(payload).encode("utf-8")))
        for i, img in enumerate(prompt.images):
            ext = "jpg" if img.mime_type == "image/jpeg" else "png"
            fields.append((f"image_{i}", f"image_{i}.{ext}", img.mime_type, img.data))
        body = b""
        for name, fname, ctype, data in fields:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{fname}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n").encode("utf-8") + data + b"\r\n"
        body += f"--{boundary}--\r\n".encode("utf-8")
        data, err = self._call("POST", "/v1/supervisor/evaluate", body, f"multipart/form-data; boundary={boundary}")
        if err is not None:
            return VLMResponse(ok=False, error=err, model=self.model)
        # 期待形: {"text": "...", "model": "..."} もしくは decision JSON そのもの
        text = data.get("text") if isinstance(data, dict) and "text" in data else json.dumps(data)
        return VLMResponse(ok=True, text=text, model=data.get("model", self.model), raw=_strip_raw(data))


def _strip_raw(data: Any) -> Any:
    """ログ保存用. 巨大になり得るフィールドは落とす."""
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k not in ("data",)}
    return data


def make_client(cfg: Dict[str, Any]) -> VLMClient:
    """supervisor.yaml の vlm セクションから client を作る.

    api_key は cfg["api_key_env"] (既定 VLM_API_KEY) の環境変数, または cfg["api_key_file"] から読む.
    """
    kind = cfg.get("client", "mock")
    if kind == "mock":
        return MockIPhoneClient(responses=cfg.get("mock_responses"), delay_sec=float(cfg.get("mock_delay_sec", 0.0)))
    if kind != "iphone":
        raise ValueError(f"unknown vlm.client: {kind}")
    key = os.environ.get(cfg.get("api_key_env", "VLM_API_KEY"))
    key_file = cfg.get("api_key_file")
    if not key and key_file and os.path.exists(os.path.expanduser(key_file)):
        with open(os.path.expanduser(key_file), encoding="utf-8") as f:
            key = f.read().strip()
    return IPhoneClient(
        base_url=cfg.get("base_url", "http://127.0.0.1:8080"),
        api_key=key or None,
        model=cfg.get("model") or None,
        api=cfg.get("api", "openai_chat"),
        timeout_sec=float(cfg.get("timeout_sec", 60.0)),
        connect_timeout_sec=float(cfg.get("connect_timeout_sec", 3.0)),
        max_tokens=int(cfg.get("max_tokens", 256)),
        temperature=float(cfg.get("temperature", 0.0)),
    )
