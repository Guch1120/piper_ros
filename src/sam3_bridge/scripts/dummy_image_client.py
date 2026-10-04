#!/usr/bin/env python3

import grpc
import numpy as np
import cv2
import segment_pb2
import segment_pb2_grpc

def run():
    W, H = 640, 480

    # ダミー画像生成（黒画像）
    dummy = np.zeros((H, W, 3), dtype=np.uint8)

    # JPEG圧縮
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
    _, jpeg = cv2.imencode(".jpg", dummy, encode_param)
    jpeg_bytes = jpeg.tobytes()

    print(f"[HSR] ダミー画像サイズ: {len(jpeg_bytes)} bytes")

    with grpc.insecure_channel("localhost:50051") as channel:
        stub = segment_pb2_grpc.SegmentServiceStub(channel)
        response = stub.SegmentImage(
            segment_pb2.ImageRequest(
                image=jpeg_bytes,
                width=W,
                height=H,
            ),
            timeout=3.0
        )
        print(f"[HSR] SAM3から返信: {response.message}")
        print(f"[HSR] 返信サイズ: {response.width}x{response.height}")

if __name__ == "__main__":
    run()