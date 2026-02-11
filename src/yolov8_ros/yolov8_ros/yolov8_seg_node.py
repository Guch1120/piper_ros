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
import struct

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
    - ~/result_cloud (sensor_msgs/PointCloud2): カラー点群
    
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

    def calculate_3d_centroid(self, cv_depth, mask_binary, step=4):
        """
        Calculate the 3D centroid of the object defined by mask_binary.
        
        1. Projects Depth pixels to RGB Frame using extrinsic/intrinsic params.
        2. Filter points that fall into 'mask_binary' (RGB frame).
        3. Compute Median Z, and Mean X/Y/Z.
        
        Returns:
            (x, y, z) in Camera Optical Frame (RGB Frame)
            Or None if no valid points.
        """
        if self.depth_info is None or self.color_info is None:
            return None

        # 1. Get Transform (Depth -> RGB)
        try:
            t = self.tf_buffer.lookup_transform(
                'camera_color_optical_frame', # Target
                'camera_depth_optical_frame', # Source
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=0.05) # Fast timeout
            )
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException, tf2_ros.ExtrapolationException):
            return None

        # Build Transform Matrix
        trans = t.transform.translation
        rot = t.transform.rotation
        
        qx, qy, qz, qw = rot.x, rot.y, rot.z, rot.w
        
        # Quaternion to Rot Matrix
        R = np.array([
            [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
            [2*qx*qy + 2*qz*qw, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
            [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx**2 - 2*qy**2]
        ])
        
        T_depth_to_rgb = np.eye(4)
        T_depth_to_rgb[0:3, 0:3] = R
        T_depth_to_rgb[0:3, 3] = [trans.x, trans.y, trans.z]
        
        # Intrinsics
        fx_d, fy_d = self.depth_info.k[0], self.depth_info.k[4]
        cx_d, cy_d = self.depth_info.k[2], self.depth_info.k[5]
        
        fx_rgb, fy_rgb = self.color_info.k[0], self.color_info.k[4]
        cx_rgb, cy_rgb = self.color_info.k[2], self.color_info.k[5]
        
        h, w = cv_depth.shape
        rgb_h, rgb_w = self.latest_color_img.height, self.latest_color_img.width

        # 2. Downsample and Backproject
        if mask_binary is None or np.count_nonzero(mask_binary) == 0:
            return None
            
        v, u = np.mgrid[0:h:step, 0:w:step]
        z = cv_depth[0:h:step, 0:w:step]
        
        valid = (z > 0)
        z = z[valid] / 1000.0 # m
        u = u[valid]
        v = v[valid]
        
        if len(z) == 0:
            return None

        # Backproject to Depth Frame 3D
        x_d = (u - cx_d) * z / fx_d
        y_d = (v - cy_d) * z / fy_d
        
        N = len(x_d)
        points_depth_hom = np.vstack((x_d, y_d, z, np.ones(N))) # (4, N)
        
        # Transform to RGB Frame
        points_rgb = T_depth_to_rgb @ points_depth_hom # (4, N)
        
        X_rgb = points_rgb[0, :]
        Y_rgb = points_rgb[1, :]
        Z_rgb = points_rgb[2, :]
        
        # Project to RGB Image Plane
        valid_proj = Z_rgb > 0.01
        
        X_rgb = X_rgb[valid_proj]
        Y_rgb = Y_rgb[valid_proj]
        Z_rgb = Z_rgb[valid_proj]
        
        if len(Z_rgb) == 0:
             return None

        u_proj = (X_rgb * fx_rgb / Z_rgb) + cx_rgb
        v_proj = (Y_rgb * fy_rgb / Z_rgb) + cy_rgb
        
        # Round and check bounds
        u_proj = np.round(u_proj).astype(int)
        v_proj = np.round(v_proj).astype(int)
        
        in_bounds = (u_proj >= 0) & (u_proj < rgb_w) & (v_proj >= 0) & (v_proj < rgb_h)
        
        u_proj = u_proj[in_bounds]
        v_proj = v_proj[in_bounds]
        
        # Check Mask
        in_mask = mask_binary[v_proj, u_proj] > 0
        
        # Filter 3D points
        final_X = X_rgb[in_bounds][in_mask]
        final_Y = Y_rgb[in_bounds][in_mask]
        final_Z = Z_rgb[in_bounds][in_mask]
        
        if len(final_Z) == 0:
            return None
            
        # Compute Centroid / Median
        median_z = np.median(final_Z)
        mean_x = np.mean(final_X)
        mean_y = np.mean(final_Y)
        
        return float(mean_x), float(mean_y), float(median_z)

    def generate_pointcloud_v2(self, cv_depth, cv_rgb, combined_mask):
        if self.depth_info is None or self.color_info is None:
            return None
            
        try:
             t = self.tf_buffer.lookup_transform('camera_color_optical_frame', 'camera_depth_optical_frame', rclpy.time.Time(), timeout=rclpy.duration.Duration(seconds=0.1))
        except:
             return None

        trans = t.transform.translation
        rot = t.transform.rotation
        
        qx, qy, qz, qw = rot.x, rot.y, rot.z, rot.w
        R = np.array([
            [1 - 2*qy**2 - 2*qz**2, 2*qx*qy - 2*qz*qw, 2*qx*qz + 2*qy*qw],
            [2*qx*qy + 2*qz*qw, 1 - 2*qx**2 - 2*qz**2, 2*qy*qz - 2*qx*qw],
            [2*qx*qz - 2*qy*qw, 2*qy*qz + 2*qx*qw, 1 - 2*qx**2 - 2*qy**2]
        ])
        T = np.eye(4)
        T[0:3, 0:3] = R
        T[0:3, 3] = [trans.x, trans.y, trans.z]
        
        fx_d, fy_d, cx_d, cy_d = self.depth_info.k[0], self.depth_info.k[4], self.depth_info.k[2], self.depth_info.k[5]
        fx_rgb, fy_rgb, cx_rgb, cy_rgb = self.color_info.k[0], self.color_info.k[4], self.color_info.k[2], self.color_info.k[5]
        
        h, w = cv_depth.shape
        step = 4
        v, u = np.mgrid[0:h:step, 0:w:step]
        z = cv_depth[0:h:step, 0:w:step]
        valid = z > 0
        z = z[valid] / 1000.0
        u, v = u[valid], v[valid]
        
        if len(z) == 0: return None
        
        x_d = (u - cx_d) * z / fx_d
        y_d = (v - cy_d) * z / fy_d
        
        points_d = np.vstack((x_d, y_d, z, np.ones(len(x_d))))
        points_rgb = T @ points_d
        
        X, Y, Z = points_rgb[0], points_rgb[1], points_rgb[2]
        
        valid_proj = Z > 0.01
        X, Y, Z = X[valid_proj], Y[valid_proj], Z[valid_proj]
        
        u_proj = np.round((X * fx_rgb / Z) + cx_rgb).astype(int)
        v_proj = np.round((Y * fy_rgb / Z) + cy_rgb).astype(int)
        
        rgb_h, rgb_w = cv_rgb.shape[:2]
        in_bounds = (u_proj >= 0) & (u_proj < rgb_w) & (v_proj >= 0) & (v_proj < rgb_h)
        
        u_proj = u_proj[in_bounds]
        v_proj = v_proj[in_bounds]
        X, Y, Z = X[in_bounds], Y[in_bounds], Z[in_bounds]
        
        if combined_mask is not None:
             in_mask = combined_mask[v_proj, u_proj] > 0
             X, Y, Z = X[in_mask], Y[in_mask], Z[in_mask]
             u_proj, v_proj = u_proj[in_mask], v_proj[in_mask]
             
        if len(X) == 0: return None
        
        colors = cv_rgb[v_proj, u_proj]
        r = colors[:, 2].astype(np.uint32)
        g = colors[:, 1].astype(np.uint32)
        b = colors[:, 0].astype(np.uint32)
        rgb_int = (r << 16) | (g << 8) | b
        rgb_float = np.array(rgb_int, dtype=np.uint32).view(np.float32)
        
        points_data = np.vstack((X, Y, Z, rgb_float)).T
        
        header = self.latest_header
        header.frame_id = "camera_color_optical_frame"
        fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='rgb', offset=12, datatype=PointField.FLOAT32, count=1),
        ]
        return point_cloud2.create_cloud(header, fields, points_data)

    def calculate_angle_from_3d(self, x, y, z):
        """Calculate Yaw/Pitch from 3D point in Camera frame."""
        yaw = np.arctan2(x, z)
        pitch = np.arctan2(y, z)
        return float(yaw), float(pitch)

    def perform_inference(self, target_classes, response=None):
        if self.latest_color_img is None or self.latest_depth_img is None:
            if response:
                response.success = False
                response.message = "No images received yet."
            return response

        try:
            cv_image = self.bridge.imgmsg_to_cv2(self.latest_color_img, desired_encoding='bgr8')
            cv_depth = self.bridge.imgmsg_to_cv2(self.latest_depth_img, desired_encoding='passthrough')
            
            orig_h, orig_w = cv_image.shape[:2]
            depth_h, depth_w = cv_depth.shape[:2]

            classes_to_detect = None
            if target_classes:
                classes_to_detect = []
                name_to_id = {v: k for k, v in self.model.names.items()}
                for name in target_classes:
                    if name in name_to_id:
                        classes_to_detect.append(name_to_id[name])
                    else:
                        self.get_logger().warn(f"Target class '{name}' not found in model classes.")
            
            results = self.model(cv_image, conf=self.conf_thres, iou=self.iou_thres, classes=classes_to_detect, verbose=False)

            object_array_msg = ObjectArray()
            object_array_msg.header = self.latest_header
            
            combined_mask = np.zeros((orig_h, orig_w), dtype=np.uint8)
            detected_count = 0
            
            debug_points = [] # For visualization

            if results[0].masks is not None:
                boxes = results[0].boxes.data.cpu().numpy()

                for i, mask_tensor in enumerate(results[0].masks.data):
                    class_id = int(boxes[i][5])
                    class_name = self.model.names[class_id]
                    score = float(boxes[i][4])
                    
                    detected_count += 1
                    
                    mask_np = mask_tensor.cpu().numpy()
                    mask_resized = cv2.resize(mask_np, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
                    binary_mask = (mask_resized > 0.5).astype(np.uint8)
                    
                    combined_mask = cv2.bitwise_or(combined_mask, binary_mask)

                    # Extract Contour for UI
                    contours, _ = cv2.findContours(binary_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contour_points = []
                    if contours:
                        main_contour = max(contours, key=cv2.contourArea)
                        epsilon = 0.005 * cv2.arcLength(main_contour, True)
                        approx = cv2.approxPolyDP(main_contour, epsilon, True)
                        for pt in approx:
                            contour_points.extend([int(pt[0][0]), int(pt[0][1])])

                    # Calculate true 3D centroid
                    centroid_3d = self.calculate_3d_centroid(cv_depth, binary_mask, step=4)
                    
                    if centroid_3d:
                        cx, cy, cz = centroid_3d
                        yaw, pitch = self.calculate_angle_from_3d(cx, cy, cz)
                        z_val = cz
                        valid_status = "Valid 3D"
                        
                        # Store debug point
                        if self.color_info:
                             fx = self.color_info.k[0]
                             fy = self.color_info.k[4]
                             cx_p = self.color_info.k[2]
                             cy_p = self.color_info.k[5]
                             
                             u_c = int((cx * fx / cz) + cx_p)
                             v_c = int((cy * fy / cz) + cy_p)
                             debug_points.append({'u': u_c, 'v': v_c, 'z': z_val, 'label': f"{z_val:.2f}m"})
                    else:
                        x1, y1, x2, y2 = boxes[i][0:4]
                        center_x = (x1 + x2) / 2
                        center_y = (y1 + y2) / 2
                        if self.color_info:
                             fx = self.color_info.k[0]
                             cx_p = self.color_info.k[2]
                             yaw = np.arctan((center_x - cx_p) / fx)
                             pitch = 0.0 
                        else:
                             yaw, pitch = 0.0, 0.0
                        z_val = 0.0
                        valid_status = "No Depth"

                    obj_info = ObjectInfo()
                    obj_info.class_name = class_name
                    obj_info.score = score
                    obj_info.x = float(yaw)
                    obj_info.y = float(pitch)
                    obj_info.z = float(z_val)
                    obj_info.contour_points = contour_points
                    
                    object_array_msg.objects.append(obj_info)
                    
                    if response: 
                        self.get_logger().info(f"Target '{class_name}': Yaw={yaw:.3f}, Pitch={pitch:.3f}, Depth={z_val:.3f}m ({valid_status})")

            self.objects_pub.publish(object_array_msg)
            
            if detected_count > 0:
                pc2_msg = self.generate_pointcloud_v2(cv_depth, cv_image, combined_mask)
                if pc2_msg:
                    self.result_cloud_pub.publish(pc2_msg)
            
            if detected_count > 0:
                masked_img_msg = self.bridge.cv2_to_imgmsg(combined_mask * 255, encoding='mono8')
                masked_img_msg.header = self.latest_header
                self.mask_pub.publish(masked_img_msg)
                
                res_plotted = results[0].plot()
                
                # Draw Debug Points on Output Image
                for pt in debug_points:
                    u, v = pt['u'], pt['v']
                    # Draw Circle
                    cv2.circle(res_plotted, (u, v), 5, (0, 0, 255), -1)
                    # Draw Text
                    cv2.putText(res_plotted, pt['label'], (u + 10, v), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                debug_msg = self.bridge.cv2_to_imgmsg(res_plotted, encoding='bgr8')
                debug_msg.header = self.latest_header
                self.debug_pub.publish(debug_msg)
                
                if response:
                    response.success = True
                    response.message = f"Detected {detected_count} target objects."
            else:
                if response:
                    response.success = True
                    response.message = "No target objects detected."
                
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
