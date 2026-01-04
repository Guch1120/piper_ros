
import unittest
from unittest.mock import MagicMock
import numpy as np
import rclpy
import sys
import os

# Add package path
sys.path.append(os.getcwd())
try:
    from sam3_ros.sam3_node import Sam3Node
except ImportError:
    sys.path.append(os.path.join(os.getcwd(), 'src/sam3_ros'))
    from sam3_ros.sam3_node import Sam3Node

class TestSam3Service(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = Sam3Node()
        self.node.tracker = MagicMock()
        # Mock logger
        self.node.get_logger = MagicMock()

    def test_start_tracking_no_image(self):
        request = MagicMock()
        request.prompt = "test"
        response = MagicMock()
        
        self.node.latest_cv_image = None
        
        resp = self.node.start_tracking_callback(request, response)
        
        self.assertFalse(resp.success)
        self.assertIn("No image", resp.message)
        self.assertFalse(self.node.tracking_active)

    def test_start_tracking_success(self):
        request = MagicMock()
        request.prompt = "test"
        response = MagicMock()
        
        # Mock image
        self.node.latest_cv_image = np.zeros((480, 640, 3), dtype=np.uint8)
        self.node.tracker.init_track.return_value = []
        
        resp = self.node.start_tracking_callback(request, response)
        
        self.assertTrue(resp.success)
        self.assertTrue(self.node.tracking_active)
        self.assertEqual(self.node.current_prompt, "test")
        self.node.tracker.init_track.assert_called_once()

    def test_stop_tracking(self):
        request = MagicMock()
        response = MagicMock()
        
        self.node.tracking_active = True
        self.node.current_prompt = "test"
        
        resp = self.node.stop_tracking_callback(request, response)
        
        self.assertTrue(resp.success)
        self.assertFalse(self.node.tracking_active)
        self.assertIsNone(self.node.current_prompt)

if __name__ == '__main__':
    unittest.main()
