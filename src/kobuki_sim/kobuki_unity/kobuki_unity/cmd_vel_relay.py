#!/usr/bin/env python3
"""Relay geometry_msgs/Twist from nav2's cmd_vel output to the Kobuki
external velocity-command topic ('commands/velocity', matching real
kobuki_node - see kobuki_unity_sim_node.py's module docstring).

nav2_bringup's controller_server publishes on 'cmd_vel' by default; neither
the real kobuki_node nor kobuki_unity_sim_node subscribe to that topic name,
so nav2 cannot drive the robot without this relay (or an equivalent remap).
A plain launch-time topic remap on the controller_server node would also
work, but this explicit relay keeps nav2's own default topic name untouched
and is easy to reason about independently of whichever nav2 launch is used.
"""

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


class CmdVelRelay(Node):

    def __init__(self) -> None:
        super().__init__('kotyaka_cmd_vel_relay')

        self.declare_parameter('input_topic', 'cmd_vel')
        self.declare_parameter('output_topic', 'commands/velocity')
        input_topic = str(self.get_parameter('input_topic').value)
        output_topic = str(self.get_parameter('output_topic').value)

        self.publisher = self.create_publisher(Twist, output_topic, 10)
        self.subscription = self.create_subscription(
            Twist, input_topic, self._relay_callback, 10)

        self.get_logger().info(f'Relaying {input_topic} -> {output_topic}')

    def _relay_callback(self, message: Twist) -> None:
        self.publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CmdVelRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
