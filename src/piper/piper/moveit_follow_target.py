#!/usr/bin/env python3
"""
SAM3 のマスク差分 (/sam3/target_diff) を使い、MoveIt でエンドエフェクタを横方向に追従させる。

  target_diff_node (sam3_bridge)  --PointStamped(diff_pixel)-->  この node  --MoveGroup action-->  move_group

* 横方向 = カメラ(camera_color_optical_frame)のx軸方向。物体が画像右にあれば(diff>0)+x側へ動かす。
* 目標は「現在のlink6位置 + ステップ」。姿勢制約は付けない(位置制約のみ)。
  `orientation_tolerance` > 0 にすると現在姿勢を保持する制約を追加できる。
* 1ステップ実行 → settle_time 待つ → そのあとに撮られた差分で次のステップ、という閉ループ。
  (カメラが手先にあるため、動作中の古いマスクで動かないようにヘッダstampで判定する)
* 安全のため enable サービスを呼ぶまで動かない。enable時の位置を起点に max_total_offset を超えて動かない。
"""
import math

import rclpy
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from geometry_msgs.msg import Pose, PointStamped
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (BoundingVolume, Constraints, MoveItErrorCodes,
                             OrientationConstraint, PositionConstraint)
from shape_msgs.msg import SolidPrimitive
from std_srvs.srv import SetBool
from tf2_ros import TransformException
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener


def quat_x_axis(q):
    """クォータニオンの回転行列の第1列 (= 回転後のx軸ベクトル)。"""
    return (1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            2.0 * (q.x * q.y + q.w * q.z),
            2.0 * (q.x * q.z - q.w * q.y))


def compute_step(diff_pixel, gain, deadband, max_step):
    """差分[pixel] -> 移動量[m]。不感帯内は0、max_stepでクリップ。"""
    if abs(diff_pixel) <= deadband:
        return 0.0
    return max(-max_step, min(max_step, gain * diff_pixel))


