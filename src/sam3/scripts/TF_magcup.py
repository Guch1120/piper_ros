import rclpy
from rclpy.node import Node
from rclpy.duration import Duration
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
import tf2_ros
import tf2_geometry_msgs
from geometry_msgs.msg import TransformStamped, PointStamped, Point
import traceback

class MugTFPublisher(Node):
    """
    画像座標と深度から, マグカップのTF(target_mug)を
    ワールド座標系(map)に生成して配信するノード
    """

    def __init__(self):
        super().__init__('mug_tf_publisher')

        # 並列処理を許可するグループ
        self.callback_group = ReentrantCallbackGroup()

        # TFバッファとリスナー
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.static_broadcaster = tf2_ros.StaticTransformBroadcaster(self)

        # カメラ設定 (1280x720)
        self.fx = 909.4475708007812
        self.fy = 907.5896606445312
        self.cx = 637.9448852539062
        self.cy = 378.9811706542969

        # サブスクライバー
        self.subscription = self.create_subscription(
            Point,
            '/magcup_object_uvz',
            self.topic_callback,
            10,
            callback_group=self.callback_group
        )

        self.get_logger().info('MugTFPublisher Node has been started (Debug Mode).')
        self.get_logger().info('Waiting for /tf_static from static_transform_publisher...')

    def topic_callback(self, msg):
        u = msg.x
        v = msg.y
        depth = msg.z
        
        self.get_logger().info(f'Subscribed topic data : u={u:.2f}, v={v:.2f}, depth={depth:.3f}')
        self.execute_calculation_and_broadcast_TF(u, v, depth)

    # 画像座標(u, v)と深度(depth)からワールド座標系でのTFを計算し, 配信する
    def execute_calculation_and_broadcast_TF(self, u, v, depth, camera_frame='camera_color_optical_frame', target_frame='map'):
        try:
            if depth <= 0.0:
                self.get_logger().warn('Invalid depth received.')
                return False

            # 画像座標 -> カメラ座標系
            x_c = (u - self.cx) * depth / self.fx
            y_c = (v - self.cy) * depth / self.fy
            z_c = depth

            point_camera = PointStamped()
            point_camera.header.frame_id = camera_frame
            # Time(seconds=0) で「最新のTF」を指定
            point_camera.header.stamp = rclpy.time.Time(seconds=0).to_msg()
            point_camera.point.x = x_c
            point_camera.point.y = y_c
            point_camera.point.z = z_c

            self.get_logger().info(f'Camera Coords : [{x_c:.3f}, {y_c:.3f}, {z_c:.3f}]')

            # TF変換の確認
            # タイムアウトを少し長め(2.0秒)にして待ってみる
            if not self.tf_buffer.can_transform(target_frame, camera_frame, rclpy.time.Time(seconds=0), timeout=Duration(seconds=2.0)):
                self.get_logger().error(f'Transform from {camera_frame} to {target_frame} NOT found.')
                
                # デバッグ: 何がバッファに入っているか表示
                self.get_logger().error('--- Current TF Buffer Frames ---')
                self.get_logger().error(self.tf_buffer.all_frames_as_yaml())
                self.get_logger().error('--------------------------------')
                self.get_logger().error('HINT: Make sure "static_transform_publisher" is running in another terminal!')
                return False
            
            # 変換実行
            point_world = self.tf_buffer.transform(point_camera, target_frame)

            self.get_logger().info(f'World Coords : [{point_world.point.x:.3f}, {point_world.point.y:.3f}, {point_world.point.z:.3f}]')

            # TF発行
            t = TransformStamped()
            t.header.stamp = self.get_clock().now().to_msg()
            t.header.frame_id = target_frame
            t.child_frame_id = 'target_mug'
            t.transform.translation.x = point_world.point.x
            t.transform.translation.y = point_world.point.y
            t.transform.translation.z = point_world.point.z
            t.transform.rotation.w = 1.0

            self.static_broadcaster.sendTransform(t)
            self.get_logger().info('Broadcast TF [target_mug] SUCCESS.')
            return True

        except Exception:
            self.get_logger().error('Unexpected error in calculation.')
            self.get_logger().error(traceback.format_exc())
            return False

def main(args=None):
    rclpy.init(args=args)
    node = MugTFPublisher()
    
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()