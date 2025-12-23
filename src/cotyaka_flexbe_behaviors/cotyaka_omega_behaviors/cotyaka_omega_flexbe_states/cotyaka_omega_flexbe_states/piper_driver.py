#!/usr/bin/env python3
# -*-coding:utf8-*-
import time
from flexbe_core import Logger

# piper_sdkパッケージは src/piper_sdk にあるため、
# ワークスペースがsourceされていればimport可能です
try:
    from piper_sdk import C_PiperInterface_V2
except ImportError:
    Logger.logerr("Failed to import piper_sdk. Make sure 'piper_sdk' package is built and sourced.")
    # テスト用のダミークラス（SDKがない環境でのエラー回避用）
    class C_PiperInterface_V2:
        def __init__(self, port): pass
        def ConnectPort(self): pass
        def EnablePiper(self): return False

class PiperGlobalDriver:
    """
    複数のステートでPiperへの接続を共有するためのシングルトンクラス。
    """
    _instance = None

    @classmethod
    def get_instance(cls, can_port="can0"):
        # すでに接続済みならそのインスタンスを返す
        if cls._instance is not None:
            return cls._instance

        # 新規接続
        Logger.loginfo(f"Connecting to Piper via {can_port}...")
        try:
            instance = C_PiperInterface_V2(can_port)
            instance.ConnectPort()
            
            # Enable待機ループ
            retry_count = 0
            while not instance.EnablePiper():
                time.sleep(0.01)
                retry_count += 1
                if retry_count > 500: # 5秒タイムアウト
                    Logger.logerr("Timeout: Failed to enable Piper.")
                    return None
            
            cls._instance = instance
            Logger.loginfo("Piper connected and enabled.")
            return cls._instance

        except Exception as e:
            Logger.logerr(f"Exception connecting to Piper: {e}")
            return None