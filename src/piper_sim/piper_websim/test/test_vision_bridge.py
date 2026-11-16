import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import rclpy
from rclpy.executors import MultiThreadedExecutor
from sensor_msgs.msg import CompressedImage, Image
from piper_websim.vision_bridge import VisionBridge
from rclpy.node import Node

received = {}
ready = threading.Event()

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        received.update(json.loads(self.rfile.read(int(self.headers['content-length']))))
        self.send_response(200)
        self.send_header('content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"labels":[{"label":"box"}]}')
        ready.set()
    def log_message(self, *_):
        pass

class Probe(Node):
    def __init__(self):
        super().__init__('vision_bridge_probe')
        self.image = self.create_publisher(CompressedImage, '/camera/color/image_raw/compressed', 10)
        self.depth = self.create_publisher(Image, '/camera/depth/image_raw', 10)
        self.create_timer(0.2, self.publish_once)
    def publish_once(self):
        image = CompressedImage(); image.format = 'jpeg'; image.data = [1, 2, 3, 4]
        depth = Image(); depth.width = 2; depth.height = 1; depth.encoding = '16UC1'; depth.step = 4; depth.data = [0, 1, 2, 3]
        self.image.publish(image); self.depth.publish(depth)

rclpy.init()
server = HTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
bridge = VisionBridge(); bridge._endpoint = f'http://127.0.0.1:{server.server_port}/infer'
probe = Probe(); executor = MultiThreadedExecutor(); executor.add_node(bridge); executor.add_node(probe)
threading.Thread(target=executor.spin, daemon=True).start()
if not ready.wait(5):
    raise SystemExit('VISION_BRIDGE_TIMEOUT')
assert received['image']['format'] == 'jpeg'
assert received['depth']['encoding'] == '16UC1'
assert received['depth']['width'] == 2
print('VISION_BRIDGE_PASS')
executor.shutdown(); bridge.destroy_node(); probe.destroy_node(); server.shutdown(); rclpy.shutdown()
