#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import select
import termios
import tty
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class WaitEnterAndPubMsgNode(Node):
    """
    Enterキーで指定コマンドをpublishし、qキーで終了するROS 2ノード。

    Gemma4 VLM用途では、command_topic=/gemma4_vlm/request,
    record_command=record としておくと、Enterキーでプロンプトファイル入力の推論を開始できる。
    """

    def __init__(self):
        super().__init__('gemma4_vlm_enter_trigger')
        self.declare_parameter('command_topic', '/gemma4_vlm/request')
        self.declare_parameter('record_command', 'record')
        self.declare_parameter('done_command', 'done')
        self.declare_parameter('publish_done_on_quit', False)

        self._command_topic = self.get_parameter('command_topic').value
        self._record_command = self.get_parameter('record_command').value
        self._done_command = self.get_parameter('done_command').value
        self._publish_done_on_quit = self.get_parameter('publish_done_on_quit').value
        self._pub = self.create_publisher(String, self._command_topic, 10)
        self._old_terminal_settings = None
        self._running = True

        self.get_logger().info('Publish command to topic: {}'.format(self._command_topic))
        self.get_logger().info('Press Enter to publish "{}". Press q to quit{}.'.format(
            self._record_command,
            ' and publish "{}"'.format(self._done_command) if self._publish_done_on_quit else ''
        ))
        time.sleep(0.5)

    def setup_terminal(self):
        if not sys.stdin.isatty():
            self.get_logger().warning('stdin is not a TTY. Keyboard input may not work.')
            return False
        self._old_terminal_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return True

    def restore_terminal(self):
        if self._old_terminal_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_terminal_settings)
            self._old_terminal_settings = None

    def publish_command(self, command):
        msg = String()
        msg.data = command
        self._pub.publish(msg)
        self.get_logger().info('Published "{}" to {}'.format(command, self._command_topic))

    def spin_keyboard(self):
        terminal_ok = self.setup_terminal()
        if not terminal_ok:
            self.get_logger().error('This node requires an interactive terminal.')
            return

        try:
            while rclpy.ok() and self._running:
                rclpy.spin_once(self, timeout_sec=0.0)
                readable, _, _ = select.select([sys.stdin], [], [], 0.0)
                if readable:
                    key = sys.stdin.read(1)
                    if key in ['\n', '\r']:
                        self.publish_command(self._record_command)
                    elif key == 'q':
                        if self._publish_done_on_quit:
                            self.publish_command(self._done_command)
                        self.get_logger().info('Quit.')
                        self._running = False
                    elif key == '\x03':
                        self.get_logger().info('Interrupted by Ctrl+C.')
                        self._running = False
                time.sleep(0.05)
        finally:
            self.restore_terminal()


def main(args=None):
    rclpy.init(args=args)
    node = WaitEnterAndPubMsgNode()
    try:
        node.spin_keyboard()
    except KeyboardInterrupt:
        node.get_logger().info('KeyboardInterrupt.')
    finally:
        node.restore_terminal()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
