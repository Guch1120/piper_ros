#!/usr/bin/env python3
"""AMR_TOOLKIT のウェイポイントを Nav2 へ順番に送る巡回ノード。"""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Optional

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from std_srvs.srv import Empty
import yaml


@dataclass(frozen=True)
class Waypoint:
    """Nav2 に送る 2D ウェイポイント。"""

    number: int
    x: float
    y: float
    yaw: float


def _finite_float(value: Any, field_name: str) -> float:
    """有限な浮動小数点値へ変換する。"""
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} は数値である必要があります: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name} は有限値である必要があります: {value!r}")
    return result


def _read_pgm_size(path: Path) -> tuple[int, int]:
    """P2/P5 PGM のヘッダから width/height を読む。"""
    with path.open("rb") as stream:
        tokens: list[bytes] = []
        while len(tokens) < 4:
            line = stream.readline()
            if not line:
                break
            line = line.split(b"#", 1)[0]
            tokens.extend(line.split())
    if len(tokens) < 4 or tokens[0] not in (b"P2", b"P5"):
        raise ValueError(f"対応する PGM ヘッダを読めません: {path}")
    return int(tokens[1]), int(tokens[2])


def _resolve_map_image(map_yaml_path: Path, image_value: str) -> Path:
    """map YAML の image を YAML 基準の絶対パスへ解決する。"""
    image_path = Path(image_value)
    if not image_path.is_absolute():
        image_path = map_yaml_path.parent / image_path
    return image_path


def load_waypoints(waypoint_path: str, map_yaml_path: str = "") -> list[Waypoint]:
    """AMR_TOOLKIT の新形式と旧 points 形式を読み込む。"""
    source_path = Path(waypoint_path).expanduser().resolve()
    with source_path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}

    if isinstance(data.get("waypoints"), list):
        waypoints: list[Waypoint] = []
        for index, item in enumerate(data["waypoints"], 1):
            if not isinstance(item, dict):
                raise ValueError(f"waypoints[{index}] はマッピングである必要があります")
            yaw_value = item.get("angle_radians")
            if yaw_value is None and item.get("angle_degrees") is not None:
                yaw_value = math.radians(_finite_float(item["angle_degrees"], "angle_degrees"))
            if yaw_value is None:
                yaw_value = 0.0
            number = int(item.get("number", index))
            waypoints.append(Waypoint(
                number=number,
                x=_finite_float(item.get("x"), f"waypoints[{index}].x"),
                y=_finite_float(item.get("y"), f"waypoints[{index}].y"),
                yaw=_finite_float(yaw_value, f"waypoints[{index}].angle_radians"),
            ))
        if not waypoints:
            raise ValueError("waypoints が空です")
        return waypoints

    if not isinstance(data.get("points"), list):
        raise ValueError("AMR_TOOLKIT の waypoints または旧形式の points がありません")
    if not map_yaml_path:
        raise ValueError("旧形式 points には map_yaml が必要です")

    map_path = Path(map_yaml_path).expanduser().resolve()
    with map_path.open("r", encoding="utf-8") as stream:
        map_data = yaml.safe_load(stream) or {}
    resolution = _finite_float(map_data.get("resolution"), "map.resolution")
    origin = map_data.get("origin")
    if not isinstance(origin, list) or len(origin) < 2:
        raise ValueError("map.origin に [x, y, yaw] が必要です")
    origin_x = _finite_float(origin[0], "map.origin[0]")
    origin_y = _finite_float(origin[1], "map.origin[1]")
    image_value = map_data.get("image")
    if not image_value:
        raise ValueError("旧形式変換には map.image が必要です")
    image_path = _resolve_map_image(map_path, str(image_value))
    width, height = _read_pgm_size(image_path)

    waypoints = []
    for index, item in enumerate(data["points"], 1):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError(f"points[{index}] は少なくとも [px, py] が必要です")
        pixel_x = _finite_float(item[0], f"points[{index}][0]")
        pixel_y = _finite_float(item[1], f"points[{index}][1]")
        # PGM の原点は左下、画像の pixel_y は上から下へ増える。
        x = origin_x + (pixel_x + 0.5) * resolution
        y = origin_y + (height - pixel_y - 0.5) * resolution
        qz = _finite_float(item[5], f"points[{index}][5]") if len(item) > 5 else 0.0
        qw = _finite_float(item[6], f"points[{index}][6]") if len(item) > 6 else 1.0
        yaw = 2.0 * math.atan2(qz, qw)
        waypoints.append(Waypoint(index, x, y, yaw))
    if not waypoints:
        raise ValueError("points が空です")
    return waypoints


