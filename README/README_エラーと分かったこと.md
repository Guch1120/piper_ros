readmeの中国語と英語の違いは，3.2と3.3章の有無． \
3.2章は爪ありと爪なしの詳細説明が英語版にはない． \
3.3性は英語版にそもそも存在しない．

実行コマンド
```
ros2 launch piper start_single_piper.launch.py
```
エラー
```
root@robo25-Alienware-m15-R3:/workspace/ros2_ws# ros2 launch piper start_single_piper.launch.py
[INFO] [launch]: All log files can be found below /root/.ros/log/2025-11-07-21-42-33-424098-robo25-Alienware-m15-R3-94
[INFO] [launch]: Default logging verbosity is set to INFO
[INFO] [piper_single_ctrl-1]: process started with pid [95]
[piper_single_ctrl-1] [INFO] [1762519353.698281132] [piper_ctrl_single_node]: can_port is can0
[piper_single_ctrl-1] [INFO] [1762519353.698646117] [piper_ctrl_single_node]: auto_enable is True
[piper_single_ctrl-1] [INFO] [1762519353.699120544] [piper_ctrl_single_node]: gripper_exist is True
[piper_single_ctrl-1] [INFO] [1762519353.699478228] [piper_ctrl_single_node]: gripper_val_mutiple is 1
[piper_single_ctrl-1] [INFO] [1762519353.713801301] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762519353.715043997] [piper_ctrl_single_node]: Enable status:False
[piper_single_ctrl-1] [INFO] [1762519353.715825661] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762519354.717496902] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762519354.717920250] [piper_ctrl_single_node]: Enable status:True
[piper_single_ctrl-1] [INFO] [1762519354.718489894] [piper_ctrl_single_node]: --------------------
[piper_single_ctrl-1] [INFO] [1762520044.000938158] [piper_ctrl_single_node]: Received enable flag:
[piper_single_ctrl-1] [INFO] [1762520044.001268966] [piper_ctrl_single_node]: enable_flag: False
[piper_single_ctrl-1] [INFO] [1762520062.390508145] [piper_ctrl_single_node]: Received enable flag:
[piper_single_ctrl-1] [INFO] [1762520062.391034929] [piper_ctrl_single_node]: enable_flag: True
[piper_single_ctrl-1] [INFO] [1762520073.624658958] [piper_ctrl_single_node]: Received enable flag:
[piper_single_ctrl-1] [INFO] [1762520073.625101347] [piper_ctrl_single_node]: enable_flag: False

```
状況 ```ros2 topic echo /arm_status```によると
```
---
ctrl_mode: 0
arm_status: 0
mode_feedback: 0
teach_status: 0
motion_status: 0
trajectory_num: 0
err_code: 0
joint_1_angle_limit: false
joint_2_angle_limit: false
joint_3_angle_limit: false
joint_4_angle_limit: false
joint_5_angle_limit: false
joint_6_angle_limit: false
communication_status_joint_1: false
communication_status_joint_2: false
communication_status_joint_3: false
communication_status_joint_4: false
communication_status_joint_5: false
communication_status_joint_6: false
---
```
内容は以下の通り，つまりfalseがデフォルトということ．
```
uint8 ctrl_mode
    0x00  待機状態
    0x01  CANコマンド制御モード
    0x02  教標モード
    0x03  Ethernet制御モード
    0x04  wifi制御モード
    0x05  リモコン制御モード
    0x06  連結教標モード
    0x07  オフライン軌跡モード4 
uint8 arm_status
    0x00 ノーマル
    0x01 緊急停止
    0x02 解なし
    0x03 シグナル
    0x04 ターゲット角度超過
    0x05 ジョイント通信エラー
    0x06 Joint brake not released    <-----?????
    0x07 ロボットアームが衝突を検知
    0x08 ドラッグティーチングで速度超過
    0x09 ジョイントステータス異常
    0x0A その他の異常
    0x0B 教示再生
    0x0C 教示実行
    0x0D 教示一時停止
    0x0E メイン制御NTC熱源
    0x0F 放電抵抗NTC熱源
uint8 mode_feedback
    0x00 MOVE P (ポイント・トゥ・ポイント移動)
    0x01 MOVE J (関節空間移動)
    0x02 MOVE L (直線移動)
    0x03 MOVE C (円弧移動)
uint8 teach_status
    0x00 閉じる
    0x01 ティーチング記録開始（ドラッグティーチングモードに入る）
    0x02 ティーチング記録終了（ドラッグティーチングモードを終了する）
    0x03 ティーチング軌道を実行（ドラッグティーチング軌道を再現）
    0x04 一時停止
    0x05 再開（軌道再現を継続）
    0x06 実行を終了
    0x07 軌道の開始点へ移動
uint8 motion_status
    0x00 指定点に到達
    0x01 指定点に未到達
uint8 trajectory_num
    0~255 (Feedback in offline trajectory mode)
bool joint_1_angle_limit// Joint 1 communication error (0: Normal, 1: Error)
bool joint_2_angle_limit// Joint 2 communication error (0: Normal, 1: Error)
bool joint_3_angle_limit// Joint 3 communication error (0: Normal, 1: Error)
bool joint_4_angle_limit// Joint 4 communication error (0: Normal, 1: Error)
bool joint_5_angle_limit// Joint 5 communication error (0: Normal, 1: Error)
bool joint_6_angle_limit// Joint 6 communication error (0: Normal, 1: Error)
bool communication_status_joint_1// Joint 1 angle exceeds limit (0: Normal, 1: Error)
bool communication_status_joint_2// Joint 2 angle exceeds limit (0: Normal, 1: Error)
bool communication_status_joint_3// Joint 3 angle exceeds limit (0: Normal, 1: Error)
bool communication_status_joint_4// Joint 4 angle exceeds limit (0: Normal, 1: Error)
bool communication_status_joint_5// Joint 5 angle exceeds limit (0: Normal, 1: Error)
bool communication_status_joint_6// Joint 6 angle exceeds limit (0: Normal, 1: Error)
```
piper_single_ctrlノードのパラメータ
```
can_port:開放するCANポートの名前
auto_enable:自動有効化するか．Trueのときプログラム起動時に自動有効化される．
# 注意：この設定をFalseにすると、割り込み処理後にノードを再起動しても、ロボットアームは前回起動時の状態を維持する
# 前回の起動時にロボットアームが有効状態だった場合、プログラム中断後にノードを再起動しても有効状態を維持
# 前回の起動時にロボットアームが無効状態だった場合、プログラム中断後にノードを再起動しても無効状態を維持
gripper_exist:グリッパーの有無．Trueは有るときでグリッパー制御が有効になる．
rviz_ctrl_flag:rvizで関節角を送信するか．Trueでrvizからの関節角メッセージを受信する．
gripper_val_mutiple:グリッパー制御倍率の設定
# RVizのjoint7範囲は[0,0.04]であるのに対し、実際のグリッパーストロークは0.08mであるため、RVizで実際のグリッパーを制御するにはグリッパー倍率を2倍に設定する必要がある
```


