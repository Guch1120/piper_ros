#!/usr/bin/env python3
import time  # 追加: 時刻取得用
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher, ProxySubscriberCached
from std_msgs.msg import String
from geometry_msgs.msg import Point

class DetectObjectWithSAM3State(EventState):
    """
    /sam3/request に物体名を投げ、/sam3/result から座標を受け取るState
    """

    def __init__(self, object_name):
        super(DetectObjectWithSAM3State, self).__init__(
            outcomes=['succeeded', 'failed', 'timeout'],
            output_keys=['u', 'v', 'z']
        )
        # UI入力ミス防止のための文字変換
        self.object_name = str(object_name) 
        
        self._topic_req = '/sam3/request'
        self._topic_res = '/sam3/result'
        
        self._pub = ProxyPublisher({self._topic_req: String})
        self._sub = ProxySubscriberCached({self._topic_res: Point})
        
        self._timeout_sec = 10.0
        self._start_time = 0.0

    def on_enter(self, userdata):
        Logger.loginfo(f'[SAM3 State] Requesting: {self.object_name}')
        Logger.loginfo(f'[SAM3 State] Waiting for response... (timeout: {self._timeout_sec} sec)')
        
        # リクエスト送信
        msg = String()
        msg.data = self.object_name
        self._pub.publish(self._topic_req, msg)
        
        # 修正: 標準のtimeを使用
        self._start_time = time.time()

    def execute(self, userdata):
        # 修正: 標準のtimeを使用
        elapsed = time.time() - self._start_time
        
        # タイムアウト判定
        if elapsed > self._timeout_sec:
            Logger.logwarn('[SAM3 State] Timeout!')
            return 'timeout'

        # 結果受信確認
        if self._sub.has_msg(self._topic_res):
            res = self._sub.get_last_msg(self._topic_res)
            
            userdata.u = res.x
            userdata.v = res.y
            userdata.z = res.z
            Logger.loginfo(f'[SAM3 State] Received: u={res.x:.2f}, v={res.y:.2f}, z={res.z:.3f}')
            return 'succeeded'
            
        return None # 待機継続

    def on_exit(self, userdata):
        pass