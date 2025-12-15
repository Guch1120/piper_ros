#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
from flexbe_core import EventState, Logger
from piper_sdk import *


# --- 修正箇所: ここから ---
# ROS 2のパス解決に失敗する場合への対策
# このファイルがあるフォルダをシステムの検索パスに強制追加し、
# 隣にある 'piper_driver.py' を確実に見つけられるようにします。
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from piper_driver import PiperGlobalDriver
except ImportError as e:
    Logger.logerr(f"Critical: Still cannot import PiperGlobalDriver: {e}")
    # 安全のため、NameErrorを防ぐダミークラス定義（エラーログ用）
    class PiperGlobalDriver:
        @staticmethod
        def get_instance(port): return None
# --- 修正箇所: ここまで ---

class PiperOpenState(EventState):
    '''
    Piperのグリッパを指定した幅まで「開く」ステート。

    -- target_width  float   開く目標の幅 [mm] (デフォルト: 100.0)
    -- can_port      string  CANポート名 (デフォルト: 'can0')

    <= done          動作コマンド送信完了
    <= failed        接続または送信失敗
    '''

    def __init__(self, target_width=100.0, can_port="can0"):
        super().__init__(outcomes=['done', 'failed'])
        self._target_width = target_width
        self._can_port = can_port
        self._piper = None

    def on_enter(self, userdata):
        # ドライバ取得
        self._piper = PiperGlobalDriver.get_instance(self._can_port)

        if self._piper is None:
            Logger.logerr('Piper instance is None. Check connection or Import.')
            return

        # 幅制限 (0~100mm)
        safe_width = max(0.0, min(self._target_width, 100.0))
        target_um = int(safe_width * 1000)

        try:
            Logger.loginfo(f'Opening Gripper to {safe_width} mm ({target_um} um)')
            # GripperCtrl(width_um, speed, force, status)
            self._piper.GripperCtrl(abs(target_um), 1000, 0x03, 0)
        except Exception as e:
            Logger.logerr(f'Failed to send command: {e}')
            self._piper = None 

    def execute(self, userdata):
        if self._piper is None:
            return 'failed'
        
        # 簡易待機
        time.sleep(0.1)
        return 'done'