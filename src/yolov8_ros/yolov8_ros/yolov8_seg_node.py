#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image, CameraInfo
from piper_msgs.srv import YoloSeg
from std_srvs.srv import SetBool
from piper_msgs.msg import ObjectInfo, ObjectArray
from message_filters import Subscriber, ApproximateTimeSynchronizer
import cv2
import numpy as np
import torch
# Monkey patch torch.load to default weights_only=False to fix YOLOv8 loading issue with PyTorch 2.6+
_original_load = torch.load
def _load_wrapped(*args, **kwargs):
    if 'weights_only' not in kwargs:
         kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)
torch.load = _load_wrapped

from ultralytics import YOLO

class YOLOv8SegNode(Node):
    def __init__(self):
        super().__init__('yolov8_seg_node')

        # Parameters
        self.declare_parameter('model_path', 'yolov8n-seg.pt')
        self.declare_parameter('device', 'cpu') # 'cpu' or 'cuda'
        self.declare_parameter('conf_thres', 0.5)
        self.declare_parameter('iou_thres', 0.45)
        self.declare_parameter('auto_start', True)
        self.declare_parameter('target_classes', [])
        
        self.model_path = self.get_parameter('model_path').get_parameter_value().string_value
        self.device = self.get_parameter('device').get_parameter_value().string_value
        self.conf_thres = self.get_parameter('conf_thres').get_parameter_value().double_value
        self.iou_thres = self.get_parameter('iou_thres').get_parameter_value().double_value

        self.get_logger().info(f"Loading YOLOv8 model from {self.model_path} on {self.device}...")
        try:
            self.model = YOLO(self.model_path)
            self.model.to(self.device)
            self.get_logger().info("Model loaded successfully.")
        except Exception as e:
            self.get_logger().error(f"Failed to load model: {e}")
            raise e

        self.bridge = CvBridge()
        
        # Latest frames buffer
        self.latest_color_img = None
        self.latest_depth_img = None
        self.latest_header = None

        # Subscribers with synchronization
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        self.color_sub = Subscriber(self, Image, '/camera/camera/color/image_raw')
        self.depth_sub = Subscriber(self, Image, '/camera/camera/aligned_depth_to_color/image_raw')
        
        # Synchronsizer
        self.ts = ApproximateTimeSynchronizer([self.color_sub, self.depth_sub], queue_size=10, slop=0.1)
        self.ts.registerCallback(self.image_callback)

        # Service
        self.srv_trigger = self.create_service(YoloSeg, '~/trigger', self.trigger_callback)
        self.srv_enable = self.create_service(SetBool, '~/enable', self.enable_callback)

        # Publishers
        self.mask_pub = self.create_publisher(Image, '~/result_mask', 10)
        self.debug_pub = self.create_publisher(Image, '~/result_debug', 10)
        self.objects_pub = self.create_publisher(ObjectArray, '~/objects', 10)
        
        # Continuous Execution State
        self.target_classes = self.get_parameter('target_classes').get_parameter_value().string_array_value
        self.continuous_enabled = self.get_parameter('auto_start').get_parameter_value().bool_value
        
        self.get_logger().info(f"YOLOv8 Segmentation Node Initialized. Auto-start: {self.continuous_enabled}")

    def image_callback(self, color_msg, depth_msg):
        self.latest_color_img = color_msg
        self.latest_depth_img = depth_msg
        self.latest_header = color_msg.header
        
        if self.continuous_enabled:
            # Run inference immediately with current settings
            self.perform_inference(self.target_classes)

    def enable_callback(self, request, response):
        self.continuous_enabled = request.data
        response.success = True
        response.message = f"Continuous execution set to {self.continuous_enabled}"
        self.get_logger().info(response.message)
        return response

    def trigger_callback(self, request, response):
        # Update target classes if provided (even if empty, it might mean 'all')
        self.target_classes = request.target_classes
        self.get_logger().info(f"Updated target classes to: {self.target_classes}")
        
        return self.perform_inference(self.target_classes, response)

    def perform_inference(self, target_classes, response=None):
        # If response is None, it's called from image_callback (continuous), so we don't return response
        # We just publish topics.
        
        if self.latest_color_img is None or self.latest_depth_img is None:
            if response:
                response.success = False
                response.message = "No images received yet."
            return response

        try:
            # Convert ROS images to OpenCV
            cv_image = self.bridge.imgmsg_to_cv2(self.latest_color_img, desired_encoding='bgr8')
            cv_depth = self.bridge.imgmsg_to_cv2(self.latest_depth_img, desired_encoding='passthrough') # 16UC1 (mm)
            
            orig_h, orig_w = cv_image.shape[:2]

            # Run Inference
            results = self.model(cv_image, conf=self.conf_thres, iou=self.iou_thres, verbose=False)

            object_array_msg = ObjectArray()
            object_array_msg.header = self.latest_header
            
            # Combined mask for specific targets to publish
            combined_mask = np.zeros((orig_h, orig_w), dtype=np.uint8)
            detected_count = 0

            if results[0].masks is not None:
                masks = results[0].masks.data.cpu().numpy() # (N, H, W) in model resolution
                boxes = results[0].boxes.data.cpu().numpy() # (N, 6)

                for i, mask_tensor in enumerate(results[0].masks.data):
                    class_id = int(boxes[i][5])
                    class_name = self.model.names[class_id]
                    score = float(boxes[i][4])
                    
                    # Filtering
                    if target_classes and (class_name not in target_classes):
                        continue
                    
                    detected_count += 1
                    
                    # Resize mask to original image size
                    mask_np = mask_tensor.cpu().numpy()
                    mask_resized = cv2.resize(mask_np, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
                    binary_mask = (mask_resized > 0.5).astype(np.uint8)
                    
                    # Add to combined mask
                    combined_mask = cv2.bitwise_or(combined_mask, binary_mask)

                    # Extract Contour
                    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    contour_points = []
                    if contours:
                        # Find largest contour
                        main_contour = max(contours, key=cv2.contourArea)
                        
                        # approxPolyDP to reduce points if needed
                        epsilon = 0.005 * cv2.arcLength(main_contour, True)
                        approx = cv2.approxPolyDP(main_contour, epsilon, True)
                        
                        # Flatten: [u1, v1, u2, v2, ...]
                        # approx shape is (N, 1, 2)
                        for pt in approx:
                            contour_points.extend([int(pt[0][0]), int(pt[0][1])])

                    # Extract Depth
                    masked_depth = cv_depth[binary_mask == 1]
                    z_val = 0.0
                    pos_x = 0.0 # Placeholder
                    pos_y = 0.0 # Placeholder

                    if masked_depth.size > 0:
                        valid_depth = masked_depth[masked_depth > 0]
                        if valid_depth.size > 0:
                            # Use median for robustness
                            z_mm = np.median(valid_depth)
                            z_val = z_mm / 1000.0 # mm to m

                    # Create ObjectInfo
                    obj_info = ObjectInfo()
                    obj_info.class_name = class_name
                    obj_info.score = score
                    obj_info.x = pos_x
                    obj_info.y = pos_y
                    obj_info.z = z_val
                    obj_info.contour_points = contour_points
                    
                    object_array_msg.objects.append(obj_info)
                    
                    # Log only if it's a trigger response or debug level, to avoid spamming continuous log
                    if response: 
                        self.get_logger().info(f"Target '{class_name}': Depth={z_val:.3f}m, Points={len(contour_points)//2}")

            # Publish Objects
            self.objects_pub.publish(object_array_msg)
            
            # Publish result images
            if detected_count > 0:
                masked_img_msg = self.bridge.cv2_to_imgmsg(combined_mask * 255, encoding='mono8')
                masked_img_msg.header = self.latest_header
                self.mask_pub.publish(masked_img_msg)
                
                # Debug image with all detections (even non-targets, for context)
                res_plotted = results[0].plot()
                debug_msg = self.bridge.cv2_to_imgmsg(res_plotted, encoding='bgr8')
                debug_msg.header = self.latest_header
                self.debug_pub.publish(debug_msg)
                
                if response:
                    response.success = True
                    response.message = f"Detected {detected_count} target objects."
            else:
                if response:
                    response.success = True # Success technically, just nothing found
                    response.message = "No target objects detected."
                
                # Debug image
                debug_msg = self.bridge.cv2_to_imgmsg(cv_image, encoding='bgr8')
                debug_msg.header = self.latest_header
                self.debug_pub.publish(debug_msg)
            
            if response:
                return response

        except Exception as e:
            self.get_logger().error(f"Error during inference: {e}")
            if response:
                response.success = False
                response.message = str(e)
                return response

def main(args=None):
    rclpy.init(args=args)
    node = YOLOv8SegNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
