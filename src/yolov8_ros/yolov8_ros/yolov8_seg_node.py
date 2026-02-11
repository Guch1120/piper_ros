#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image, CameraInfo
from piper_msgs.srv import YoloSeg
from std_srvs.srv import SetBool
from piper_msgs.msg import ObjectInfo, ObjectArray
from std_msgs.msg import String
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
from sensor_msgs.msg import PointCloud2, PointField
from sensor_msgs_py import point_cloud2
import tf2_ros
from tf2_ros import Buffer, TransformListener
# import tf_transformations # Removed to avoid dependency


class YOLOv8SegNode(Node):
    """
    YOLOv8 Segmentation Node
    
    Subscribed Topics:
    - /camera/camera/color/image_raw (sensor_msgs/Image): RGB画像
    - /camera/camera/depth/image_rect_raw (sensor_msgs/Image): 生の深度画像 (Rectified Raw Depth, 16UC1)
    - /camera/camera/color/camera_info (sensor_msgs/CameraInfo): RGBカメラの内部パラメータ
    - /camera/camera/depth/camera_info (sensor_msgs/CameraInfo): Depthカメラの内部パラメータ
    
    Published Topics:
    - ~/objects (piper_msgs/ObjectArray): 検出された物体の情報（クラス名, スコア, 角度誤差(x=Yaw, y=Pitch), 深度(z)）
    - ~/result_mask (sensor_msgs/Image): 検出物体のバイナリマスク画像 (mono8)
    - ~/result_debug (sensor_msgs/Image): バウンディングボックスとラベルを描画したデバッグ用画像 (bgr8)
    
    Services:
    - ~/trigger (piper_msgs/YoloSeg): 1回だけ検出を実行するトリガー
    - ~/enable (std_srvs/SetBool): 連続検出の有効/無効を切り替える
    """
    def __init__(self):
        super().__init__('yolov8_seg_node')

        # Parameters
        self.declare_parameter('model_path', 'yolov8n-seg.pt')
        self.declare_parameter('device', 'cuda') # 'cpu' or 'cuda'
        self.declare_parameter('conf_thres', 0.5)
        self.declare_parameter('iou_thres', 0.45)
        self.declare_parameter('auto_start', True)
        self.declare_parameter('target_classes', '') # Default to empty string
        
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
                
        # Intrinsics
        self.color_info = None
        self.depth_info = None

        # Subscribers with synchronization
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )
        
        # NOTE: Using raw depth now, not aligned
        self.color_sub = Subscriber(self, Image, '/camera/camera/color/image_raw')
        self.depth_sub = Subscriber(self, Image, '/camera/camera/depth/image_rect_raw') # Rectified raw depth
        self.color_info_sub = self.create_subscription(CameraInfo, '/camera/camera/color/camera_info', self.color_info_callback, 10)
        self.depth_info_sub = self.create_subscription(CameraInfo, '/camera/camera/depth/camera_info', self.depth_info_callback, 10)
        
        # Synchronsizer
        self.ts = ApproximateTimeSynchronizer([self.color_sub, self.depth_sub], queue_size=10, slop=0.2) # Increased slop slightly
        self.ts.registerCallback(self.image_callback)

        # Service
        self.srv_trigger = self.create_service(YoloSeg, '~/trigger', self.trigger_callback)
        self.srv_enable = self.create_service(SetBool, '~/enable', self.enable_callback)

        # Publishers
        self.mask_pub = self.create_publisher(Image, '~/result_mask', 10)
        self.debug_pub = self.create_publisher(Image, '~/result_debug', 10)
        self.objects_pub = self.create_publisher(ObjectArray, '~/objects', 10)
        self.result_cloud_pub = self.create_publisher(PointCloud2, '~/result_cloud', 10)
        
        # Target Classes Subscriber
        self.target_classes_sub = self.create_subscription(String, '~/target_classes', self.target_classes_callback, 10)
        
        # TF Buffer & Listener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # Continuous Execution State
        # Handle target_classes parameter (can be string array or comma-separated string)
        # Force retrieve as string first to see if it works, or check type explicitly
        target_classes_param = self.get_parameter('target_classes')
        
        raw_value = target_classes_param.value
        self.get_logger().info(f"Target Classes Raw Value: {raw_value}, Type: {type(raw_value)}")

        if isinstance(raw_value, str):
            if raw_value:
                 self.target_classes = [s.strip() for s in raw_value.split(',')]
            else:
                 self.target_classes = []
        elif isinstance(raw_value, list):
             self.target_classes = raw_value
        else:
             self.target_classes = []
        
        self.continuous_enabled = self.get_parameter('auto_start').get_parameter_value().bool_value
        
        self.get_logger().info(f"YOLOv8 Segmentation Node Initialized. Auto-start: {self.continuous_enabled}, Target Classes: {self.target_classes}")

    def color_info_callback(self, msg):
        self.color_info = msg
        
    def depth_info_callback(self, msg):
        self.depth_info = msg

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
    
    
    def target_classes_callback(self, msg):
        """Callback to update target classes dynamically from a string topic."""
        raw_value = msg.data
        if raw_value:
             self.target_classes = [s.strip() for s in raw_value.split(',')]
        else:
             self.target_classes = []
        self.get_logger().info(f"Target classes updated via topic to: {self.target_classes}")
        
        # Optionally trigger inference if continuous mode is disabled but we want to see result immediately?
        # For now, just update state. If continuous is on, next frame will use it.

    def calculate_angle(self, center_x, center_y, camera_info):
        """Calculate yaw and pitch angles from image center to verified object center."""
        if camera_info is None:
            return 0.0, 0.0
            
        fx = camera_info.k[0]
        fy = camera_info.k[4]
        cx = camera_info.k[2]
        cy = camera_info.k[5]
        
        # Angle = atan((x - cx) / fx)
        yaw = np.arctan((center_x - cx) / fx)
        pitch = np.arctan((center_y - cy) / fy)
        
        return float(yaw), float(pitch)

    def project_rgb_to_depth(self, u_rgb, v_rgb, depth_z=1.0):
        """
        Approximate projection from RGB pixel to Depth pixel.
        Assuming parallel axes and only baseline offset on X-axis (standard stereo).
        
        u_depth = (u_rgb - cx_rgb) * (fx_depth / fx_rgb) + cx_depth + (baseline * fx_depth / Z)
        v_depth = (v_rgb - cy_rgb) * (fy_depth / fy_rgb) + cy_depth
        
        Since we don't know Z yet, we can't perfectly map the disparity.
        HOWEVER, if we are just checking if it's "in view", we can approximate or use an iterative approach.
        
        BUT, the implementation plan says: "Servo to center".
        If we assume the cameras are parallel, the center of RGB and center of Depth are offset by fixed baseline.
        
        For D435i: distance between RGB and Left IR (Depth origin) is ~15mm.
        RGB is to the right of Depth (usually).
        
        Let's use a simpler check:
        1. Calculate vector in RGB frame.
        2. Rotate/Translate to Depth frame (Rigid transform).
        3. Project back to Depth pixel.
        
        Simpler approximation for now (assuming Z >> baseline):
        The angle from RGB is roughly the angle from Depth.
        So verify if (yaw, pitch) is within Depth FOV.
        """
        if self.color_info is None or self.depth_info is None:
            return -1, -1 # Invalid

        # Intrinsic parameters
        fx_rgb = self.color_info.k[0]
        cx_rgb = self.color_info.k[2]
        fy_rgb = self.color_info.k[4]
        cy_rgb = self.color_info.k[5]
        
        fx_d = self.depth_info.k[0]
        cx_d = self.depth_info.k[2]
        fy_d = self.depth_info.k[4]
        cy_d = self.depth_info.k[5]

        # Calculate angle of the pixel in RGB frame
        # x = (u - cx) * Z / fx
        # We don't know Z, but we know the ray direction.
        # ray_x = (u - cx) / fx
        
        # Baseline offset (RGB to Depth)
        # T_rgb_depth = [-0.015, 0, 0] (approx 15mm for D435)
        # But without TF, we can just use the angles.
        # Since baseline is small, for objects > 0.5m, the parallax is small.
        # We can try to map purely by angle first.
        
        # Normalized coordinates in RGB
        x_norm = (u_rgb - cx_rgb) / fx_rgb
        y_norm = (v_rgb - cy_rgb) / fy_rgb
        
        # Reproject to Depth (ignoring translation for infinite distance / far check)
        # u_d_inf = x_norm * fx_d + cx_d
        # v_d_inf = y_norm * fy_d + cy_d
        
        # Ideally, we should add disparity: disparity = (baseline * fx) / Z
        # Since we want to know if it's in the frame, we can assume a minimum Z (e.g. 0.3m) 
        # to see the worst case disparity or just check center.
        
        # Let's return the "infinity" projection pixel for now, as it's the target location for servoing.
        u_d = int(x_norm * fx_d + cx_d)
        v_d = int(y_norm * fy_d + cy_d)
        
        return u_d, v_d

    def generate_pointcloud(self, cv_depth, cv_rgb, combined_mask):
        """
        Generate Colored PointCloud2 from Depth image and RGB image, filtered by mask.
        Corrects for RGB-Depth extrinsic calibration.
        """
        if self.depth_info is None or self.color_info is None:
            return None

        # 1. Look up transform from Depth to RGB
        try:
            # We want to transform Depth points (in Depth frame) to RGB frame (to color them and output in RGB frame)
            # OR output in Depth frame and project RGB pixels to it?
            # User wants "detected area pointcloud".
            # Usually we visualize in RGB frame (Color Optical Frame).
            # So: Points in Depth Frame -> Transform to RGB Frame -> Output
            
            # tf: Target=RGB, Source=Depth
            t = self.tf_buffer.lookup_transform(
                'camera_color_optical_frame', # Target
                'camera_depth_optical_frame', # Source
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=0.1)
            )
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException):
            # Fallback: identity if no TF (e.g. not published yet)
            # self.get_logger().warn("TF lookup failed, assuming identity for point cloud")
            return None # Skip if no TF for accuracy

        # TF Matrix
        trans = t.transform.translation
        rot = t.transform.rotation
        
        # Convert to matrix manually to avoid dependency
        tr_vec = [trans.x, trans.y, trans.z]
        # rot is x, y, z, w
        qx, qy, qz, qw = rot.x, rot.y, rot.z, rot.w
        
        # Quaternion to Rotation Matrix
        R = np.array([
            [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
            [2*qx*qy + 2*qz*qw, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
            [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx**2 - 2*qy**2]
        ])
        
        T_depth_to_rgb = np.eye(4)
        T_depth_to_rgb[0:3, 0:3] = R
        T_depth_to_rgb[0:3, 3] = tr_vec
        
        # Depth Intrinsics
        fx_d = self.depth_info.k[0]
        fy_d = self.depth_info.k[4]
        cx_d = self.depth_info.k[2]
        cy_d = self.depth_info.k[5]

        # RGB Intrinsics
        fx_rgb = self.color_info.k[0]
        fy_rgb = self.color_info.k[4]
        cx_rgb = self.color_info.k[2]
        cy_rgb = self.color_info.k[5]
        
        h, w = cv_depth.shape
        rgb_h, rgb_w = cv_rgb.shape[:2]

        # 2. Downsample for performance (Step = 4 or 8)
        step = 4 
        
        # Generate Grid
        # u: column index, v: row index
        v, u = np.mgrid[0:h:step, 0:w:step]
        z = cv_depth[0:h:step, 0:w:step]
        
        # Filter valid depth
        valid = (z > 0)
        z = z[valid] / 1000.0 # mm to m
        u = u[valid]
        v = v[valid]
        
        # 3. Back-project to 3D (Depth Frame)
        # X = (u - cx) * Z / fx
        x = (u - cx_d) * z / fx_d
        y = (v - cy_d) * z / fy_d
        
        # Points in Depth Frame: (N, 4) homogeneous
        N = len(x)
        if N == 0:
            return None
            
        points_depth = np.vstack((x, y, z, np.ones(N)))
        
        # 4. Transform to RGB Frame
        # points_rgb = T * points_depth
        points_rgb = T_depth_to_rgb @ points_depth # (4, N)
        
        X_rgb = points_rgb[0, :]
        Y_rgb = points_rgb[1, :]
        Z_rgb = points_rgb[2, :]
        
        # 5. Project to RGB Image Plane to find color and check mask
        # u_rgb = X * fx / Z + cx
        # Check Z > 0 to avoid division by zero (behind camera)
        valid_proj = Z_rgb > 0.01
        
        u_proj = (X_rgb[valid_proj] * fx_rgb / Z_rgb[valid_proj]) + cx_rgb
        v_proj = (Y_rgb[valid_proj] * fy_rgb / Z_rgb[valid_proj]) + cy_rgb
        
        # Round to integers
        u_proj = np.round(u_proj).astype(int)
        v_proj = np.round(v_proj).astype(int)
        
        # Filter inside image bounds
        in_bounds = (u_proj >= 0) & (u_proj < rgb_w) & (v_proj >= 0) & (v_proj < rgb_h)
        
        # Valid indices in the original points array
        valid_indices = np.where(valid_proj)[0][in_bounds]
        
        # Final valid points
        final_X = X_rgb[valid_indices]
        final_Y = Y_rgb[valid_indices]
        final_Z = Z_rgb[valid_indices]
        
        final_u = u_proj[in_bounds]
        final_v = v_proj[in_bounds]
        
        # 6. Check Mask (is point inside detection?)
        # combined_mask is (H, W), 255 or 0
        # If mask is provided
        if combined_mask is not None:
             in_mask = combined_mask[final_v, final_u] > 0
             
             final_X = final_X[in_mask]
             final_Y = final_Y[in_mask]
             final_Z = final_Z[in_mask]
             final_u = final_u[in_mask]
             final_v = final_v[in_mask]
        
        if len(final_X) == 0:
            return None

        # 7. Get Colors
        colors = cv_rgb[final_v, final_u] # (N, 3) BGR
        
        # Pack into PointCloud2
        # Setup structured array for PC2
        # Fields: x, y, z, rgb
        
        # RGB packing logic for ROS (float32 representing 0x00RRGGBB)
        # However, PointCloud2 usually takes packed bytes or specific struct.
        # Simplest way with sensor_msgs_py:
        # data = [[x, y, z, r, g, b], ...] and use fields.
        
        # But standard is packed float/int.
        # Let's use simple x, y, z fields first to test geometry.
        # Adding color needs bit manipulation or helper.
        
        # Standard RGB packing:
        # rgb = (r << 16) | (g << 8) | b
        # stored as float32
        
        # We need to swap BGR to RGB
        r = colors[:, 2].astype(np.uint32)
        g = colors[:, 1].astype(np.uint32)
        b = colors[:, 0].astype(np.uint32)
        rgb_int = (r << 16) | (g << 8) | b
        
        # Re-interpret as float32
        import struct
        # Vectorized way to cast uint32 to float32 (same bits)
        # Using a view
        rgb_float = np.array(rgb_int, dtype=np.uint32).view(np.float32)
        
        # Combine
        points_data = np.vstack((final_X, final_Y, final_Z, rgb_float)).T # (N, 4)
        
        # Create Header
        header = self.latest_header
        # Important: Frame ID should be what these points are in.
        # We transformed to camera_color_optical_frame.
        header.frame_id = "camera_color_optical_frame"
        
        fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='rgb', offset=12, datatype=PointField.FLOAT32, count=1),
        ]
        
        pc2_msg = point_cloud2.create_cloud(header, fields, points_data)
        return pc2_msg

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
            depth_h, depth_w = cv_depth.shape[:2]

            # Run Inference
            # Prepare classes filter
            classes_to_detect = None
            if target_classes:
                classes_to_detect = []
                # Invert model names: name -> id
                # self.model.names is usually {0: 'person', 1: 'bicycle', ...}
                name_to_id = {v: k for k, v in self.model.names.items()}
                
                for name in target_classes:
                    if name in name_to_id:
                        classes_to_detect.append(name_to_id[name])
                    else:
                        self.get_logger().warn(f"Target class '{name}' not found in model classes.")
            
            # Pass classes argument to filter at inference level
            results = self.model(cv_image, conf=self.conf_thres, iou=self.iou_thres, classes=classes_to_detect, verbose=False)

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
                    
                    # Filtering is now done at inference level, so we don't need to filter here again.
                    # But checking just in case logic changes is fine.
                    
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
                    center_x = 0
                    center_y = 0
                    
                    if contours:
                        # Find largest contour
                        main_contour = max(contours, key=cv2.contourArea)
                        
                        # Calculate Moments for Center
                        M = cv2.moments(main_contour)
                        if M["m00"] != 0:
                            center_x = int(M["m10"] / M["m00"])
                            center_y = int(M["m01"] / M["m00"])
                        else:
                            # Fallback to bounding box center
                            x, y, w, h = cv2.boundingRect(main_contour)
                            center_x = int(x + w / 2)
                            center_y = int(y + h / 2)
                        
                        # approxPolyDP to reduce points if needed
                        epsilon = 0.005 * cv2.arcLength(main_contour, True)
                        approx = cv2.approxPolyDP(main_contour, epsilon, True)
                        
                        # Flatten: [u1, v1, u2, v2, ...]
                        for pt in approx:
                            contour_points.extend([int(pt[0][0]), int(pt[0][1])])

                    # --- New Angle & Depth Logic ---
                    
                    # 1. Calculate Angle (Yaw, Pitch) from RGB intrinsics
                    yaw, pitch = self.calculate_angle(center_x, center_y, self.color_info)
                    
                    # 2. Project RGB Center to Depth Frame
                    u_d, v_d = self.project_rgb_to_depth(center_x, center_y)
                    
                    z_val = 0.0
                    
                    # 3. Check availability in Depth Frame
                    if 0 <= u_d < depth_w and 0 <= v_d < depth_h:
                        # Read depth at center (single pixel or small window)
                        # Let's verify a 3x3 window for robustness
                        depth_region = cv_depth[max(0, v_d-1):min(depth_h, v_d+2), max(0, u_d-1):min(depth_w, u_d+2)]
                        valid_depths = depth_region[depth_region > 0]
                        
                        if valid_depths.size > 0:
                            z_mm = np.median(valid_depths)
                            z_val = z_mm / 1000.0 # mm to m
                    
                    # Create ObjectInfo
                    obj_info = ObjectInfo()
                    obj_info.class_name = class_name
                    obj_info.score = score
                    
                    # Store Angles in X, Y
                    obj_info.x = yaw   # Yaw Angle (rad)
                    obj_info.y = pitch # Pitch Angle (rad)
                    
                    obj_info.z = z_val # Depth (m) or 0.0 if invalid
                    obj_info.contour_points = contour_points
                    
                    object_array_msg.objects.append(obj_info)
                    
                    # Log
                    if response: 
                        status = "Valid" if z_val > 0 else "No Depth/OutOfFOV"
                        self.get_logger().info(f"Target '{class_name}': Yaw={yaw:.3f}, Pitch={pitch:.3f}, Depth={z_val:.3f}m ({status})")

            # Publish Objects
            self.objects_pub.publish(object_array_msg)
            
            # Generate and Publish PointCloud
            if detected_count > 0:
                pc2_msg = self.generate_pointcloud(cv_depth, cv_image, combined_mask)
                if pc2_msg:
                    self.result_cloud_pub.publish(pc2_msg)
            
            # Publish result images
            if detected_count > 0:
                masked_img_msg = self.bridge.cv2_to_imgmsg(combined_mask * 255, encoding='mono8')
                masked_img_msg.header = self.latest_header
                self.mask_pub.publish(masked_img_msg)
                
                # Debug image with all detections
                res_plotted = results[0].plot()
                
                # Draw center point and status on debug image
                if object_array_msg.objects:
                    for obj in object_array_msg.objects:
                         # Re-calculate center for visualization (approx)
                         # We don't have the center easily here without re-looping or storing
                         # But results[0].plot() draws boxes.
                         pass

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
            import traceback
            traceback.print_exc()
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
