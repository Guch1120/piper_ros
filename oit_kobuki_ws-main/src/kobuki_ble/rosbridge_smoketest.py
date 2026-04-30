#!/usr/bin/env python3

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import time


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def recv_http_headers(sock: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("WebSocket handshake response was empty")
        data += chunk
    return data


def send_text_frame(sock: socket.socket, message: str) -> None:
    payload = message.encode("utf-8")
    header = bytearray([0x81])
    payload_len = len(payload)

    if payload_len < 126:
        header.append(0x80 | payload_len)
    elif payload_len < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", payload_len))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", payload_len))

    mask = os.urandom(4)
    header.extend(mask)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(header + masked)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--path", default="/")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    time.sleep(args.delay)

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    expected_accept = base64.b64encode(
        hashlib.sha1(f"{key}{GUID}".encode("ascii")).digest()
    ).decode("ascii")

    with socket.create_connection((args.host, args.port), timeout=5.0) as sock:
        sock.settimeout(5.0)
        request = (
            f"GET {args.path} HTTP/1.1\r\n"
            f"Host: {args.host}:{args.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = recv_http_headers(sock).decode("ascii", errors="replace")

        if "101 Switching Protocols" not in response:
            raise RuntimeError(f"Handshake failed: {response}")
        if expected_accept not in response:
            raise RuntimeError("Unexpected Sec-WebSocket-Accept in handshake response")

        advertise = {
            "op": "advertise",
            "topic": "/cmd_vel",
            "type": "geometry_msgs/msg/Twist",
        }
        publish = {
            "op": "publish",
            "topic": "/cmd_vel",
            "msg": {
                "linear": {"x": 0.12, "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": 0.34},
            },
        }

        send_text_frame(sock, json.dumps(advertise, separators=(",", ":")))
        time.sleep(0.2)
        for _ in range(3):
            send_text_frame(sock, json.dumps(publish, separators=(",", ":")))
            time.sleep(0.2)
        print("rosbridge_publish_ok")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
