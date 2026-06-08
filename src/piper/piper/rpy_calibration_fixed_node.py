#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Estimate the URDF fixed-joint rotation for an eye-in-hand RealSense camera.

Use case:
  - RealSense D435i is mounted on the arm/gripper.
  - An ArUco marker is placed flat on the floor/table.
  - Move the hand camera roughly perpendicular to the marker.
  - Run this node and copy the reported rpy into the URDF origin of the
    xacro:sensor_d435i fixed joint.

Default behavior is `normal_only` calibration:
  - It uses only the marker plane normal.
  - This corrects pitch/roll tilt, which is usually what produces Z-height
    errors from depth.
  - Marker yaw on the floor does not need to be known.

Important:
  - This node does NOT automatically edit the URDF.
  - Copy "Corrected URDF rotation (wrapped)" manually into:
      <xacro:sensor_d435i ...>
        <origin xyz="..." rpy="COPY_HERE"/>
      </xacro:sensor_d435i>
"""

import math
from typing import List, Optional

import cv2
import numpy as np
import rclpy
import tf2_ros
from cv_bridge import CvBridge
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from scipy.spatial.transform import Rotation as R
from sensor_msgs.msg import CameraInfo, Image


class RPYCalibrationNode(Node):
    def __init__(self):
        super().__init__('rpy_calibration_node')

        # ----------------------------
        # Parameters
        # ----------------------------
        self.declare_parameter('image_topic', '/camera/camera/color/image_raw')
        self.declare_parameter('camera_info_topic', '/camera/camera/color/camera_info')

        self.declare_parameter('base_frame', 'base_link')

        # In the current URDF, the RealSense macro is attached to gripper_base.
        self.declare_parameter('parent_frame', 'gripper_base')
        self.declare_parameter('camera_link_frame', 'camera_link')
        self.declare_parameter('optical_frame', 'camera_color_optical_frame')

        self.declare_parameter('marker_id', 0)
        self.declare_parameter('marker_length', 0.10)  # [m]
        self.declare_parameter('aruco_dictionary', 'DICT_6X6_250')

        # normal_only:
        #   Correct pitch/roll from the floor/table normal.
        # full_marker:
        #   Estimate full orientation; marker yaw must be known.
        self.declare_parameter('calibration_mode', 'normal_only')
        self.declare_parameter('marker_yaw_deg', 0.0)

        # +1:
        #   marker +Z is base +Z. Usually correct for a marker printed face-up.
        # -1:
        #   marker +Z is base -Z.
        self.declare_parameter('marker_z_sign', 1.0)

        self.declare_parameter('samples', 30)
        self.declare_parameter('min_samples_to_print', 10)
        self.declare_parameter('print_every_n_frames', 10)
        self.declare_parameter('show_image', True)

        # Use image timestamp for TF lookup.
        # If TF at the image timestamp is unavailable, fallback to latest TF.
        self.declare_parameter('use_image_timestamp', True)
        self.declare_parameter('fallback_to_latest_tf', True)
        self.declare_parameter('tf_timeout_sec', 0.2)

        # ----------------------------
        # Read parameters
        # ----------------------------
        self.image_topic = str(self.get_parameter('image_topic').value)
        self.camera_info_topic = str(self.get_parameter('camera_info_topic').value)

        self.base_frame = str(self.get_parameter('base_frame').value)
        self.parent_frame = str(self.get_parameter('parent_frame').value)
        self.camera_link_frame = str(self.get_parameter('camera_link_frame').value)
        self.optical_frame = str(self.get_parameter('optical_frame').value)

        self.marker_id = int(self.get_parameter('marker_id').value)
        self.marker_length = float(self.get_parameter('marker_length').value)
        self.aruco_dictionary = str(self.get_parameter('aruco_dictionary').value)

        self.calibration_mode = str(self.get_parameter('calibration_mode').value)
        self.marker_yaw_deg = float(self.get_parameter('marker_yaw_deg').value)
        self.marker_z_sign = (
            1.0 if float(self.get_parameter('marker_z_sign').value) >= 0.0 else -1.0
        )

        self.samples = int(self.get_parameter('samples').value)
        self.min_samples_to_print = int(self.get_parameter('min_samples_to_print').value)
        self.print_every_n_frames = int(self.get_parameter('print_every_n_frames').value)
        self.show_image = bool(self.get_parameter('show_image').value)

        self.use_image_timestamp = bool(self.get_parameter('use_image_timestamp').value)
        self.fallback_to_latest_tf = bool(self.get_parameter('fallback_to_latest_tf').value)
        self.tf_timeout_sec = float(self.get_parameter('tf_timeout_sec').value)

        # ----------------------------
        # Tools / state
        # ----------------------------
        self.bridge = CvBridge()
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        self.camera_matrix: Optional[np.ndarray] = None
        self.dist_coeffs: Optional[np.ndarray] = None

        # History of estimated R_parent_optical matrices.
        self.r_parent_optical_history: List[np.ndarray] = []
        self.frame_count = 0

        self.aruco_dict = self._create_aruco_dictionary(self.aruco_dictionary)
        self.aruco_params, self.detector = self._create_aruco_detector(self.aruco_dict)

        # ----------------------------
        # Subscribers
        # ----------------------------
        self.create_subscription(
            CameraInfo,
            self.camera_info_topic,
            self.camera_info_callback,
            1,
        )

        self.create_subscription(
            Image,
            self.image_topic,
            self.image_callback,
            1,
        )

        self.get_logger().info('RPY Calibration Node Started.')
        self.get_logger().info(f'image_topic: {self.image_topic}')
        self.get_logger().info(f'camera_info_topic: {self.camera_info_topic}')
        self.get_logger().info(
            f'frames: base={self.base_frame}, parent={self.parent_frame}, '
            f'camera_link={self.camera_link_frame}, optical={self.optical_frame}'
        )
        self.get_logger().info(
            f'ArUco marker_id={self.marker_id}, '
            f'marker_length={self.marker_length:.4f} m, '
            f'dictionary={self.aruco_dictionary}'
        )
        self.get_logger().info(
            f'calibration_mode={self.calibration_mode}, '
            f'marker_yaw_deg={self.marker_yaw_deg:.2f}, '
            f'marker_z_sign={self.marker_z_sign:+.0f}'
        )
        self.get_logger().info(
            f'use_image_timestamp={self.use_image_timestamp}, '
            f'fallback_to_latest_tf={self.fallback_to_latest_tf}, '
            f'tf_timeout_sec={self.tf_timeout_sec:.2f}'
        )
        self.get_logger().info(
            'Place the marker flat on the floor/table. '
            'For normal_only mode, marker yaw does not matter.'
        )

    # ============================================================
    # ArUco setup
    # ============================================================

    def _create_aruco_dictionary(self, dictionary_name: str):
        if not hasattr(cv2, 'aruco'):
            raise RuntimeError(
                'cv2.aruco is not available. '
                'Install opencv-contrib-python or ROS OpenCV package with aruco support.'
            )

        if not hasattr(cv2.aruco, dictionary_name):
            available = [name for name in dir(cv2.aruco) if name.startswith('DICT_')]
            raise ValueError(
                f'Unknown ArUco dictionary: {dictionary_name}. '
                f'Available examples: {available[:10]}'
            )

        dict_id = getattr(cv2.aruco, dictionary_name)

        try:
            return cv2.aruco.getPredefinedDictionary(dict_id)  # OpenCV >= 4.7
        except AttributeError:
            return cv2.aruco.Dictionary_get(dict_id)  # OpenCV < 4.7

    def _create_aruco_detector(self, aruco_dict):
        try:
            params = cv2.aruco.DetectorParameters()  # OpenCV >= 4.7
            detector = cv2.aruco.ArucoDetector(aruco_dict, params)
            return params, detector
        except AttributeError:
            params = cv2.aruco.DetectorParameters_create()  # OpenCV < 4.7
            return params, None

    # ============================================================
    # ROS callbacks
    # ============================================================

    def camera_info_callback(self, msg: CameraInfo):
        self.camera_matrix = np.array(msg.k, dtype=np.float64).reshape((3, 3))

        if len(msg.d) > 0:
            self.dist_coeffs = np.array(msg.d, dtype=np.float64)
        else:
            self.dist_coeffs = np.zeros((5,), dtype=np.float64)

    def image_callback(self, msg: Image):
        if self.camera_matrix is None:
            return

        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, 'bgr8')

            if self.detector is not None:
                corners, ids, _ = self.detector.detectMarkers(cv_image)
            else:
                corners, ids, _ = cv2.aruco.detectMarkers(
                    cv_image,
                    self.aruco_dict,
                    parameters=self.aruco_params,
                )

            if ids is None or self.marker_id not in ids.flatten().tolist():
                if self.show_image:
                    cv2.imshow('RPY Calibration', cv_image)
                    cv2.waitKey(1)
                return

            self.process_marker(corners, ids, cv_image, msg.header.stamp)

        except Exception as e:
            self.get_logger().error(f'Image processing error: {e}')

    # ============================================================
    # Main calibration process
    # ============================================================

    def process_marker(self, corners, ids, cv_image, image_stamp):
        ids_flat = ids.flatten()
        marker_index = int(np.where(ids_flat == self.marker_id)[0][0])
        marker_corners = corners[marker_index].reshape((4, 2)).astype(np.float32)

        obj_points = np.array(
            [
                [-self.marker_length / 2.0,  self.marker_length / 2.0, 0.0],
                [ self.marker_length / 2.0,  self.marker_length / 2.0, 0.0],
                [ self.marker_length / 2.0, -self.marker_length / 2.0, 0.0],
                [-self.marker_length / 2.0, -self.marker_length / 2.0, 0.0],
            ],
            dtype=np.float32,
        )

        success, rvec, tvec = cv2.solvePnP(
            obj_points,
            marker_corners,
            self.camera_matrix,
            self.dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )

        if not success:
            return

        if self.show_image:
            cv2.aruco.drawDetectedMarkers(cv_image, corners, ids)
            cv2.drawFrameAxes(
                cv_image,
                self.camera_matrix,
                self.dist_coeffs,
                rvec,
                tvec,
                self.marker_length * 0.5,
            )
            cv2.imshow('RPY Calibration', cv_image)
            cv2.waitKey(1)

        # R_cam_marker maps vectors from marker frame to optical camera frame.
        # In OpenCV camera coordinates:
        #   x: image right
        #   y: image down
        #   z: camera forward
        R_cam_marker, _ = cv2.Rodrigues(rvec)
        t_cam_marker = tvec.reshape(3)

        try:
            stamp = Time.from_msg(image_stamp) if self.use_image_timestamp else Time()

            R_base_parent = self._lookup_rotation(
                self.base_frame,
                self.parent_frame,
                stamp,
            )
            R_parent_camera_link_current = self._lookup_rotation(
                self.parent_frame,
                self.camera_link_frame,
                stamp,
            )
            R_camera_link_optical = self._lookup_rotation(
                self.camera_link_frame,
                self.optical_frame,
                stamp,
            )

        except Exception as e:
            self.get_logger().warn(f'Waiting for TF tree... {e}')
            return

        R_parent_optical_current = (
            R_parent_camera_link_current @ R_camera_link_optical
        )

        if self.calibration_mode == 'full_marker':
            R_parent_optical_new = self._estimate_full_marker_rotation(
                R_cam_marker=R_cam_marker,
                R_base_parent=R_base_parent,
            )

        elif self.calibration_mode == 'normal_only':
            R_parent_optical_new = self._estimate_normal_only_rotation(
                R_cam_marker=R_cam_marker,
                R_base_parent=R_base_parent,
                R_parent_optical_current=R_parent_optical_current,
            )

        else:
            self.get_logger().error(
                f'Unknown calibration_mode={self.calibration_mode}. '
                'Use normal_only or full_marker.'
            )
            return

        self._append_rotation_sample(R_parent_optical_new)

        self.frame_count += 1

        if len(self.r_parent_optical_history) < self.min_samples_to_print:
            return

        if self.frame_count % max(self.print_every_n_frames, 1) != 0:
            return

        R_parent_optical_avg = self._average_rotations(self.r_parent_optical_history)

        # We need URDF origin rotation:
        #   R_parent_camera_link_new
        # because RealSense macro internally provides:
        #   R_camera_link_optical
        #
        # Therefore:
        #   R_parent_optical_new = R_parent_camera_link_new * R_camera_link_optical
        #   R_parent_camera_link_new = R_parent_optical_new * inv(R_camera_link_optical)
        R_parent_camera_link_new = (
            R_parent_optical_avg @ R_camera_link_optical.T
        )

        current_rpy = R.from_matrix(
            R_parent_camera_link_current
        ).as_euler('xyz')

        raw_new_rpy = R.from_matrix(
            R_parent_camera_link_new
        ).as_euler('xyz')

        best_rpy = self._closest_equivalent_euler_xyz(raw_new_rpy, current_rpy)
        best_rpy_wrapped = self._wrap_to_pi(best_rpy)

        current_normal_error_deg, new_normal_error_deg = self._normal_error_debug(
            R_cam_marker=R_cam_marker,
            R_base_parent=R_base_parent,
            R_parent_optical_current=R_parent_optical_current,
            R_parent_optical_new=R_parent_optical_avg,
        )

        marker_distance = float(np.linalg.norm(t_cam_marker))
        predicted_z_error = marker_distance * math.sin(
            math.radians(current_normal_error_deg)
        )

        self._print_result(
            sample_count=len(self.r_parent_optical_history),
            marker_distance=marker_distance,
            t_cam_marker=t_cam_marker,
            current_normal_error_deg=current_normal_error_deg,
            new_normal_error_deg=new_normal_error_deg,
            predicted_z_error=predicted_z_error,
            current_rpy=current_rpy,
            raw_new_rpy=raw_new_rpy,
            best_rpy=best_rpy,
            best_rpy_wrapped=best_rpy_wrapped,
        )

    # ============================================================
    # Calibration math
    # ============================================================

    def _estimate_full_marker_rotation(
        self,
        R_cam_marker: np.ndarray,
        R_base_parent: np.ndarray,
    ) -> np.ndarray:
        """
        Full orientation estimate.

        Assumption:
          marker frame orientation in base_link is known.
          By default, marker x-axis is aligned with base_link x-axis.

        Formula:
          R_base_marker = R_base_parent * R_parent_optical * R_optical_marker
          R_parent_optical = R_base_parent.T * R_base_marker * R_optical_marker.T
        """
        yaw = math.radians(self.marker_yaw_deg)
        R_base_marker = R.from_euler('z', yaw).as_matrix()

        if self.marker_z_sign < 0.0:
            # If the marker +Z points downward in base, flip marker frame around X.
            R_base_marker = R_base_marker @ R.from_euler('x', math.pi).as_matrix()

        return R_base_parent.T @ R_base_marker @ R_cam_marker.T

    def _estimate_normal_only_rotation(
        self,
        R_cam_marker: np.ndarray,
        R_base_parent: np.ndarray,
        R_parent_optical_current: np.ndarray,
    ) -> np.ndarray:
        """
        Pitch/roll-only correction from the marker plane normal.

        It does not require the marker yaw on the floor/table to be known.
        We compute the minimum correction in the parent frame that rotates the
        currently predicted marker normal onto the expected gravity normal.
        """
        marker_normal_in_optical = R_cam_marker[:, 2]

        expected_marker_normal_in_base = (
            self.marker_z_sign * np.array([0.0, 0.0, 1.0])
        )

        expected_marker_normal_in_parent = (
            R_base_parent.T @ expected_marker_normal_in_base
        )

        current_marker_normal_in_parent = (
            R_parent_optical_current @ marker_normal_in_optical
        )

        correction_parent = self._rotation_between_vectors(
            current_marker_normal_in_parent,
            expected_marker_normal_in_parent,
        )

        return correction_parent @ R_parent_optical_current

    def _normal_error_debug(
        self,
        R_cam_marker: np.ndarray,
        R_base_parent: np.ndarray,
        R_parent_optical_current: np.ndarray,
        R_parent_optical_new: np.ndarray,
    ):
        marker_normal_in_optical = R_cam_marker[:, 2]

        expected_marker_normal_in_base = (
            self.marker_z_sign * np.array([0.0, 0.0, 1.0])
        )

        expected_marker_normal_in_parent = (
            R_base_parent.T @ expected_marker_normal_in_base
        )

        current_normal = R_parent_optical_current @ marker_normal_in_optical
        new_normal = R_parent_optical_new @ marker_normal_in_optical

        return (
            self._angle_between_vectors(
                current_normal,
                expected_marker_normal_in_parent,
            ),
            self._angle_between_vectors(
                new_normal,
                expected_marker_normal_in_parent,
            ),
        )

    # ============================================================
    # TF helper
    # ============================================================

    def _lookup_rotation(
        self,
        target_frame: str,
        source_frame: str,
        stamp: Time,
    ) -> np.ndarray:
        """
        Lookup rotation matrix from source_frame to target_frame.

        If timestamp lookup fails and fallback_to_latest_tf is true,
        it retries with latest TF.
        """
        timeout = Duration(seconds=self.tf_timeout_sec)

        try:
            tf_msg = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                stamp,
                timeout=timeout,
            )
        except Exception:
            if not self.fallback_to_latest_tf:
                raise

            tf_msg = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                Time(),
                timeout=timeout,
            )

        q = tf_msg.transform.rotation
        return R.from_quat([q.x, q.y, q.z, q.w]).as_matrix()

    # ============================================================
    # Rotation averaging / utilities
    # ============================================================

    def _append_rotation_sample(self, rotation_matrix: np.ndarray):
        self.r_parent_optical_history.append(rotation_matrix)

        if len(self.r_parent_optical_history) > self.samples:
            self.r_parent_optical_history.pop(0)

    def _average_rotations(self, rotation_matrices: List[np.ndarray]) -> np.ndarray:
        """
        Quaternion Markley average.
        Returns a 3x3 rotation matrix.
        """
        quats = R.from_matrix(np.stack(rotation_matrices)).as_quat()  # x, y, z, w

        ref = quats[0]

        for i in range(len(quats)):
            if np.dot(quats[i], ref) < 0.0:
                quats[i] *= -1.0

        A = quats.T @ quats
        eigenvalues, eigenvectors = np.linalg.eigh(A)

        avg_quat = eigenvectors[:, np.argmax(eigenvalues)]

        if avg_quat[3] < 0.0:
            avg_quat *= -1.0

        return R.from_quat(avg_quat).as_matrix()

    def _rotation_between_vectors(
        self,
        src: np.ndarray,
        dst: np.ndarray,
    ) -> np.ndarray:
        src = self._normalize(src)
        dst = self._normalize(dst)

        dot = float(np.clip(np.dot(src, dst), -1.0, 1.0))

        if dot > 1.0 - 1e-9:
            return np.eye(3)

        if dot < -1.0 + 1e-9:
            # 180 degree rotation:
            # choose an arbitrary axis perpendicular to src.
            axis = np.cross(src, np.array([1.0, 0.0, 0.0]))

            if np.linalg.norm(axis) < 1e-6:
                axis = np.cross(src, np.array([0.0, 1.0, 0.0]))

            axis = self._normalize(axis)
            return R.from_rotvec(math.pi * axis).as_matrix()

        axis = np.cross(src, dst)
        axis = self._normalize(axis)
        angle = math.acos(dot)

        return R.from_rotvec(angle * axis).as_matrix()

    def _angle_between_vectors(
        self,
        a: np.ndarray,
        b: np.ndarray,
    ) -> float:
        a = self._normalize(a)
        b = self._normalize(b)

        return math.degrees(
            math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0)))
        )

    def _normalize(self, v: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(v)

        if norm < 1e-12:
            raise ValueError('zero-length vector cannot be normalized')

        return v / norm

    def _closest_equivalent_euler_xyz(
        self,
        euler_xyz: np.ndarray,
        reference_xyz: np.ndarray,
    ) -> np.ndarray:
        """
        Return an equivalent xyz Euler representation closest to reference_xyz.

        This helps avoid confusing large jumps when the current RPY is near a
        singularity such as pitch ~= +/- pi/2.
        """
        base_candidates = [
            np.array(euler_xyz),
            np.array([
                euler_xyz[0] + math.pi,
                math.pi - euler_xyz[1],
                euler_xyz[2] + math.pi,
            ]),
        ]

        best = np.array(euler_xyz)
        best_score = float('inf')

        for base in base_candidates:
            for sx in [-2.0 * math.pi, 0.0, 2.0 * math.pi]:
                for sy in [-2.0 * math.pi, 0.0, 2.0 * math.pi]:
                    for sz in [-2.0 * math.pi, 0.0, 2.0 * math.pi]:
                        candidate = base + np.array([sx, sy, sz])
                        score = np.sum(
                            self._wrap_to_pi(candidate - reference_xyz) ** 2
                        )

                        if score < best_score:
                            best_score = score
                            best = candidate

        return best

    def _wrap_to_pi(self, angles: np.ndarray) -> np.ndarray:
        return (angles + math.pi) % (2.0 * math.pi) - math.pi

    # ============================================================
    # Logging
    # ============================================================

    def _print_result(
        self,
        sample_count: int,
        marker_distance: float,
        t_cam_marker: np.ndarray,
        current_normal_error_deg: float,
        new_normal_error_deg: float,
        predicted_z_error: float,
        current_rpy: np.ndarray,
        raw_new_rpy: np.ndarray,
        best_rpy: np.ndarray,
        best_rpy_wrapped: np.ndarray,
    ):
        current_rpy_deg = np.degrees(current_rpy)
        wrapped_deg = np.degrees(best_rpy_wrapped)

        self.get_logger().info('\n[RealSense Hand Camera RPY Calibration]')
        self.get_logger().info(f'samples: {sample_count}/{self.samples}')
        self.get_logger().info(
            f'marker distance from optical frame: {marker_distance:.4f} m, '
            f'tvec=[{t_cam_marker[0]:+.4f}, '
            f'{t_cam_marker[1]:+.4f}, '
            f'{t_cam_marker[2]:+.4f}] m'
        )
        self.get_logger().info(
            f'normal error current -> calibrated: '
            f'{current_normal_error_deg:.3f} deg -> '
            f'{new_normal_error_deg:.3f} deg'
        )
        self.get_logger().info(
            f'rough Z error caused by current tilt at this distance: '
            f'{predicted_z_error * 100.0:.2f} cm'
        )

        self.get_logger().info(
            'Current URDF rotation: '
            f'rpy="{current_rpy[0]:.6f} '
            f'{current_rpy[1]:.6f} '
            f'{current_rpy[2]:.6f}" '
            f'deg=[{current_rpy_deg[0]:+.2f}, '
            f'{current_rpy_deg[1]:+.2f}, '
            f'{current_rpy_deg[2]:+.2f}]'
        )

        self.get_logger().info(
            'Corrected URDF rotation raw: '
            f'rpy="{raw_new_rpy[0]:.6f} '
            f'{raw_new_rpy[1]:.6f} '
            f'{raw_new_rpy[2]:.6f}"'
        )

        self.get_logger().info(
            'Corrected URDF rotation closest-to-current: '
            f'rpy="{best_rpy[0]:.6f} '
            f'{best_rpy[1]:.6f} '
            f'{best_rpy[2]:.6f}"'
        )

        self.get_logger().info(
            'Corrected URDF rotation (wrapped): '
            f'rpy="{best_rpy_wrapped[0]:.6f} '
            f'{best_rpy_wrapped[1]:.6f} '
            f'{best_rpy_wrapped[2]:.6f}" '
            f'deg=[{wrapped_deg[0]:+.2f}, '
            f'{wrapped_deg[1]:+.2f}, '
            f'{wrapped_deg[2]:+.2f}]'
        )

        self.get_logger().info(
            'Copy "Corrected URDF rotation (wrapped)" into the '
            '<origin ... rpy="..."/> of xacro:sensor_d435i.'
        )
        self.get_logger().info(
            'Keep xyz unchanged first. Adjust xyz only after tilt error is removed.'
        )
        self.get_logger().info('---------------------------------------------')


def main(args=None):
    rclpy.init(args=args)

    node = RPYCalibrationNode()

    try:
        rclpy.spin(node)

    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()