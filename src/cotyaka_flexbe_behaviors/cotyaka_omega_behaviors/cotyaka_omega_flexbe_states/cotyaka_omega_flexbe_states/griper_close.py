#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
from flexbe_core import EventState, Logger

# --- インポートパス対策 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from piper_driver import PiperGlobalDriver
    # 接続確認をスキップするためにSDKを直接インポート
    from piper_sdk import C_PiperInterface_V2
except ImportError as e:
    Logger.logerr(f"Critical: Import failed in CloseState: {e}")
    # ダミー定義
    class PiperGlobalDriver:
        _instance = None
    class C_PiperInterface_V2:
        def __init__(self, p): pass
        def ConnectPort(self): pass
        def EnablePiper(self): pass
        def GripperCtrl(self, a, b, c, d): pass

class PiperCloseState(EventState):
    '''
    Piperのグリッパを指定した幅まで「閉じる」ステート。
    **修正版: Enable完了確認を行わず、強制的にコマンドを送信します。**

    -- target_width  float   閉じる目標の幅 [mm] (デフォルト: 0.0)
    -- can_port      string  CANポート名 (デフォルト: 'can0')

    <= done          動作コマンド送信完了
    <= failed        接続または送信失敗
    '''

    def __init__(self, target_width=0.0, can_port="can0"):
        super().__init__(outcomes=['done', 'failed'])
        self._target_width = target_width
        self._can_port = can_port
        self._piper = None

    def on_enter(self, userdata):
        # --- 修正箇所: 接続確認ループの削除 ---
        
        # 1. 既に誰かが接続済みならそれを使う
        if PiperGlobalDriver._instance is not None:
            self._piper = PiperGlobalDriver._instance
        else:
            # 2. まだ接続がない場合、確認ループ(while)なしで強制接続する
            Logger.loginfo("Force connecting to Piper (Skipping Enable Check)...")
            try:
                self._piper = C_PiperInterface_V2(self._can_port)
                self._piper.ConnectPort()
                
                # Enableコマンドを1回だけ送る（結果を待たない）
                self._piper.EnablePiper()
                
                # シングルトンに登録しておく
                PiperGlobalDriver._instance = self._piper
                Logger.loginfo("Piper initialized (No Wait Mode).")
            except Exception as e:
                Logger.logerr(f"Exception during force connect: {e}")
                self._piper = None
                return

        if self._piper is None:
            Logger.logerr('Piper instance is None.')
            return

        # 幅制限 (0~100mm)
        safe_width = max(0.0, min(self._target_width, 100.0))
        target_um = int(safe_width * 1000)

        try:
            Logger.loginfo(f'Closing Gripper to {safe_width} mm ({target_um} um)')
            # コマンド送信
            self._piper.GripperCtrl(abs(target_um), 1000, 0x03, 0)
        except Exception as e:
            Logger.logerr(f'Failed to send command: {e}')
            self._piper = None

    def execute(self, userdata):
        if self._piper is None:
            return 'failed'
        
        time.sleep(0.1)
        return 'done'