class WaypointPatrolNode(Node):
    """NavigateToPose を一つずつ完了させる巡回実行器。"""

    def __init__(self) -> None:
        super().__init__("waypoint_patrol")
        self.declare_parameter("waypoint_file", "")
        self.declare_parameter("map_yaml", "")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("action_name", "navigate_to_pose")
        self.declare_parameter("start_delay_sec", 1.0)
        self.declare_parameter("goal_timeout_sec", 180.0)
        self.declare_parameter("localization_timeout_sec", 30.0)
        self.declare_parameter("localization_settle_sec", 2.0)
        self.declare_parameter("inter_goal_settle_sec", 2.0)
        self.declare_parameter("amcl_pose_max_age_sec", 2.0)
        self.declare_parameter("clear_costmaps_before_goal", True)
        self.declare_parameter("publish_initial_pose", False)
        self.declare_parameter("initial_pose_x", 0.0)
        self.declare_parameter("initial_pose_y", 0.0)
        self.declare_parameter("initial_pose_yaw", 0.0)
        self.declare_parameter("initial_pose_stamp_offset_sec", 0.2)
        self.declare_parameter("initial_pose_publish_count", 6)
        self.declare_parameter("initial_pose_publish_period_sec", 0.5)

        waypoint_file = str(self.get_parameter("waypoint_file").value)
        map_yaml = str(self.get_parameter("map_yaml").value)
        if not waypoint_file:
            raise ValueError("waypoint_file パラメータが必要です")
        self.frame_id = str(self.get_parameter("frame_id").value)
        self.goal_timeout_sec = float(self.get_parameter("goal_timeout_sec").value)
        self.localization_timeout_sec = float(
            self.get_parameter("localization_timeout_sec").value)
        self.localization_settle_sec = float(
            self.get_parameter("localization_settle_sec").value)
        self.inter_goal_settle_sec = float(
            self.get_parameter("inter_goal_settle_sec").value)
        self.amcl_pose_max_age_sec = float(
            self.get_parameter("amcl_pose_max_age_sec").value)
        self.clear_costmaps_before_goal = bool(
            self.get_parameter("clear_costmaps_before_goal").value)
        self.publish_initial_pose = bool(self.get_parameter("publish_initial_pose").value)
        self.initial_pose_x = float(self.get_parameter("initial_pose_x").value)
        self.initial_pose_y = float(self.get_parameter("initial_pose_y").value)
        self.initial_pose_yaw = float(self.get_parameter("initial_pose_yaw").value)
        self.initial_pose_stamp_offset_sec = float(
            self.get_parameter("initial_pose_stamp_offset_sec").value)
        self.initial_pose_publish_count = int(
            self.get_parameter("initial_pose_publish_count").value)
        self.initial_pose_publish_period_sec = float(
            self.get_parameter("initial_pose_publish_period_sec").value)
        self.waypoints = load_waypoints(waypoint_file, map_yaml)
        self.current_index = 0
        self.current_goal_handle = None
        self.goal_started_at = None
        self.last_odom: Optional[Odometry] = None
        self.last_world_pose: Optional[PoseStamped] = None
        self.last_amcl_receive_time = None
        self.localization_started_at = None
        self.localization_ready = False
        self.next_goal_ready_at = None
        self.retry_timer = None
        self.clear_costmap_clients = [
            self.create_client(Empty, "/local_costmap/clear_entirely_local_costmap"),
            self.create_client(Empty, "/global_costmap/clear_entirely_global_costmap"),
        ]
        self.clear_costmap_pending = 0
        self.clear_costmap_deadline = None
        self.initial_pose_pub = None
        self.initial_pose_timer = None
        self.initial_pose_publish_index = 0
        self.finished = False
        self.failed = False

        action_name = str(self.get_parameter("action_name").value)
        self.action_client = ActionClient(self, NavigateToPose, action_name)
        self.create_subscription(Odometry, "/odom", self._odom_callback, 10)
        self.create_subscription(
            PoseStamped, "/kobuki_unity/world_pose", self._world_pose_callback, 10)
        self.create_subscription(
            PoseWithCovarianceStamped, "/amcl_pose", self._amcl_pose_callback, 10)
        if self.publish_initial_pose:
            self.initial_pose_pub = self.create_publisher(
                PoseWithCovarianceStamped, "/initialpose", 10)
        self.create_timer(0.2, self._state_timer_callback)
        delay = max(0.0, float(self.get_parameter("start_delay_sec").value))
        self.create_timer(delay, self._start_once)
        self._started = False
        self.get_logger().info(
            f"PATROL_LOADED count={len(self.waypoints)} file={waypoint_file}")
        for index, waypoint in enumerate(self.waypoints, 1):
            self.get_logger().info(
                f"PATROL_WAYPOINT index={index} number={waypoint.number} "
                f"x={waypoint.x:.6f} y={waypoint.y:.6f} yaw={waypoint.yaw:.6f}")

    def _start_once(self) -> None:
        if self._started:
            return
        self._started = True
        self.localization_started_at = self.get_clock().now()
        if self.publish_initial_pose:
            self._publish_initial_pose()
            self.initial_pose_timer = self.create_timer(
                max(0.1, self.initial_pose_publish_period_sec),
                self._publish_initial_pose)
        self.get_logger().info(
            f"PATROL_WAITING_FOR_AMCL timeout={self.localization_timeout_sec:.1f} "
            f"settle={self.localization_settle_sec:.1f} "
            f"initial_pose_enabled={self.publish_initial_pose}")

    def _publish_initial_pose(self) -> None:
        """初回 localization 専用。goal 間の map->odom をリセットしない。"""
        if self.initial_pose_pub is None or \
                self.initial_pose_publish_index >= self.initial_pose_publish_count:
            if self.initial_pose_timer is not None:
                self.initial_pose_timer.cancel()
            return

        stamp = self.get_clock().now() - Duration(
            seconds=max(0.0, self.initial_pose_stamp_offset_sec))
        message = PoseWithCovarianceStamped()
        message.header.frame_id = self.frame_id
        message.header.stamp = stamp.to_msg()
        message.pose.pose.position.x = self.initial_pose_x
        message.pose.pose.position.y = self.initial_pose_y
        message.pose.pose.orientation.z = math.sin(self.initial_pose_yaw / 2.0)
        message.pose.pose.orientation.w = math.cos(self.initial_pose_yaw / 2.0)
        message.pose.covariance[0] = 0.05
        message.pose.covariance[7] = 0.05
        message.pose.covariance[35] = 0.1
        self.initial_pose_pub.publish(message)
        self.initial_pose_publish_index += 1
        self.get_logger().info(
            f"PATROL_INITIAL_POSE_SENT index={self.initial_pose_publish_index}/"
            f"{self.initial_pose_publish_count} stamp_offset_sec="
            f"{self.initial_pose_stamp_offset_sec:.3f}")

    def _odom_callback(self, message: Odometry) -> None:
        self.last_odom = message

    def _world_pose_callback(self, message: PoseStamped) -> None:
        self.last_world_pose = message

    def _amcl_pose_callback(self, _message: PoseWithCovarianceStamped) -> None:
        """AMCL の受信時刻を記録し、initial pose は再送しない。"""
        now = self.get_clock().now()
        if self.last_amcl_receive_time is None:
            self.localization_started_at = now
            self.get_logger().info("PATROL_AMCL_POSE_FIRST_RECEIVED")
        self.last_amcl_receive_time = now

    def _state_timer_callback(self) -> None:
        """初回 localization と goal 間の安定化を非ブロッキングで待つ。"""
        if self.finished or self.failed or not self._started:
            return

        now = self.get_clock().now()
        if not self.localization_ready:
            if self.last_amcl_receive_time is None:
                elapsed = (now - self.localization_started_at).nanoseconds / 1e9 \
                    if self.localization_started_at is not None else 0.0
                if elapsed > self.localization_timeout_sec:
                    self.failed = True
                    self.get_logger().error(
                        f"PATROL_LOCALIZATION_TIMEOUT elapsed={elapsed:.1f} "
                        f"timeout={self.localization_timeout_sec:.1f}")
                return

            receive_age = (now - self.last_amcl_receive_time).nanoseconds / 1e9
            stable_elapsed = (now - self.localization_started_at).nanoseconds / 1e9
            if receive_age <= self.amcl_pose_max_age_sec and \
                    stable_elapsed >= self.localization_settle_sec:
                self.localization_ready = True
                if self.initial_pose_timer is not None:
                    self.initial_pose_timer.cancel()
                    self.initial_pose_timer = None
                self.get_logger().info(
                    f"PATROL_LOCALIZATION_READY stable_sec={stable_elapsed:.1f} "
                    f"pose_age_sec={receive_age:.3f} initial_pose_resend=false")
                self._send_next_goal()
                return

            if stable_elapsed > self.localization_timeout_sec:
                self.failed = True
                self.get_logger().error(
                    f"PATROL_LOCALIZATION_TIMEOUT elapsed={stable_elapsed:.1f} "
                    f"pose_age_sec={receive_age:.3f}")
            return

        if self.current_goal_handle is None and self.next_goal_ready_at is not None:
            if (now - self.next_goal_ready_at).nanoseconds >= 0:
                self.next_goal_ready_at = None
                self._send_next_goal()

        self._timeout_callback()

    def _clear_costmap_done(self, _future: Any) -> None:
        """costmap clear service の完了を記録する。"""
        self.clear_costmap_pending = max(0, self.clear_costmap_pending - 1)

    def _costmaps_ready_for_goal(self) -> bool:
        """各 goal の直前に一時障害物レイヤーを一度だけ消去する。"""
        if not self.clear_costmaps_before_goal:
            return True
        if self.clear_costmap_deadline is not None:
            now = self.get_clock().now()
            if self.clear_costmap_pending > 0 and now < self.clear_costmap_deadline:
                return False
            if self.clear_costmap_pending > 0:
                self.get_logger().warn(
                    "PATROL_COSTMAP_CLEAR_TIMEOUT proceeding_with_pending_requests=true")
                self.clear_costmap_pending = 0
            self.clear_costmap_deadline = None
            return True

        self.clear_costmap_pending = 0
        for client in self.clear_costmap_clients:
            if not client.service_is_ready():
                continue
            future = client.call_async(Empty.Request())
            future.add_done_callback(self._clear_costmap_done)
            self.clear_costmap_pending += 1
        self.get_logger().info(
            f"PATROL_COSTMAP_CLEAR requested={self.clear_costmap_pending}")
        if self.clear_costmap_pending == 0:
            return True
        self.clear_costmap_deadline = self.get_clock().now() + Duration(seconds=1.0)
        return False

    def _send_next_goal(self) -> None:
        if self.current_index >= len(self.waypoints):
            self.finished = True
            self.get_logger().info(
                f"PATROL_COMPLETE visited={len(self.waypoints)} total={len(self.waypoints)}")
            return
        waypoint = self.waypoints[self.current_index]
        if not self.action_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("PATROL_WAITING_FOR_NAV2 action=navigate_to_pose")
            if self.retry_timer is None:
                self.retry_timer = self.create_timer(1.0, self._retry_send_once)
            return
        if not self._costmaps_ready_for_goal():
            return

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self.frame_id
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = waypoint.x
        goal.pose.pose.position.y = waypoint.y
        goal.pose.pose.orientation.z = math.sin(waypoint.yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(waypoint.yaw / 2.0)
        self.goal_started_at = self.get_clock().now()
        self.get_logger().info(
            f"PATROL_GOAL_SENT index={self.current_index + 1}/{len(self.waypoints)} "
            f"x={waypoint.x:.6f} y={waypoint.y:.6f} yaw={waypoint.yaw:.6f}")
        future = self.action_client.send_goal_async(goal, feedback_callback=self._feedback_callback)
        future.add_done_callback(self._goal_response_callback)

    def _retry_send_once(self) -> None:
        if self.retry_timer is not None:
            self.retry_timer.cancel()
            self.retry_timer = None
        self._send_next_goal()

    def _feedback_callback(self, feedback_message: Any) -> None:
        feedback = feedback_message.feedback
        distance = getattr(feedback, "distance_remaining", None)
        if distance is not None:
            self.get_logger().info(
                f"PATROL_FEEDBACK index={self.current_index + 1} "
                f"distance_remaining={float(distance):.3f}")

    def _goal_response_callback(self, future: Any) -> None:
        try:
            goal_handle = future.result()
        except Exception as exc:  # pragma: no cover - ROS transport error
            self.failed = True
            self.get_logger().error(f"PATROL_GOAL_RESPONSE_ERROR error={exc}")
            return
        if not goal_handle.accepted:
            self.failed = True
            self.get_logger().error(
                f"PATROL_GOAL_REJECTED index={self.current_index + 1}")
            return
        self.current_goal_handle = goal_handle
        self.get_logger().info(
            f"PATROL_GOAL_ACCEPTED index={self.current_index + 1}/{len(self.waypoints)}")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._result_callback)

    def _result_callback(self, future: Any) -> None:
        wrapped_result = future.result()
        status = int(wrapped_result.status)
        waypoint = self.waypoints[self.current_index]
        self.get_logger().info(
            f"PATROL_GOAL_RESULT index={self.current_index + 1} "
            f"status={status} status_name={self._status_name(status)}")
        if status != GoalStatus.STATUS_SUCCEEDED:
            self.failed = True
            self.get_logger().error(
                f"PATROL_STOPPED index={self.current_index + 1} "
                f"reason={self._status_name(status)}")
            return
        self._log_arrival(waypoint)
        self.current_index += 1
        self.current_goal_handle = None
        self.goal_started_at = None
        self.next_goal_ready_at = self.get_clock().now() + Duration(
            seconds=self.inter_goal_settle_sec)
        self.get_logger().info(
            f"PATROL_INTER_GOAL_SETTLE index={self.current_index + 1} "
            f"seconds={self.inter_goal_settle_sec:.1f} initial_pose_resend=false")

    def _log_arrival(self, waypoint: Waypoint) -> None:
        if self.last_odom is not None:
            pose = self.last_odom.pose.pose
            self.get_logger().info(
                f"PATROL_ARRIVAL index={self.current_index + 1} "
                f"target=({waypoint.x:.6f},{waypoint.y:.6f}) "
                f"odom=({pose.position.x:.6f},{pose.position.y:.6f})")
        else:
            self.get_logger().warn(
                f"PATROL_ARRIVAL index={self.current_index + 1} odom=UNAVAILABLE")
        if self.last_world_pose is not None:
            pose = self.last_world_pose.pose
            self.get_logger().info(
                f"PATROL_WORLD_ARRIVAL index={self.current_index + 1} "
                f"world_pose=({pose.position.x:.6f},{pose.position.y:.6f})")
        else:
            self.get_logger().warn(
                f"PATROL_WORLD_ARRIVAL index={self.current_index + 1} world_pose=UNAVAILABLE")

    def _timeout_callback(self) -> None:
        if self.current_goal_handle is None or self.goal_started_at is None:
            return
        elapsed = (self.get_clock().now() - self.goal_started_at).nanoseconds / 1e9
        if elapsed <= self.goal_timeout_sec:
            return
        index = self.current_index + 1
        self.get_logger().error(
            f"PATROL_GOAL_TIMEOUT index={index} elapsed={elapsed:.1f} "
            f"timeout={self.goal_timeout_sec:.1f}")
        self.failed = True
        self.current_goal_handle.cancel_goal_async()

    @staticmethod
    def _status_name(status: int) -> str:
        names = {
            GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
            GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
            GoalStatus.STATUS_EXECUTING: "EXECUTING",
            GoalStatus.STATUS_CANCELING: "CANCELING",
            GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
            GoalStatus.STATUS_CANCELED: "CANCELED",
            GoalStatus.STATUS_ABORTED: "ABORTED",
        }
        return names.get(status, f"STATUS_{status}")


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node: Optional[WaypointPatrolNode] = None
    try:
        node = WaypointPatrolNode()
        while rclpy.ok() and not node.finished and not node.failed:
            rclpy.spin_once(node, timeout_sec=0.2)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        if node is not None:
            node.get_logger().error(f"PATROL_CONFIG_ERROR error={exc}")
        else:
            print(f"PATROL_CONFIG_ERROR error={exc}")
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
