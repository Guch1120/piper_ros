#!/usr/bin/env python3
# -*-coding:utf8-*-

#piperアームをリセットするノード
import rclpy
from  rclpy.node import Node
from piper_sdk import C_PiperInterface_V2
import time

class PiperCtrlResetNode(Node):
    """
    Piperアームをリセットするノード
    1度起動するとリセットコマンドを送信する
    """
    def __init__(self):
        super().__init__('piper_ctrl_reset_node')
        self.get_logger().info('Wake up ......Piper Reset Node')
        self.piper = None
        
        try:
            self.piper = C_PiperInterface_V2()
            self.get_logger().info('CANポートに接続中...')
            self.piper.ConnectPort()
            time.sleep(0.1)
            # MotionCtrl_1 の docstring によると、0x02 は回復
            self.get_logger().info('リセット（回復）コマンド (0x02) を送信します...')
            self.piper.MotionCtrl_1(0x02, 0, 0)
            self.get_logger().info('リセットコマンドを送信しました。')

        except Exception as e:
            self.get_logger().error(f'処理中にエラーが発生しました: {e}')

def main(args=None):
    rclpy.init(args=args)
    ctrl_reset_node = None
    try:
        ctrl_reset_nodereset_node = PiperCtrlResetNode()
        time.sleep(0.5)
    except KeyboardInterrupt:
        if ctrl_reset_node :
            ctrl_reset_node.get_logger().info('Keyboard Interrupt......')
    except Exception as e:
        if ctrl_reset_node :
            ctrl_reset_node.get