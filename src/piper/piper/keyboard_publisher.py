#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import sys
import termios
import tty
import select

msg = """
Visual Servo Debugger (Keyboard)
--------------------------------
      [W] Forward (+X)
       ^
       |
[A] Left <---+---> [D] Right (-Y)
  (+Y)     |
           v
      [S] Backward (-X)

[R] Reset Offset
--------------------------------
CTRL-C to quit
"""

class KeyPublisher(Node):
    def __init__(self):
        super().__init__('keyboard_debug_publisher')
        self.pub = self.create_publisher(String, '/debug/keyboard_cmd', 10)
        self.settings = termios.tcgetattr(sys.stdin)

    def getKey(self):
        tty.setraw(sys.stdin.fileno())
        select.select([sys.stdin], [], [], 0)
        key = sys.stdin.read(1)
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)
        return key

    def run(self):
        print(msg)
        try:
            while rclpy.ok():
                key = self.getKey()
                if key == '\x03': # Ctrl-C
                    break
                
                if key in ['w', 'a', 's', 'd', 'r', 'W', 'A', 'S', 'D', 'R']:
                    m = String()
                    m.data = key.lower()
                    self.pub.publish(m)
                    print(f"Sent: {key}")
        except Exception as e:
            print(e)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.settings)

def main(args=None):
    rclpy.init(args=args)
    node = KeyPublisher()
    node.run()
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