piper_interface_v2.py参照.motionctrl関数の中身
```
    def MotionCtrl_1(self, 
                    emergency_stop: Literal[0x00, 0x01, 0x02] = 0, 
                    track_ctrl: Literal[0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08] = 0, 
                    grag_teach_ctrl: Literal[0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07] = 0):
        '''
        ロボットアーム運動制御指令1        
        CAN ID:
            0x150
        
        Args:
            emergency_stop: 緊急停止 uint8 
                0x00 無効
                0x01 緊急停止
                0x02 復旧
            track_ctrl: 軌道指令 uint8 
                0x00 オフ
                0x01 現在の計画を一時停止 
                0x02 現在の軌道を継続
                0x03 現在の軌道をクリア 
                0x04 全軌道をクリア 
                0x05 現在の計画軌道を取得 
                0x06 実行を終了 
                0x07 軌跡転送
                0x08 軌跡転送終了
            grag_teach_ctrl: ドラッグティーチング指令 uint8 
                0x00 オフ
                0x01 ティーチング記録開始（ドラッグティーチングモード進入）
                0x02 ティーチング記録終了（ドラッグティーチングモード終了） 
                0x03 ティーチング軌跡実行（ドラッグティーチング軌跡再現） 
                0x04 実行一時停止 
                0x05 実行継続（軌跡再現継続） 
                0x06 実行終了 
                0x07 軌跡起点へ移動        '''
        '''
        ロボットアーム動作制御コマンド（0x150）を送信します。
        
        引数:
            emergency_stop (int): 緊急停止コマンド。
                0x00: 無効
                0x01: 緊急停止
                0x02: 再開
            track_ctrl (int): 軌道制御コマンド。
                0x00: 無効化
                0x01: 現在の計画を一時停止
                0x02: 現在の軌跡を継続
                0x03: 現在の軌跡をクリア
                0x04: 全軌跡をクリア
                0x05: 現在の計画軌跡を取得
                0x06: 実行を終了
                0x07: 軌跡送信
                0x08: 軌道送信終了
            grag_teach_ctrl (int): ティーチモード制御コマンド。
                0x00: 無効化
                0x01: ティーチ記録開始 (ティーチモード進入)
                0x02: ティーチ記録終了 (ティーチモード退出)
                0x03: ティーチ済み軌道実行 (ティーチモード軌道の再生)
                0x04: 実行一時停止
                0x05: 実行継続 (軌道再生再開)
                0x06: 実行終了
                0x07: 軌道開始点へ移動
        tx_can = Message()
        motion_ctrl_1 = ArmMsgMotionCtrl_1(emergency_stop, track_ctrl, grag_teach_ctrl)
        msg = PiperMessage(type_=ArmMsgType.PiperMsgMotionCtrl_1, arm_motion_ctrl_1=motion_ctrl_1)
        self.__parser.EncodeMessage(msg, tx_can)
        feedback = self.__arm_can.SendCanMessage(tx_can.arbitration_id, tx_can.data)
        if feedback is not self.__arm_can.CAN_STATUS.SEND_MESSAGE_SUCCESS:
            self.logger.error("0x150 send failed: SendCanMessage(%s)", feedback)

```

