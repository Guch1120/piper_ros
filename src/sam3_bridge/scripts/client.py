# client.py（Python3.8 / HSRコンテナ）
import grpc
import ping_pb2
import ping_pb2_grpc

def run():
    # --network=host なので localhost で到達可能
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = ping_pb2_grpc.PingServiceStub(channel)
        response = stub.Ping(
            ping_pb2.PingRequest(message="Hello from HSR!"),
            timeout=3.0
        )
        print(f"[HSR] 受信: {response.message}")

if __name__ == "__main__":
    run()
