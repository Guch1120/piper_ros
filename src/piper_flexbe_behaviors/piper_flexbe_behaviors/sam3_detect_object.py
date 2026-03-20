#!/usr/bin/env python3
import time
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher, ProxySubscriberCached
from std_msgs.msg import String
from geometry_msgs.msg import Point, PoseArray

class DetectObjectWithSAM3State(EventState):
    """
    /sam3/request に物体名を投げ、/sam3/result_points から点群を受け取るState
    
    -- object_name      string  検出対象のテキストプロンプト
    
    #> pose_array       PoseArray  検出された点群データ(u, v, z)のリスト
    """

    def __init__(self, object_name):
        super(DetectObjectWithSAM3State, self).__init__(
            outcomes=['succeeded', 'failed', 'timeout'],
            output_keys=['pose_array'] # 変更: 単一点ではなく配列を出力
        )
        self.object_name = str(object_name) 
        
        self._topic_req = '/sam3/request'
        self._topic_res_legacy = '/sam3/result'      # 失敗判定用(z<0チェック)
        self._topic_res_points = '/sam3/result_points' # データ取得用
        
        self._pub = ProxyPublisher({self._topic_req: String})
        
        # 2つのトピックをキャッシュ付きで購読
        self._sub = ProxySubscriberCached({
            self._topic_res_legacy: Point,
            self._topic_res_points: PoseArray
        })
        
        self._timeout_sec = 10.0
        self._start_time = 0.0

    def on_enter(self, userdata):
        Logger.loginfo(f'[SAM3 State] Requesting: {self.object_name}')
        
        # --- 前回実行時の古いメッセージを削除 ---
        if self._sub.has_msg(self._topic_res_legacy):
            self._sub.remove_last_msg(self._topic_res_legacy)
        if self._sub.has_msg(self._topic_res_points):
            self._sub.remove_last_msg(self._topic_res_points)
        Logger.loginfo('[SAM3 State] Cleared old messages from cache.')
        # ----------------------------------------
        
        Logger.loginfo(f'[SAM3 State] Waiting for response... (timeout: {self._timeout_sec} sec)')
        
        # リクエスト送信
        msg = String()
        msg.data = self.object_name
        self._pub.publish(self._topic_req, msg)
        
        self._start_time = time.time()

    def execute(self, userdata):
        elapsed = time.time() - self._start_time
        
        # 1. タイムアウト判定
        if elapsed > self._timeout_sec:
            Logger.logwarn('[SAM3 State] Timeout!')
            return 'timeout'

        # 2. 失敗判定 (Legacy Pointトピックの z < 0 を監視)
        # SAM3ノードは検出失敗時に Point(0,0,-1) を即座に出す仕様のため
        if self._sub.has_msg(self._topic_res_legacy):
            res = self._sub.get_last_msg(self._topic_res_legacy)
            if res.z < 0.0:
                Logger.logwarn('[SAM3 State] Node reported: Nothing detected.')
                return 'failed'

        # 3. 成功判定 (PoseArrayトピックの受信)
        if self._sub.has_msg(self._topic_res_points):
            pose_array_msg = self._sub.get_last_msg(self._topic_res_points)
            
            # 空配列チェック (念のため)
            if len(pose_array_msg.poses) == 0:
                Logger.logwarn('[SAM3 State] Received empty point list.')
                return 'failed'
            
            userdata.pose_array = pose_array_msg
            Logger.loginfo(f'[SAM3 State] Received {len(pose_array_msg.poses)} points.')
            return 'succeeded'
            
        return None # 待機継続

    def on_exit(self, userdata):
        pass