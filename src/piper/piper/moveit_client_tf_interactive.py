#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rcl_interfaces.msg import SetParametersResult
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
import math

class MoveItClientTfInteractive(Node):
    def __init__(self):
        super().__init__('moveit_client_tf_interactive_node')

        # --- 設定: フレーム名（固定） ---
        self.parent_frame = 'base_link'      # 親フレーム名（必要に応じて変更してください）
        self.child_frame = 'interactive_set'   # 子フレーム名（必要に応じて変更してください）

        # --- TFブロードキャスターの初期化 ---
        self.tf_broadcaster = TransformBroadcaster(self)

        # --- パラメータの宣言と初期値設定 ---
        # 起動時にコマンドライン引数で指定可能、なければデフォルト値が使われる
        self.declare_parameter('x', 0.2)
        self.declare_parameter('y', 0.0)
        self.declare_parameter('z', 0.1)
        self.declare_parameter('roll', 0.0)
        self.declare_parameter('pitch', 0.0)
        self.declare_parameter('yaw', 0.0)

        # 現在のパラメータ値を取得して内部変数に保持
        self.update_internal_params()

        # --- パラメータ変更コールバックの設定 ---
        # 外部からパラメータが変更されたときに実行される関数を登録
        self.add_on_set_parameters_callback(self.parameter_callback)

        # --- タイマー設定: 50HzでTFを発行 ---
        self.timer = self.create_timer(0.02, self.broadcast_timer_callback)

        self.get_logger().info(f'Dummy TF Publisher started. Frame: {self.parent_frame} -> {self.child_frame}')

    def update_internal_params(self):
        """パラメータサーバーから現在の値を取得して変数を更新"""
        self.tx = self.get_parameter('x').get_parameter_value().double_value
        self.ty = self.get_parameter('y').get_parameter_value().double_value
        self.tz = self.get_parameter('z').get_parameter_value().double_value
        self.t_roll = self.get_parameter('roll').get_parameter_value().double_value
        self.t_pitch = self.get_parameter('pitch').get_parameter_value().double_value
        self.t_yaw = self.get_parameter('yaw').get_parameter_value().double_value

    def parameter_callback(self, params):
        """パラメータ変更時に呼ばれるコールバック"""
        for param in params:
            if param.name == 'x':
                self.tx = param.value
            elif param.name == 'y':
                self.ty = param.value
            elif param.name == 'z':
                self.tz = param.value
            elif param.name == 'roll':
                self.t_roll = param.value
            elif param.name == 'pitch':
                self.t_pitch = param.value
            elif param.name == 'yaw':
                self.t_yaw = param.value
            
            self.get_logger().info(f'Updated {param.name}: {param.value}')

        return SetParametersResult(successful=True)

    def broadcast_timer_callback(self):
        """定期的にTFを発行する"""
        t = TransformStamped()

        # ヘッダー設定
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self.parent_frame
        t.child_frame_id = self.child_frame

        # 位置設定
        t.transform.translation.x = self.tx
        t.transform.translation.y = self.ty
        t.transform.translation.z = self.tz

        # 姿勢設定 (Euler -> Quaternion)
        qx, qy, qz, qw = self.euler_to_quaternion(self.t_roll, self.t_pitch, self.t_yaw)
        t.transform.rotation.x = qx
        t.transform.rotation.y = qy
        t.transform.rotation.z = qz
        t.transform.rotation.w = qw

        # 発行
        self.tf_broadcaster.sendTransform(t)

    def euler_to_quaternion(self, roll, pitch, yaw):
        """オイラー角(rad)をクォータニオン(x, y, z, w)に変換"""
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)

        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy

        return x, y, z, w

def main(args=None):
    rclpy.init(args=args)
    node = MoveItClientTfInteractive()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()