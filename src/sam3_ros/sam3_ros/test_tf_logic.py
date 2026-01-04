
import unittest
from unittest.mock import MagicMock
import numpy as np
import rclpy
from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import Header
from cv_bridge import CvBridge
import cv2
import sys
import os

# Add package path
sys.path.append(os.getcwd())
try:
    from sam3_ros.sam3_node import Sam3Node
except ImportError:
    sys.path.append(os.path.join(os.getcwd(), 'src/sam3_ros'))
    from sam3_ros.sam3_node import Sam3Node

class TestSam3TF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = Sam3Node()
        # Mock tracker
        self.node.tracker = MagicMock()
        # Mock TF broadcaster
        self.node.tf_broadcaster = MagicMock()
        
        self.bridge = CvBridge()

    def test_tf_publishing(self):
        # 1. Setup Camera Info
        info_msg = CameraInfo()
        info_msg.header.frame_id = "camera_color_optical_frame"
        info_msg.width = 640
        info_msg.height = 480
        # Simple pinhole: fx=fy=500, cx=320, cy=240
        info_msg.k = [500.0, 0.0, 320.0, 
                      0.0, 500.0, 240.0, 
                      0.0, 0.0, 1.0]
        info_msg.p = [500.0, 0.0, 320.0, 0.0,
                      0.0, 500.0, 240.0, 0.0,
                      0.0, 0.0, 1.0, 0.0]
        
        self.node.info_callback(info_msg)
        
        # 2. Setup Dummy Images
        # RGB: 640x480
        rgb_img = np.zeros((480, 640, 3), dtype=np.uint8)
        rgb_msg = self.bridge.cv2_to_imgmsg(rgb_img, encoding="rgb8")
        rgb_msg.header.frame_id = "camera_color_optical_frame"
        
        # Depth: 640x480, constant 1000mm (1 meter)
        depth_img = np.ones((480, 640), dtype=np.uint16) * 1000
        depth_msg = self.bridge.cv2_to_imgmsg(depth_img, encoding="mono16") # passthrough usually implies mono16 for depth
        depth_msg.header = rgb_msg.header
        
        # 3. Mock Tracker Output
        # Mask at center (320, 240)
        mask = np.zeros((480, 640), dtype=np.uint8)
        # 10x10 square at center
        mask[235:245, 315:325] = 255
        self.node.tracker.init_track.return_value = [mask]
        
        # 4. Set prompt to enable tracking
        self.node.current_prompt = "test"
        self.node.tracking_active = False
        
        # 5. Run Callback
        self.node.image_depth_callback(rgb_msg, depth_msg)
        
        # 6. Verify TF
        self.node.tf_broadcaster.sendTransform.assert_called_once()
        args = self.node.tf_broadcaster.sendTransform.call_args[0]
        t = args[0]
        
        print(f"Translation: x={t.transform.translation.x}, y={t.transform.translation.y}, z={t.transform.translation.z}")
        
        # Expected:
        # u ~ 320, v ~ 240
        # ray = (0, 0, 1)
        # depth = 1.0
        # x = 0, y = 0, z = 1.0
        
        self.assertAlmostEqual(t.transform.translation.z, 1.0, places=2)
        self.assertAlmostEqual(t.transform.translation.x, 0.0, places=1)
        self.assertAlmostEqual(t.transform.translation.y, 0.0, places=1)
        self.assertEqual(t.child_frame_id, "sam3_target")

if __name__ == '__main__':
    unittest.main()