モータidの割当はpiper_sdk/piper_msgs/msg_v2/can_id.py
sdk内部とidのメッセージタイプはpiper_sdk/piper_msgs/msg_v2/arm_id_type_map.pyで決まっている．



### rosdep install -i --from-path src --rosdistro humble -y
executing command [apt-get install -y ros-humble-warehouse-ros-mongo]
Reading package lists... Done
Building dependency tree... Done
Reading state information... Done
E: Unable to locate package ros-humble-warehouse-ros-mongo
ERROR: the following rosdeps failed to install
  apt: command [apt-get install -y ros-humble-warehouse-ros-mongo] failed



deticを追加したあとでCOLCON IGNOREファイルを追加しないとビルド時にバカ程エラー出る \
これはdeticがrosプログラム群でないのにsetup.pyというファイルがあるせいでrosパッケージ群として誤認識されるから． \
対処法はCOLCON_IGNOREファイル(中身は空)を追加してビルド時に無視されるようにすること． \
追加するのは2つ.この2つの下に犯人のsetup.pyがある．\
```
detic/detectron2/COLCON_IGNORE
detic/Detic/third_party/COLCON_IGNORE
```

piperのgazeboを動かすときにjoint8_ctrl.pyに実行権限が必要
```
chmod +x src/piper_sim/piper_gazebo/scripts/joint8_ctrl.py
```

Realsense D435Iのdepth最小距離は0.1m \
近すぎると左右のセンサで三角測量できなくなることが原因． \
