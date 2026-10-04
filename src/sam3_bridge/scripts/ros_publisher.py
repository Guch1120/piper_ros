#!/usr/bin/env python3
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String


class TestPublisher(Node):
    def __init__(self):
        super().__init__("test_publisher")
        self.declare_parameter("topic_name", "/test/message")
        self.declare_parameter("period", 1.0)
        topic = str(self.get_parameter("topic_name").value)
        period = float(self.get_parameter("period").value)
        self.publisher = self.create_publisher(String, topic, 1)
        self.count = 0
        self.timer = self.create_timer(period, self.publish_message)

    def publish_message(self):
        msg = String(data=f"Hello from ROS 2! count={self.count}")
        self.publisher.publish(msg)
        self.get_logger().info(f"[Publisher] 送信: {msg.data}")
        self.count += 1


def main(args=None):
    rclpy.init(args=args)
    node = TestPublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