class MoveItFollowTarget(Node):
    def __init__(self):
        super().__init__('follow_target')
        self.declare_parameter('diff_topic', '/sam3/target_diff')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('ee_link', 'link6')
        self.declare_parameter('camera_frame', 'camera_color_optical_frame')
        self.declare_parameter('group_name', 'arm')
        self.declare_parameter('move_action', 'move_action')
        self.declare_parameter('gain_m_per_px', 0.0004)     # 100px -> 4cm。向きが逆なら負にする
        self.declare_parameter('deadband_px', 15.0)
        self.declare_parameter('max_step', 0.03)            # 1回の最大移動[m]
        self.declare_parameter('max_total_offset', 0.15)    # enable位置からの最大移動[m]
        self.declare_parameter('position_tolerance', 0.005) # 位置制約球の半径[m]
        self.declare_parameter('orientation_tolerance', 0.0)  # 0: 姿勢制約なし, >0: 現在姿勢を保持[rad]
        self.declare_parameter('planning_time', 1.0)
        self.declare_parameter('velocity_scale', 0.2)
        self.declare_parameter('acceleration_scale', 0.2)
        self.declare_parameter('settle_time', 0.7)          # 動作完了後、この秒数以降に撮られた差分を使う
        self.declare_parameter('fail_cooldown', 1.0)
        self.declare_parameter('start_enabled', False)

        p = self.get_parameter
        self.base_frame = p('base_frame').value
        self.ee_link = p('ee_link').value
        self.camera_frame = p('camera_frame').value
        self.group_name = p('group_name').value
        self.gain = float(p('gain_m_per_px').value)
        self.deadband = float(p('deadband_px').value)
        self.max_step = float(p('max_step').value)
        self.max_total = float(p('max_total_offset').value)
        self.pos_tol = float(p('position_tolerance').value)
        self.ori_tol = float(p('orientation_tolerance').value)
        self.planning_time = float(p('planning_time').value)
        self.vel_scale = float(p('velocity_scale').value)
        self.acc_scale = float(p('acceleration_scale').value)
        self.settle = float(p('settle_time').value)
        self.fail_cooldown = float(p('fail_cooldown').value)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.client = ActionClient(self, MoveGroup, p('move_action').value)

        self.latest = None            # 最新の PointStamped
        self.last_used_stamp = None   # 使用済みの差分(二重実行防止)
        self.busy = False
        self.ready_after = self.get_clock().now()   # この時刻以降のstampの差分のみ有効
        self.anchor = None
        self.enabled = False

        self.create_subscription(PointStamped, p('diff_topic').value, self.diff_cb, 1)
        self.create_service(SetBool, '~/enable', self.enable_cb)
        self.create_timer(0.1, self.tick)

        if p('start_enabled').value:
            self.set_enabled(True)
        self.get_logger().info(
            'follow_target ready (enabled={}). 有効化: ros2 service call '
            '/follow_target/enable std_srvs/srv/SetBool "{{data: true}}"'.format(self.enabled))

    # ---------- enable ----------
    def enable_cb(self, req, res):
        res.success = self.set_enabled(req.data)
        res.message = 'enabled' if self.enabled else 'disabled'
        return res

    def set_enabled(self, flag):
        if not flag:
            self.enabled = False
            return True
        ee = self.lookup(self.ee_link)
        if ee is None:
            self.get_logger().error('enable失敗: {}->{} のTFが取れない'.format(
                self.base_frame, self.ee_link))
            return False
        t = ee.transform.translation
        self.anchor = (t.x, t.y, t.z)
        self.latest = None
        self.ready_after = self.get_clock().now()
        self.enabled = True
        return True

    # ---------- callbacks ----------
    def diff_cb(self, msg):
        self.latest = msg

    def lookup(self, frame):
        try:
            return self.tf_buffer.lookup_transform(
                self.base_frame, frame, Time(), timeout=Duration(seconds=0.2))
        except TransformException as ex:
            self.get_logger().warn('TF {}->{}: {}'.format(self.base_frame, frame, ex),
                                   throttle_duration_sec=2.0)
            return None

    def tick(self):
        if not self.enabled or self.busy or self.latest is None:
            return
        msg = self.latest
        stamp = Time.from_msg(msg.header.stamp)
        if stamp.nanoseconds == 0:
            stamp = self.get_clock().now()   # stampが無いソース用
        elif self.last_used_stamp is not None and stamp <= self.last_used_stamp:
            return
        if stamp < self.ready_after:
            return   # 動作中/動作前に撮られた古い差分

        step = compute_step(msg.point.x, self.gain, self.deadband, self.max_step)
        self.last_used_stamp = stamp
        if step == 0.0:
            return

        cam = self.lookup(self.camera_frame)
        ee = self.lookup(self.ee_link)
        if cam is None or ee is None:
            return
        ax = quat_x_axis(cam.transform.rotation)
        ep = ee.transform.translation
        target = (ep.x + step * ax[0], ep.y + step * ax[1], ep.z + step * ax[2])

        if self.anchor is not None and math.dist(target, self.anchor) > self.max_total:
            self.get_logger().warn('起点から{:.2f}m超のため停止(max_total_offset)。'
                                   '向きが逆なら gain_m_per_px の符号を反転'.format(self.max_total),
                                   throttle_duration_sec=2.0)
            return

        self.get_logger().info('diff={:+.0f}px -> step={:+.3f}m along cam_x=({:.2f},{:.2f},{:.2f})'
                               .format(msg.point.x, step, *ax))
        self.send_goal(target, ee.transform.rotation)

    # ---------- MoveIt ----------
    def send_goal(self, xyz, cur_quat):
        if not self.client.server_is_ready():
            self.get_logger().warn('MoveGroup action server not available',
                                   throttle_duration_sec=2.0)
            return

        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = xyz
        pose.orientation.w = 1.0   # 球の姿勢(意味なし)

        sphere = SolidPrimitive(type=SolidPrimitive.SPHERE, dimensions=[self.pos_tol])
        bv = BoundingVolume()
        bv.primitives.append(sphere)
        bv.primitive_poses.append(pose)
        pc = PositionConstraint()
        pc.header.frame_id = self.base_frame
        pc.link_name = self.ee_link
        pc.constraint_region = bv
        pc.weight = 1.0
        cons = Constraints()
        cons.position_constraints.append(pc)

        if self.ori_tol > 0.0:
            oc = OrientationConstraint()
            oc.header.frame_id = self.base_frame
            oc.link_name = self.ee_link
            oc.orientation = cur_quat
            oc.absolute_x_axis_tolerance = self.ori_tol
            oc.absolute_y_axis_tolerance = self.ori_tol
            oc.absolute_z_axis_tolerance = self.ori_tol
            oc.weight = 1.0
            cons.orientation_constraints.append(oc)

        goal = MoveGroup.Goal()
        r = goal.request
        r.group_name = self.group_name
        r.allowed_planning_time = self.planning_time
        r.num_planning_attempts = 3
        r.max_velocity_scaling_factor = self.vel_scale
        r.max_acceleration_scaling_factor = self.acc_scale
        r.start_state.is_diff = True
        r.goal_constraints.append(cons)
        goal.planning_options.plan_only = False

        self.busy = True
        self.client.send_goal_async(goal).add_done_callback(self.goal_response_cb)

    def goal_response_cb(self, future):
        handle = future.result()
        if not handle.accepted:
            self.get_logger().error('MoveGroup goal rejected')
            self.finish(False)
            return
        handle.get_result_async().add_done_callback(self.result_cb)

    def result_cb(self, future):
        code = future.result().result.error_code.val
        ok = code == MoveItErrorCodes.SUCCESS
        if not ok:
            self.get_logger().warn('MoveGroup failed: error_code={}'.format(code))
        self.finish(ok)

    def finish(self, ok):
        wait = self.settle if ok else self.settle + self.fail_cooldown
        self.ready_after = self.get_clock().now() + Duration(seconds=wait)
        self.busy = False


def main(args=None):
    rclpy.init(args=args)
    node = MoveItFollowTarget()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
