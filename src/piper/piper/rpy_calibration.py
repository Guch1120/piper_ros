#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge
import cv2
import numpy as np
import tf2_ros
from tf2_geometry_msgs import TransformStamped
import math
from rclpy.time import Time
from scipy.spatial.transform import Rotation as R

class RPYCalibrationNode(Node):
    def __init__(self):
        super().__init__('rpy_calibration_node')
        
        # Tools
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        
        # State
        self.camera_info = None
        self.camera_matrix = None
        self.dist_coeffs = None
        self.quat_history = []
        self.history_length = 30 # Number of frames to average
        
        # ArUco Setup
        # Using DICT_6X6_250 as generated
        try:
             # OpenCV 4.7+
             self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
             self.aruco_params = cv2.aruco.DetectorParameters()
             self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)
        except AttributeError:
             # OpenCV < 4.7
             self.aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_6X6_250)
             self.aruco_params = cv2.aruco.DetectorParameters_create()
             self.detector = None

        # Marker size in meters (Assumed 10cm, change if printed differently)
        self.marker_length = 0.10 
        
        # Subscribers
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            '/camera/camera/color/camera_info',
            self.camera_info_callback,
            1
        )
        
        self.image_sub = self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.image_callback,
            1
        )
        
        self.get_logger().info("RPY Calibration Node Started.")
        self.get_logger().info(f"Looking for ArUco Marker ID:0, Assumed Size: {self.marker_length*100}cm")
        self.get_logger().info("Place the marker flat on the floor (horizontal plane).")

    def camera_info_callback(self, msg):
        self.camera_info = msg
        self.camera_matrix = np.array(msg.k).reshape((3, 3))
        self.dist_coeffs = np.array(msg.d)

    def image_callback(self, msg):
        if self.camera_matrix is None:
            return
            
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, "bgr8")
            
            # Detect ArUco
            if self.detector is not None:
                corners, ids, rejected = self.detector.detectMarkers(cv_image)
            else:
                corners, ids, rejected = cv2.aruco.detectMarkers(cv_image, self.aruco_dict, parameters=self.aruco_params)
            
            if ids is not None and 0 in ids:
                self.process_marker(corners, ids, cv_image)
            else:
                # Optionally show image without marker
                cv2.imshow("RPY Calibration", cv_image)
                cv2.waitKey(1)
                
        except Exception as e:
            self.get_logger().error(f"Image processing error: {e}")

    def process_marker(self, corners, ids, cv_image):
        # Find index for ID 0
        idx = np.where(ids == 0)[0][0]
        marker_corners = corners[idx]
        
        # 1. Calculate Camera to Marker Pose (solvePnP)
        # Marker definition: 3D points in marker coordinate system (Z=0)
        obj_points = np.array([
            [-self.marker_length/2,  self.marker_length/2, 0],
            [ self.marker_length/2,  self.marker_length/2, 0],
            [ self.marker_length/2, -self.marker_length/2, 0],
            [-self.marker_length/2, -self.marker_length/2, 0]
        ], dtype=np.float32)
        
        success, rvec, tvec = cv2.solvePnP(
            obj_points, marker_corners, self.camera_matrix, self.dist_coeffs, flags=cv2.SOLVEPNP_IPPE_SQUARE
        )
        
        if not success:
            return
            
        # Draw axes
        cv2.drawFrameAxes(cv_image, self.camera_matrix, self.dist_coeffs, rvec, tvec, self.marker_length)
        cv2.imshow("RPY Calibration", cv_image)
        cv2.waitKey(1)
        
        # 2. Get Robot Pose (base_link -> link6)
        try:
            # We want the rotation of link6 in the base frame
            tf_link6 = self.tf_buffer.lookup_transform(
                'base_link', # Target frame (assuming this is aligned with gravity Z-up)
                'link6',     # Source frame
                rclpy.time.Time()
            )
        except Exception as e:
            self.get_logger().warn(f"Waiting for TF info... {e}")
            return
            
        # 3. Math for Mounting angles
        # Rotation matrices
        # rvec from solvePnP maps MarkerFrame -> OpticalCameraFrame
        # T_cam_marker
        R_cam_marker, _ = cv2.Rodrigues(rvec)
        
        # TF gives T_base_link6
        q = tf_link6.transform.rotation
        R_base_link6 = R.from_quat([q.x, q.y, q.z, q.w]).as_matrix()
        
        # We assume the marker is flat on the floor. 
        # So MarkerFrame Z-axis is parallel to base_link Z-axis (Gravity).
        # Depending on how the marker is rotated on the floor, X and Y might differ, 
        # but the Z axis direction is the absolute reference for Pitch/Roll.
        
        # Let's find the orientation of the camera relative to link6.
        # Ideally, T_link6_cam is what we put in URDF.
        # We observed T_cam_marker. 
        # Marker Z vector in Camera Frame:
        z_marker_in_cam = R_cam_marker[:, 2] 
        
        # We know Marker Z is vertical in world (base_link).
        # Base Z vector [0,0,1] in base_link.
        # Let's represent this Base Z (Up) vector in the Link6 frame:
        # R_base_link6 * v_link6 = v_base  => v_link6 = R_link6_base * v_base
        z_base_in_link6 = R_base_link6.T @ np.array([0, 0, 1])
        
        # Now we have two vectors that physically represent the "Up" or "Gravity" direction:
        # 1. z_marker_in_cam: The UP direction seen by the camera (assuming marker is flat)
        # 2. z_base_in_link6: The UP direction relative to link6 (from TF)
        
        # The URDF RPY defines R_link6_cam.
        # R_link6_cam * v_cam = v_link6
        # Therefore, R_link6_cam * z_marker_in_cam = z_base_in_link6
        
        # This gives us alignment for Pitch and Roll. 
        # Yaw is undetermined just from Z, because the marker could be spun around on the floor.
        # IF we assume the user aligns the marker perfectly with the robot's X axis, we can find Yaw.
        # Let's assume the user put the marker so its X axis faces the same way as robot X axis.
        x_base_in_link6 = R_base_link6.T @ np.array([1, 0, 0])
        x_marker_in_cam = R_cam_marker[:, 0]
        
        # We want R_link6_cam such that:
        # R_link6_cam * z_marker_in_cam = z_base_in_link6
        # R_link6_cam * x_marker_in_cam = x_base_in_link6
        
        y_base_in_link6 = R_base_link6.T @ np.array([0, 1, 0])
        y_marker_in_cam = R_cam_marker[:, 1]
        
        V_cam = np.column_stack((x_marker_in_cam, y_marker_in_cam, z_marker_in_cam))
        V_link6 = np.column_stack((x_base_in_link6, y_base_in_link6, z_base_in_link6))
        
        # R_link6_optical = V_link6 * V_cam^-1
        # This is the rotation from link6 to camera_color_optical_frame
        R_link6_optical = V_link6 @ np.linalg.inv(V_cam)
        
        # --- Pattern D: The "Live TF Tree" approach (Bulletproof) ---
        # Instead of guessing what the Realsense URDF macro does internally, we can simply ask the live TF tree!
        # The user has some URDF currently running (which they set manually, e.g., 3.14 -1.6 3.14).
        # We can look up:
        # 1. The EXACT current transform from link6 to camera_link
        # 2. The EXACT current transform from camera_link to camera_color_optical_frame
        
        try:
            # 1. Current URDF definition (link6 -> camera_link)
            tf_urdf = self.tf_buffer.lookup_transform(
                'link6',
                'camera_link',
                rclpy.time.Time()
            )
            
            # 2. Internal macro definition (camera_link -> camera_color_optical_frame)
            tf_macro = self.tf_buffer.lookup_transform(
                'camera_link',
                'camera_color_optical_frame',
                rclpy.time.Time()
            )
            
            # Convert these to rotation matrices
            q_urdf = tf_urdf.transform.rotation
            R_urdf = R.from_quat([q_urdf.x, q_urdf.y, q_urdf.z, q_urdf.w]).as_matrix()
            
            q_macro = tf_macro.transform.rotation
            R_macro = R.from_quat([q_macro.x, q_macro.y, q_macro.z, q_macro.w]).as_matrix()
            
            # We measured R_link6_optical (from marker).
            # We want to find the NEW R_urdf (let's call it R_urdf_new) such that:
            # R_urdf_new * R_macro = R_link6_optical
            # Therefore: R_urdf_new = R_link6_optical * (R_macro)^-1
            R_urdf_new = avg_R_opt.as_matrix() @ np.linalg.inv(R_macro)
            
            # Now we extract the RPY for this new URDF rotation
            # Using standard URDF fixed-axes xyz (extrinsic)
            new_rpy_urdf = R.from_matrix(R_urdf_new).as_euler('xyz')
            
            # To prevent huge jumps due to euler aliasing, let's find the equivalent 
            # angles closest to the CURRENT URDF angles.
            current_rpy = R.from_matrix(R_urdf).as_euler('xyz')
            
            def euler_distance(a, b):
                return sum((min(abs(a[i] - b[i]), 2*math.pi - abs(a[i] - b[i])))**2 for i in range(3))
                
            best_rpy = new_rpy_urdf
            min_dist = float('inf')
            
            # Test shifts to find the closest visual representation
            for rx in [-2*math.pi, -math.pi, 0, math.pi, 2*math.pi]:
                for ry in [-2*math.pi, -math.pi, 0, math.pi, 2*math.pi]:
                    for rz in [-2*math.pi, -math.pi, 0, math.pi, 2*math.pi]:
                        shift = new_rpy_urdf + np.array([rx, ry, rz])
                        # Verify the shifted euler produces the exact same rotation matrix
                        test_R = R.from_euler('xyz', shift).as_matrix()
                        diff_trace = np.trace(R_urdf_new.T @ test_R)
                        if diff_trace > 2.999: # matrices are practically identical
                            dist = euler_distance(shift, current_rpy)
                            if dist < min_dist:
                                min_dist = dist
                                best_rpy = shift

            self.get_logger().info("\n[Live TF Extracted Correction]")
            self.get_logger().info(f"Current URDF value: xyz=\"...\" rpy=\"{current_rpy[0]:.4f} {current_rpy[1]:.4f} {current_rpy[2]:.4f}\"")
            self.get_logger().info(f"Corrected URDF value: xyz=\"...\" rpy=\"{best_rpy[0]:.4f} {best_rpy[1]:.4f} {best_rpy[2]:.4f}\"")
            self.get_logger().info("Please copy the EXACT Corrected URDF value above into piper_macro.xacro!")
            self.get_logger().info("-----------------------")

        except Exception as e:
            self.get_logger().warn(f"Waiting for full TF tree to compute exact URDF offset... {e}")
            pass

def main(args=None):
    rclpy.init(args=args)
    node = RPYCalibrationNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
