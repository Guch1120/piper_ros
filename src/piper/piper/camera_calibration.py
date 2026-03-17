#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState, Image, CameraInfo
from cv_bridge import CvBridge
import cv2
import numpy as np
import time
import threading
import math
from tf2_ros import Buffer, TransformListener
from geometry_msgs.msg import TransformStamped, PointStamped
import tf2_geometry_msgs

class CameraCalibrationNode(Node):
    def __init__(self):
        super().__init__('camera_calibration_node')
        
        # Publishers
        self.joint_pub = self.create_publisher(JointState, 'joint_ctrl_single', 1)
        
        # Subscribers
        self.image_sub = self.create_subscription(
            Image, 
            '/camera/camera/color/image_raw', 
            self.image_callback, 
            1
        )
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            '/camera/camera/color/camera_info',
            self.camera_info_callback,
            1
        )
        self.joint_state_sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            1
        )
        self.depth_sub = self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_callback,
            1
        )
        
        # TF
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # Tools
        self.bridge = CvBridge()
        
        self.camera_info = None
        self.current_joint_positions = [0.0] * 7 # [j1, j2, j3, j4, j5, j6, gripper]
        self.current_depth = None
        self.tracking_started = False
        self.feature_points = []
        self.tracks = [] # List of list of points
        self.calibrating = False
        self.prev_gray = None
        
        # Calibration Parameters
        self.start_angle = -1.5
        self.end_angle = 1.5
        self.duration = 5.0 # seconds
        self.steps = 100
        
        self.timer = self.create_timer(1.0, self.start_calibration_thread)
        self.calibration_thread = None

    def start_calibration_thread(self):
        self.timer.cancel() # Run once
        self.calibration_thread = threading.Thread(target=self.calibration_logic)
        self.calibration_thread.start()

    def camera_info_callback(self, msg):
        self.camera_info = msg
        
    def depth_callback(self, msg):
        try:
             # Use cv_bridge for depth (16UC1 -> Mono16 -> uint16 numpy)
             self.current_depth = self.bridge.imgmsg_to_cv2(msg, "16UC1")
        except Exception as e:
             # self.get_logger().error(f"Depth callback error: {e}") # Reduce log spam
             pass

    def joint_state_callback(self, msg):
        # Map joint names to positions
        # Expected names: joint1 ... joint6, joint7 (gripper)
        pos_map = {}
        for i, name in enumerate(msg.name):
            pos_map[name] = msg.position[i]
            
        new_pos = list(self.current_joint_positions)
        # Update if name exists, otherwise keep
        if 'joint1' in pos_map: new_pos[0] = pos_map['joint1']
        if 'joint2' in pos_map: new_pos[1] = pos_map['joint2']
        if 'joint3' in pos_map: new_pos[2] = pos_map['joint3']
        if 'joint4' in pos_map: new_pos[3] = pos_map['joint4']
        if 'joint5' in pos_map: new_pos[4] = pos_map['joint5']
        if 'joint6' in pos_map: new_pos[5] = pos_map['joint6']
        if 'joint7' in pos_map: new_pos[6] = pos_map['joint7']
        
        self.current_joint_positions = new_pos

    def image_callback(self, msg):
        try:
            self.current_image = self.bridge.imgmsg_to_cv2(msg, "bgr8")
            
            if self.tracking_started and self.current_image is not None:
                self.track_features()
                
        except Exception as e:
            self.get_logger().error(f"Image callback error: {e}")

    def track_features(self):
        if self.current_image is None: return

        gray = cv2.cvtColor(self.current_image, cv2.COLOR_BGR2GRAY)
        
        if len(self.feature_points) == 0:
            # Detect new features
            p0 = cv2.goodFeaturesToTrack(gray, mask=None, **dict(maxCorners=100, qualityLevel=0.3, minDistance=7, blockSize=7))
            
            if p0 is not None:
                self.feature_points = p0.reshape(-1, 2)
                self.prev_gray = gray.copy()
                self.tracks = []
                for pt in self.feature_points:
                    self.tracks.append([pt])
        else:
            # Track existing features
            if self.prev_gray is None:
                self.prev_gray = gray.copy()
                return

            p0 = self.feature_points.reshape(-1, 1, 2).astype(np.float32)
            p1, st, err = cv2.calcOpticalFlowPyrLK(self.prev_gray, gray, p0, None, **dict(winSize=(15, 15), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)))
            
            # Select good points
            if p1 is not None and st is not None:
                good_new = p1[st == 1]
                good_old = p0[st == 1]
                
                # Update tracks
                new_tracks = []
                new_features = []
                
                idx = 0
                for i, status in enumerate(st):
                    if status == 1:
                        pt = p1[i].reshape(2)
                        self.tracks[i].append(pt)
                        new_tracks.append(self.tracks[i])
                        new_features.append(pt)
                
                self.tracks = new_tracks
                self.feature_points = np.array(new_features)
                self.prev_gray = gray.copy()
            else:
                self.feature_points = []
                self.tracks = []

    def move_joint(self, angle, base_pose, duration=0.1):
        msg = JointState()
        msg.name = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6', 'joint7']
        # Use base_pose as foundation, override joint6
        target_pos = list(base_pose)
        target_pos[5] = angle # Override joint6
        
        msg.position = target_pos
        msg.velocity = [0.0] * 7 
        msg.effort = [0.0] * 7 
        self.joint_pub.publish(msg)
        time.sleep(duration)

    def calibration_logic(self):
        self.get_logger().info("Starting Calibration Sequence...")
        time.sleep(2.0)
        
        while self.camera_info is None and rclpy.ok():
             self.get_logger().info("Waiting for Camera Info...")
             time.sleep(1.0)
        
        # Capture current pose as base
        base_pose = list(self.current_joint_positions)
        self.get_logger().info(f"Captured base pose: {base_pose}")
        
        # 1. Move to Start Position
        self.get_logger().info(f"Moving to start angle: {self.start_angle}")
        steps = 50
        current_j6 = base_pose[5]
        
        for i in range(steps):
             j6_target = current_j6 + (self.start_angle - current_j6) * (i / steps)
             self.move_joint(j6_target, base_pose, 0.05)
        self.move_joint(self.start_angle, base_pose, 1.0) # Hold
        
        # 2. Start Tracking
        self.get_logger().info("Starting feature tracking...")
        self.tracks = []
        self.feature_points = []
        self.tracking_started = True
        
        # Wait a bit to get features
        time.sleep(0.5)
        
        # 3. Rotate to End Angle
        self.get_logger().info(f"Rotating to end angle: {self.end_angle}")
        for i in range(self.steps):
            angle = self.start_angle + (self.end_angle - self.start_angle) * (i / self.steps)
            self.move_joint(angle, base_pose, self.duration / self.steps)
        
        # 4. Stop Tracking
        self.tracking_started = False
        self.get_logger().info("Motion complete. Processing data...")
        
        # 5. Calculate Center of Rotation
        observed_center = self.calculate_cor(self.tracks)
        
        if observed_center is None:
             self.get_logger().error("Failed to calculate Center of Rotation (Not enough tracks or bad fit)")
        else:
             self.get_logger().info(f"Observed CoR: {observed_center}")

            # --- Depth-Based Offset Calculation ---
             if self.current_depth is not None and self.camera_info is not None:
                try:
                    # Get average depth at the center of rotation (or nearby features)
                    # Ideally, depth of the wall/plane where features are tracked.
                    # As an approximation, use the center of the image or the observed center if within bounds.
                    u_c, v_c = observed_center
                    
                    # Check if observed center is within image bounds
                    h, w = self.current_depth.shape
                    u_int, v_int = int(u_c), int(v_c)
                    
                    depth_z = 0.0
                    
                    # If center is outside, use image center depth (assuming flat wall)
                    if 0 <= u_int < w and 0 <= v_int < h:
                        depth_z = self.current_depth[v_int, u_int] * 0.001 # mm to m
                    else:
                        # Use center of image
                        depth_z = self.current_depth[h//2, w//2] * 0.001
                        
                    if depth_z > 0.1:
                        if self.camera_info.k[0] == 0: # Check if K is valid
                            fx = 615.0
                            fy = 615.0
                            cx = 320.0
                            cy = 240.0
                        else:
                            fx = self.camera_info.k[0]
                            fy = self.camera_info.k[4]
                            cx = self.camera_info.k[2]
                            cy = self.camera_info.k[5]
                        
                        # Calculate physical offset
                        # u = (Tx * fx) / Z + cx  => Tx = (u - cx) * Z / fx
                        x_offset = (u_c - cx) * depth_z / fx
                        y_offset = (v_c - cy) * depth_z / fy
                        
                        self.get_logger().info(f"--- Physical Offset Measurement ---")
                        self.get_logger().info(f"Depth (Z): {depth_z:.3f} m")
                        self.get_logger().info(f"Calculated X Offset: {x_offset:.4f} m ({x_offset*100:.1f} cm)")
                        self.get_logger().info(f"Calculated Y Offset: {y_offset:.4f} m ({y_offset*100:.1f} cm)")
                        self.get_logger().info(f"-----------------------------------")
                    else:
                        self.get_logger().warn("Invalid depth reading (0 or too close).")
                except Exception as e:
                    self.get_logger().error(f"Error calculating physical offset: {e}")
             else:
                 self.get_logger().warn("Depth image or Camera Info not available. Skipping physical offset calc.")
        
        # 6. Get Expected CoR from TF
        expected_center = self.get_expected_cor()
        self.get_logger().info(f"Expected CoR: {expected_center}")
        
        # 7. Compare and Visualize
        if observed_center is not None and expected_center is not None:
             diff = observed_center - expected_center
             self.get_logger().info(f"Difference (Obs - Exp): {diff}")
             dist = np.linalg.norm(diff)
             self.get_logger().info(f"Distance in pixels: {dist:.2f}")

        # Always save image to show what happened
        if observed_center is None:
             # Just verify tracking visually
             if len(self.tracks) > 0 and len(self.tracks[0]) > 0:
                  pts = np.array(self.tracks[0])[-1] # End point of first track
                  observed_center = pts # Mock for vis if failed
             else:
                  observed_center = np.array([0.0, 0.0])

        self.save_result_image(observed_center, expected_center)
        
        # 8. Reset Arm
        self.get_logger().info("Resetting arm to base pose...")
        for i in range(steps):
             current = self.end_angle + (current_j6 - self.end_angle) * (i / steps)
             self.move_joint(current, base_pose, 0.05)
        self.move_joint(current_j6, base_pose, 1.0)
        
        self.get_logger().info("Calibration Node Finished.")
        # Optional: Ask user or just exit
        # rclpy.shutdown() within a spinning node might be tricky if not main thread?
        # Use simple flag or just log.
    
    def calculate_cor(self, tracks):
        centers = []
        valid_tracks = 0
        if len(tracks) < 5:
            self.get_logger().warn(f"Not enough tracks: {len(tracks)}")
            return None
            
        for track in tracks:
            # Need at least 3 points for circle, but more is better for reliable arc
            if len(track) < 10: continue
            pts = np.array(track)
            
            # Check displacement
            disp = np.linalg.norm(pts[-1] - pts[0])
            if disp < 5.0: continue # Didn't move enough
            
            # Circle fitting (Taubin or Kasa method approx)
            # Simple Kasa method: Minimize sum((x-xc)^2 + (y-yc)^2 - R^2)^2
            # Linear form: 2x*xc + 2y*yc + (R^2 - xc^2 - yc^2) = x^2 + y^2
            # A_i = [2x_i, 2y_i, 1]
            # X = [xc, yc, A]
            # B_i = x_i^2 + y_i^2
            
            try:
                A = np.c_[2*pts[:,0], 2*pts[:,1], np.ones(len(pts))]
                b = pts[:,0]**2 + pts[:,1]**2
                x, res, rank, s = np.linalg.lstsq(A, b, rcond=None)
                xc, yc = x[0], x[1]
                centers.append([xc, yc])
                valid_tracks += 1
            except:
                pass
        
        if len(centers) < 3:
            self.get_logger().warn(f"Not enough valid arc fits: {len(centers)}")
            return None
            
        centers = np.array(centers)
        
        # Remove outliers?
        # Median is robust
        mean_center = np.median(centers, axis=0)
        
        # Log spread
        std_dev = np.std(centers, axis=0)
        self.get_logger().info(f"CoR Std Dev: {std_dev}")
        
        if np.linalg.norm(std_dev) > 50:
             self.get_logger().warn("CoR estimation is very noisy!")
        
        return mean_center

    def get_expected_cor(self):
        try:
            # We assume Joint 6 axis passes through origin of 'link6' frame and points along Z.
            # We want to find the projection of this point (or the axis) on the image.
            # Since the camera is fixed relative to link6, the position of the axis IS constant.
            # Assuming 'link6' frame origin is ON the rotation axis.
            
            # Wait for transform availability
            # Since TF is static (camera fixed on link6), lookup should work if description is published.
            if not self.tf_buffer.can_transform('camera_color_optical_frame', 'link6', rclpy.time.Time()):
                 self.get_logger().warn("Cannot transform link6 to camera frame")
                 return None

            # Look up transform
            t = self.tf_buffer.lookup_transform(
                'camera_color_optical_frame',
                'link6',
                rclpy.time.Time()
            )
            
            # Point in camera frame (Link 6 Origin)
            p_cam_x = t.transform.translation.x
            p_cam_y = t.transform.translation.y
            p_cam_z = t.transform.translation.z
            
            # Project using Camera Info (K matrix)
            # K = [fx, 0, cx, 0, fy, cy, 0, 0, 1]
            if self.camera_info is None:
                # Fallback to D435i approx if timeout/fail
                fx = 615.0
                fy = 615.0
                cx = 320.0
                cy = 240.0
            else:
                k = self.camera_info.k
                fx = k[0]
                fy = k[4]
                cx = k[2]
                cy = k[5]
            
            # Project (pinhole model)
            # u = fx * (x/z) + cx
            # v = fy * (y/z) + cy
            
            if abs(p_cam_z) < 0.001:
                 # Singular (point is at camera center or plane)
                 return None
                 
            u = (fx * p_cam_x) / p_cam_z + cx
            v = (fy * p_cam_y) / p_cam_z + cy
            
            return np.array([u, v])
            
        except Exception as e:
            self.get_logger().error(f"TF Error: {e}")
            return None

    def save_result_image(self, observed, expected):
        if self.current_image is None: return
        
        img = self.current_image.copy()
        h, w = img.shape[:2]
        center = (w//2, h//2)
        
        # Draw Observed (Green)
        if observed is not None:
             obs_pt = (int(observed[0]), int(observed[1]))
             cv2.drawMarker(img, obs_pt, (0, 255, 0), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
             cv2.putText(img, "Observed", (obs_pt[0]+10, obs_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Draw Expected (Blue)
        if expected is not None:
            exp_pt = (int(expected[0]), int(expected[1]))
            cv2.drawMarker(img, exp_pt, (255, 0, 0), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
            cv2.putText(img, "Expected (TF)", (exp_pt[0]+10, exp_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        
        # Draw Image Center (Red)
        cv2.drawMarker(img, center, (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
        cv2.putText(img, "Image Center", (center[0]+10, center[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        
        # Draw tracks (Yellow)
        # for track in self.tracks:
        #      if len(track) > 1:
        #           pts = np.array(track, dtype=np.int32)
        #           cv2.polylines(img, [pts], False, (0, 255, 255), 1)

        cv2.imwrite("calibration_result.png", img)
        self.get_logger().info(f"Saved calibration_result.png to {self.get_name()}") # Log path info? current dir.

def main(args=None):
    rclpy.init(args=args)
    node = CameraCalibrationNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
