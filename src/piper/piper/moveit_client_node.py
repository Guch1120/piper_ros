import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint

class MoveArmClient(Node):
    def __init__(self):
        super().__init__('move_arm_client')
        # 1. アクションクライアントの作成
        self._action_client = ActionClient(self, MoveGroup, 'move_action')

    def send_goal(self, joint_angles):
        # サーバーが見つかるまで待機
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('MoveGroup action server not available!')
            return

        # 2. ゴールメッセージの作成
        goal_msg = MoveGroup.Goal()
        
        # 【修正点1】SRDFの <group name="arm"> に合わせる
        goal_msg.request.group_name = 'arm' 
        
        goal_msg.request.allowed_planning_time = 5.0
        
        # 制約（関節を何度にするか）の設定
        constraints = Constraints()
        for name, angle in joint_angles.items():
            jc = JointConstraint()
            jc.joint_name = name
            jc.position = angle
            jc.tolerance_above = 0.01
            jc.tolerance_below = 0.01
            jc.weight = 1.0
            constraints.joint_constraints.append(jc)
            
        goal_msg.request.goal_constraints.append(constraints)

        # 3. 送信！
        self.get_logger().info('Sending goal...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().info('Goal rejected :(')
            return

        self.get_logger().info('Goal accepted! Moving...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        self.get_logger().info(f'Result code: {result.error_code.val}')
        # 成功ならエラーコードは 1 (SUCCESS) になるはずだよ
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    client = MoveArmClient()
    
    # 【修正点2】Piperの関節名（joint1 ~ joint6）と目標角度(radian)を指定
    # SRDFの <group_state name="zero"> とかを参考に安全な角度を入れておくね
    target_joints = {
        'joint1': 0.0,
        'joint2': 0.0,
        'joint3': 0.0,
        'joint4': 0.0,
        'joint5': 0.0,
        'joint6': 0.0
    }
    
    # 少し動かしたいなら、例えば joint1 (根本) を 0.5 rad くらい回してみるとか
    # target_joints['joint1'] = 0.5 
    
    client.send_goal(target_joints)
    rclpy.spin(client)

if __name__ == '__main__':
    main()