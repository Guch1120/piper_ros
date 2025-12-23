import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import String
from geometry_msgs.msg import TransformStamped
from cv_bridge import CvBridge
import cv2
import numpy as np
import torch
import message_filters
import tf2_ros
from image_geometry import PinholeCameraModel
from sam3_ros.sam3_online_tracker import Sam3OnlineTracker
from sam3_interfaces.srv import Sam3StartTracking, Sam3StopTracking

class Sam3Node(Node):
    def __init__(self):
        super().__init__('sam3_node')
        self.declare_parameter('model_path', '')
        self.declare_parameter('device', 'auto')
        
        model_path = self.get_parameter('model_path').get_parameter_value().string_value
        device_param = self.get_parameter('device').get_parameter_value().string_value
        
        if device_param == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            device = device_param
        
        if not model_path:
            model_path = None # Use default download
            
        self.get_logger().info(f"Initializing SAM3 Tracker on {device}...")
        try:
            self.tracker = Sam3OnlineTracker(checkpoint_path=model_path, device=device)
            self.get_logger().info("SAM3 Tracker initialized.")
        except Exception as e:
            self.get_logger().error(f"Failed to initialize SAM3 Tracker: {e}")
            raise e
        
        self.bridge = CvBridge()
        self.camera_model = PinholeCameraModel()
        self.camera_info_received = False
        
        # Subscribers
        self.image_sub = message_filters.Subscriber(self, Image, '/camera/color/image_raw')
        self.depth_sub = message_filters.Subscriber(self, Image, '/camera/aligned_depth_to_color/image_raw')
        
        self.info_sub = self.create_subscription(
            CameraInfo,
            '/camera/color/camera_info',
            self.info_callback,
            1
        )
        
        self.prompt_sub = self.create_subscription(
            String,
            '/sam3/prompt',
            self.prompt_callback,
            1
        )
        
        # Services
        self.start_srv = self.create_service(Sam3StartTracking, '/sam3/start_tracking', self.start_tracking_callback)
        self.stop_srv = self.create_service(Sam3StopTracking, '/sam3/stop_tracking', self.stop_tracking_callback)
        
        # Synchronizer
        self.ts = message_filters.ApproximateTimeSynchronizer(
            [self.image_sub, self.depth_sub],
            queue_size=10,
            slop=0.1
        )
        self.ts.registerCallback(self.image_depth_callback)
        
        # Publishers
        self.mask_pub = self.create_publisher(Image, '/sam3/mask', 1)
        self.overlay_pub = self.create_publisher(Image, '/sam3/overlay', 1)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        
        self.tracking_active = False
        self.current_prompt = None
        self.latest_cv_image = None # Store latest image for service-based init

    def info_callback(self, msg):
        if not self.camera_info_received:
            self.camera_model.fromCameraInfo(msg)
            self.camera_info_received = True
            self.get_logger().info("Camera info received.")

    def prompt_callback(self, msg):
        self.current_prompt = msg.data
        self.tracking_active = False # Reset tracking to re-init on next frame
        self.get_logger().info(f"Received prompt: {self.current_prompt}")

    def start_tracking_callback(self, request, response):
        prompt = request.prompt
        self.get_logger().info(f"Service: Start tracking request with prompt: {prompt}")
        
        if self.latest_cv_image is None:
            response.success = False
            response.message = "No image received yet. Cannot start tracking."
            self.get_logger().warn(response.message)
            return response
            
        try:
            self.current_prompt = prompt
            self.get_logger().info("Service: Initializing tracker...")
            masks = self.tracker.init_track(self.latest_cv_image, self.current_prompt)
            self.tracking_active = True
            response.success = True
            response.message = f"Tracking started for prompt: {prompt}"
            self.get_logger().info(response.message)
        except Exception as e:
            response.success = False
            response.message = f"Failed to start tracking: {e}"
            self.get_logger().error(response.message)
            self.tracking_active = False
            
        return response

    def stop_tracking_callback(self, request, response):
        self.tracking_active = False
        self.current_prompt = None
        response.success = True
        response.message = "Tracking stopped."
        self.get_logger().info("Service: Tracking stopped.")
        return response

    def image_depth_callback(self, rgb_msg, depth_msg):
        if not self.camera_info_received:
            self.get_logger().warn("Waiting for camera info...", throttle_duration_sec=5)
            return

        try:
            cv_image = self.bridge.imgmsg_to_cv2(rgb_msg, desired_encoding='rgb8')
            cv_depth = self.bridge.imgmsg_to_cv2(depth_msg, desired_encoding='passthrough')
            self.latest_cv_image = cv_image # Store for service use
        except Exception as e:
            self.get_logger().error(f"cv_bridge error: {e}")
            return
            
        # Topic-based trigger (legacy support)
        # If current_prompt is set but tracking is not active, it means it was set via topic
        # and we should initialize here if not already done by service.
        # However, if service set it, tracking_active is already True.
        # So we only need to handle the case where tracking_active is False but current_prompt is set.
        
        try:
            if self.current_prompt and not self.tracking_active:
                self.get_logger().info("Topic: Starting tracking...")
                masks = self.tracker.init_track(cv_image, self.current_prompt)
                self.tracking_active = True
            elif self.tracking_active:
                masks = self.tracker.step(cv_image)
            else:
                return # Nothing to do

            if masks:
                # Publish first mask for now
                mask = masks[0]
                mask_msg = self.bridge.cv2_to_imgmsg(mask, encoding='mono8')
                mask_msg.header = rgb_msg.header
                self.mask_pub.publish(mask_msg)
                
                # Create overlay
                overlay = cv_image.copy()
                mask_bool = mask > 0
                
                # Create a colored mask (green)
                green_mask = np.zeros_like(overlay)
                green_mask[mask_bool] = [0, 255, 0]
                
                # Blend
                alpha = 0.5
                # Use numpy for blending to avoid cv2.addWeighted issues with slices
                roi = overlay[mask_bool].astype(np.float32)
                green = green_mask[mask_bool].astype(np.float32)
                blended = (roi * (1 - alpha) + green * alpha).astype(np.uint8)
                overlay[mask_bool] = blended
                
                overlay_msg = self.bridge.cv2_to_imgmsg(overlay, encoding='rgb8')
                overlay_msg.header = rgb_msg.header
                self.overlay_pub.publish(overlay_msg)
                
                # 3D Position Estimation
                self.publish_tf(mask_bool, cv_depth, rgb_msg.header)
                
        except Exception as e:
            self.get_logger().error(f"Error during tracking step: {e}")
            # Reset tracking on error
            self.tracking_active = False

    def publish_tf(self, mask_bool, cv_depth, header):
        # Extract depth values within the mask
        depth_values = cv_depth[mask_bool]
        
        # Filter out invalid depth (0 or NaN)
        valid_depths = depth_values[depth_values > 0]
        valid_depths = valid_depths[~np.isnan(valid_depths)]
        
        if len(valid_depths) == 0:
            return
            
        # Compute median depth (in millimeters usually, convert to meters if needed)
        # Realsense usually provides depth in millimeters (uint16)
        median_depth_mm = np.median(valid_depths)
        median_depth_m = median_depth_mm / 1000.0
        
        # Compute centroid of the mask
        ys, xs = np.where(mask_bool)
        u = np.mean(xs)
        v = np.mean(ys)
        
        # Deproject to 3D
        # projectPixelTo3dRay returns a unit vector (x, y, z) where z=1
        ray = self.camera_model.projectPixelTo3dRay((u, v))
        
        # Scale ray by depth
        # ray is (x/z, y/z, 1)
        # We want (X, Y, Z) where Z = depth
        x = ray[0] * median_depth_m
        y = ray[1] * median_depth_m
        z = ray[2] * median_depth_m
        
        # Broadcast TF
        t = TransformStamped()
        t.header.stamp = header.stamp
        t.header.frame_id = header.frame_id
        t.child_frame_id = "sam3_target"
        
        t.transform.translation.x = x
        t.transform.translation.y = y
        t.transform.translation.z = z
        
        t.transform.rotation.x = 0.0
        t.transform.rotation.y = 0.0
        t.transform.rotation.z = 0.0
        t.transform.rotation.w = 1.0
        
        self.tf_broadcaster.sendTransform(t)

def main(args=None):
    rclpy.init(args=args)
    node = Sam3Node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
