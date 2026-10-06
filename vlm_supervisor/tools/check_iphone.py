"""Phase 4: iPhone VLM サーバとの疎通確認 (ROS 不要).

  # ホスト PC で (別ターミナルで USB 転送: Local_LLM_by_using_MobilePhone/scripts/iphone/proxy.sh 8080 8080)
  source ~/yamaguchi/Local_LLM_by_using_MobilePhone/scripts/iphone/get_api_key.sh
  export VLM_API_KEY="$API_KEY"
  cd ~/yamaguchi/piper_ros && python3 -m vlm_supervisor.tools.check_iphone [--image test.jpg]

/health, /v1/models を確認し, 短い text(+image) 問い合わせで JSON 応答・latency を測る.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from vlm_supervisor.core.decision_parser import parse_decision
from vlm_supervisor.core.iphone_client import IPhoneClient, MockIPhoneClient
from vlm_supervisor.core.models import ImageFrame
from vlm_supervisor.core.prompt_builder import SHADOW_SYSTEM_PROMPT, Prompt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8080")
    ap.add_argument("--api-key-env", default="VLM_API_KEY")
    ap.add_argument("--model", default=None)
    ap.add_argument("--image", default=None, help="JPEG/PNG file to send")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--mock", action="store_true", help="iPhone の代わりに MockIPhoneClient を使う")
    a = ap.parse_args()

    if a.mock:
        client = MockIPhoneClient()
    else:
        key = os.environ.get(a.api_key_env)
        if not key:
            print(f"[WARN] ${a.api_key_env} is empty; authenticated routes will fail", file=sys.stderr)
        client = IPhoneClient(base_url=a.base_url, api_key=key, model=a.model, timeout_sec=a.timeout)

    h = client.health()
    print("health:", json.dumps(h, ensure_ascii=False, indent=1))
    if not h.get("ok"):
        print("[ERROR] health check failed. USB 転送 (proxy.sh) と iPhone アプリ(前面表示)を確認", file=sys.stderr)
        return 1

    images = []
    if a.image:
        with open(a.image, "rb") as f:
            data = f.read()
        mime = "image/png" if a.image.lower().endswith(".png") else "image/jpeg"
        images.append(ImageFrame(timestamp=None, frame_id="", width=0, height=0, mime_type=mime, data=data))
    user = ("Task: check the connection. Describe the image in the reason field if one is attached. "
            "Use assessment \"uncertain\" and intervention \"FOLLOW_GRAPH\". Return only the JSON object.")
    resp = client.evaluate(Prompt(system=SHADOW_SYSTEM_PROMPT, user_text=user, images=images,
                                  image_labels=["test image"] if images else []))
    print(f"response ok={resp.ok} error={resp.error} latency={resp.latency_sec:.2f}s model={resp.model}")
    print("text:", resp.text)
    if resp.ok:
        d = parse_decision(resp.text)
        print("parsed:", json.dumps(d.to_dict(), ensure_ascii=False, indent=1))
        return 0 if d.valid else 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
