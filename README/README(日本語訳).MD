# AgileX ロボットアーム (humble)

[CN](README.MD)

![ubuntu](https://img.shields.io/badge/Ubuntu-22.04-orange.svg)

python_version >= "3.10"

テスト:

|PYTHON |STATE|
|---|---|
|![humble](https://img.shields.io/badge/ros-humble-blue.svg)|![Pass](https://img.shields.io/badge/Pass-blue.svg)|

## 0 URDFバージョンに関する注意

S-V1.6-3 ファームウェアバージョン以前のDHパラメータは、各関節の接触リミットを初期座標として取得されています。

S-V1.6-3 ファームウェアバージョン以降のDHパラメータは、j2（第2関節）とj3（第3関節）の座標系を2度オフセットしています。

現在のデフォルトURDFは後者（新しい方）です。

|ファームウェアバージョン |urdf|
|---|---|
|現在のバージョン < S-V1.6-3|`piper_description_old.urdf`|
|現在のバージョン >= S-V1.6-3|`piper_description.urdf`|

## 1 インストール

### 1.1 依存関係のインストール

```shell
pip3 install python-can
pip3 install scipy
```

```shell
pip3 install piper_sdk
```

```shell
sudo apt install ros-$ROS_DISTRO-ros2-control
sudo apt install ros-$ROS_DISTRO-ros2-controllers
sudo apt install ros-$ROS_DISTRO-controller-manager
```

## 2 CANモジュールの使用

注：ここのCANモジュールは、ロボットアームに内蔵されたCANモジュールのみをサポートしており、他のCANモジュールはサポートしていません。

CANツールのインストール

```bash
sudo apt update && sudo apt install can-utils ethtool
```

これら2つのツールは、CANモジュールの設定に使用されます。

bashスクリプトの実行時に `ip: command not found` と表示される場合は、`sudo apt-get install iproute2` を実行して `ip` コマンドをインストールしてください。

### 2.1 CANモジュールの検索

以下のコマンドを実行します：

```bash
bash find_all_can_port.sh
```

パスワードを入力し、CANモジュールがコンピュータに挿入されて検出されると、以下のように出力されます：

```bash
Both ethtool and can-utils are installed.
Interface can0 is connected to USB port 3-1.4:1.0
```

複数のモジュールがある場合、出力は以下のようになります：

```bash
Both ethtool and can-utils are installed.
Interface can0 is connected to USB port 3-1.4:1.0
Interface can1 is connected to USB port 3-1.1:1.0
```

各CANモジュールに対して、`Interface can1 is connected to USB port 3-1.1:1.0` のような対応する出力が表示されます。

ここで、`can1` はシステムによって検出されたCANモジュールの名前であり、`3-1.1:1.0` はそれが接続されているUSBポートです。

もしCANモジュールが既に `can_piper` などの別の名前でアクティブ化されている場合、出力は以下のようになります：

```bash
Both ethtool and can-utils are installed.
Interface can_piper is connected to USB port 3-1.4:1.0
Interface can0 is connected to USB port 3-1.1:1.0
```

CANモジュールが検出されない場合、以下のみが出力されます：

```bash
Both ethtool and can-utils are installed.
```

### 2.2 単一のCANモジュールの有効化 (`can_activate.sh` スクリプトを使用)

単一のCANモジュールを有効化する状況は2つあります。1つはPCにCANモジュールが1つだけ接続されている場合、もう1つは複数のCANモジュールが挿入されているが、そのうちの1つだけを有効化する場合です。

#### 2.2.1 PCにUSB-to-CANモジュールが1つだけ接続されている場合

単に以下を実行してください：

```bash
bash can_activate.sh can0 1000000
```

ここで、`can0` は任意の名前に置き換えることができます。`1000000` はボーレートであり、変更することはできません。

#### 2.2.2 PCに複数のUSB-to-CANモジュールが接続されているが、一度に1つのモジュールのみを有効化する場合

注：このケースは、ロボットアームと台車の両方を使用する場合に適用されます。

(1) CANモジュールのUSBハードウェアアドレスを見つけます。すべてのCANモジュールを取り外し、ロボットアームに接続されているものだけを差し込んでから、以下を実行します：

```shell
bash find_all_can_port.sh
```

USBポートの値（例：3-1.4:1.0）を記録します。

(2) CANデバイスを有効化します。USBポートの値が 3-1.4:1.0 であると仮定して、以下を実行します：

```bash
bash can_activate.sh can_piper 1000000 "3-1.4:1.0"
```

説明：**3-1.4:1.0 はハードウェアエンコードされたUSBポートであり、そこに挿入されたCANデバイスは `can_piper` という名前に変更され、ボーレート 1000000 で有効化されます。**

(3) `ifconfig` を実行して `can_piper` が表示されるか確認し、有効化が成功したかチェックします。表示されれば、CANモジュールは正常に設定されています。

### 2.3 複数のCANモジュールを同時に有効化する (`can_muti_activate.sh` スクリプトを使用)

まず、PCに挿入されている公式CANモジュールの数を確認します（ここでは2つと仮定します）。

注：**現在のコンピュータに5つのCANモジュールが挿入されている場合、指定されたCANモジュールのみを有効化できます**

#### 2.3.1 各CANモジュールのUSBポートハードウェアアドレスを記録する

各CANモジュールについて、抜き差しを行いながら対応するUSBポートアドレスを記録します。

`can_muti_activate.sh` ファイル内の `EXPECTED_CAN_COUNT` パラメータは、有効化したいCANモジュールの数に設定する必要があります（ここでは2つと仮定）。

(1) 1つのCANモジュールを差し込み、以下を実行します：

```shell
bash find_all_can_port.sh
```

`USB port` の値（例：`3-1.4:1.0`）を記録します。

(2) 次のCANモジュールを差し込みます。**前のものと同じUSBポートに差し込まないように注意**し、以下を実行します：

```shell
bash find_all_can_port.sh
```

2つ目のCANモジュールの `USB port` の値（例：`3-1.1:1.0`）を記録します。

注：**以前に有効化されていない場合、最初のモジュールはデフォルトで "can0" になり、2番目は "can1" になります。以前に有効化されていた場合は、以前使用されていた名前になります。**

#### 2.3.2 USBポート、ターゲットインターフェース名、およびビットレートを事前定義する

記録された `USB port` の値が `3-1.4:1.0` と `3-1.1:1.0` であると仮定します。`USB_PORTS["1-9:1.0"]="can_left:1000000"` の括弧内の値を、`3-1.4:1.0` と `3-1.1:1.0` に置き換えます。

最終的な結果は以下のようになります：

```shell
USB_PORTS["3-1.4:1.0"]="can_left:1000000"
USB_PORTS["3-1.1:1.0"]="can_right:1000000"
```

説明：**3-1.4:1.0 はハードウェアエンコードされたUSBポートであり、そこに挿入されたCANデバイスは "can_left" に名前変更され、ボーレート 1000000 で有効化されます。**

#### 2.3.3 複数のCANモジュールを有効化する

スクリプトを実行します：

```bash
bash can_muti_activate.sh
```

#### 2.3.4 複数のCANモジュールが正常にセットアップされたか確認する

`ifconfig` を実行して、`can_left` と `can_right` が存在するか確認します。

## 3 ノードの起動

```shell
cd piper_ros
colcon build
source install/setup.bash
```

### 3.1 単一ロボットアーム

ノード名: `piper_single_ctrl`

パラメータ (param)

```shell
can_port: オープンするCANルートの名前。

auto_enable: システムを自動的に有効にするかどうか。Trueの場合、プログラム起動時にシステムが自動的に有効になります。
#  有効化状態を手動で制御したい場合は、これをFalseに設定してください。プログラムが中断され再起動された場合、ロボットアームは前回の実行時の状態を維持します。
# アームが有効状態だった場合、再起動後も有効のままです。
# アームが無効状態だった場合、再起動後も無効のままです。

gripper_exist: エンドグリッパがあるかどうか。Trueの場合、エンドグリッパがあることを意味し、グリッパ制御がオンになります。

rviz_ctrl_flag: RVizを使用して関節角度メッセージを送信するかどうか。Trueの場合、システムはrVizによって送信された関節角度メッセージを受信します。

gripper_val_mutiple: グリッパ制御の倍率を設定します。

# RVizのjoint7の範囲は [0, 0.04] ですが、実際のグリッパの移動量は 0.08m であるため、実際のグリッパを正しく制御するには、RVizの値を2倍に設定する必要があります。
```

シングルアームロボットを起動するためのlaunchファイルは2つあります：`start_single_piper_rviz.launch.py` と `start_single_piper.launch.py` です。

前者はRVizを一緒に起動でき、スライダーを動かしてロボットアームを制御できます。

制御ノードを起動します。

```shell
# ノードを起動
ros2 run piper piper_single_ctrl --ros-args -p can_port:=can0 -p auto_enable:=false -p gripper_exist:=true -p gripper_val_mutiple:=2
# launchを起動
ros2 launch piper start_single_piper.launch.py can_port:=can0 auto_enable:=false gripper_exist:=false gripper_val_mutiple:=2
# または、デフォルトパラメータでノードを起動できます
ros2 launch piper start_single_piper.launch.py
# 上記のようにパラメータを調整することで、RVizを使用して制御を有効にすることもできます。
ros2 launch piper start_single_piper_rviz.launch.py
```

`ros2 topic list`

```shell
/arm_status # アームのステータス
/enable_flag # 有効化フラグ。ノードに送信し、trueを送ると有効化される
/end_pose # エンドエフェクタのポーズフィードバック
/joint_states # 関節メッセージを購読し、このメッセージに関節位置を送信してロボットアームの動きを制御する
/joint_states_single # 関節フィードバック
/pos_cmd # エンドエフェクタのポーズ制御
```

ros2 service list

```shell
/enable_srv # サービス側の有効化
```

ロボットアームの有効化

```shell
# サービスコール
ros2 service call /enable_srv piper_msgs/srv/Enable enable_request:\ true\ 
# トピック配信
ros2 topic pub /enable_flag std_msgs/msg/Bool data:\ true\ 
```

ロボットアームの無効化

```shell
# サービスコール
ros2 service call /enable_srv piper_msgs/srv/Enable enable_request:\ false\ 
# トピック配信
ros2 topic pub /enable_flag std_msgs/msg/Bool data:\ false\ 
```

関節メッセージの配信

注：ロボットアームが持ち上がります。動作範囲内に障害物がないことを確認してください。

ロボットアームはデフォルト速度の10%で動き、グリッパのトルクは0.5Nに設定されます。

速度範囲は1から100に制限されています。1未満の値は1として扱われます。

位置は以下の通りです：

```shell
ros2 topic pub /joint_states sensor_msgs/msg/JointState "{header: {stamp: {sec: 0, nanosec: 0}, frame_id: 'piper_single'}, name: ['joint1', 'joint2','joint3','joint4','joint5','joint6','joint7'], position: [0.2,0.2,-0.2,0.3,-0.2,0.5,0.01], velocity: [0,0,0,0,0,0,10], effort: [0,0,0,0,0,0,0.5]}"

```

### 3.2 piper カスタムメッセージ

ros パッケージ `piper_msgs`

 **ロボットアームステータスフィードバックメッセージ**: CANプロトコルの `id=0x2A1` のフィードバックメッセージに対応します。

`PiperStatusMsg.msg`

```c
uint8 ctrl_mode
/*
0x00 スタンバイモード (Standby mode)
0x01 CANコマンド制御モード (CAN command control mode)
0x02 ティーチングモード (Teaching mode)
0x03 Ethernet制御モード (Ethernet control mode)
0x04 wifi制御モード (wifi control mode)
0x05 リモートコントローラ制御モード (Remote controller control mode)
0x06 リンクティーチングモード (Linked teaching mode)
0x07 オフライン軌道モード (Offline track mode)
*/
uint8 arm_status
/*
0x00 正常 (Normal)
0x01 緊急停止 (Emergency stop)
0x02 解なし (No solution)
0x03 特異点 (Singularity)
0x04 目標角度制限超過 (Target angle exceeds limit)
0x05 関節通信エラー (Joint communication error)
0x06 関節ブレーキ未解除 (Joint brake not released)
0x07 ロボットアーム衝突検知 (Robotic arm collision detected)
0x08 ドラッグティーチング中の速度超過 (Overspeed during drag teaching)
0x09 関節ステータス異常 (Joint status abnormal)
0x0A その他の異常 (Other abnormality)
0x0B ティーチング記録 (Teaching record)
0x0C ティーチング実行 (Teaching execution)
0x0D ティーチング一時停止 (Teaching paused)
0x0E メイン制御NTC過熱 (Main control NTC overheating)
0x0F 放電抵抗NTC過熱 (Discharge resistor NTC overheating)
*/
uint8 mode_feedback
/*
0x00 MOVE P
0x01 MOVE J
0x02 MOVE L
0x03 MOVE C
*/
uint8 teach_status
/*
0x00 クローズ (Close)
0x01 ティーチング記録開始（ドラッグティーチングモードに入る）
0x02 ティーチング記録終了（ドラッグティーチングモードを終了）
0x03 ティーチング軌道実行（ドラッグティーチング軌道を再現）
0x04 一時停止 (Pause)
0x05 再開（軌道再現を継続）
0x06 実行終了 (Terminate execution)
0x07 軌道開始点へ移動 (Move to trajectory starting point)
*/
uint8 motion_status
/*
0x00 指定点に到達 (Reached the specified point)
0x01 指定点に未到達 (Not reached the specified point)
*/
uint8 trajectory_num
/* 0~255 (オフライン軌道モードでのフィードバック) */
int64 err_code// エラーコード
bool joint_1_angle_limit// 関節1 通信エラー (0: 正常, 1: エラー)
bool joint_2_angle_limit// 関節2 通信エラー (0: 正常, 1: エラー)
bool joint_3_angle_limit// 関節3 通信エラー (0: 正常, 1: エラー)
bool joint_4_angle_limit// 関節4 通信エラー (0: 正常, 1: エラー)
bool joint_5_angle_limit// 関節5 通信エラー (0: 正常, 1: エラー)
bool joint_6_angle_limit// 関節6 通信エラー (0: 正常, 1: エラー)
bool communication_status_joint_1// 関節1 角度制限超過 (0: 正常, 1: エラー)
bool communication_status_joint_2// 関節2 角度制限超過 (0: 正常, 1: エラー)
bool communication_status_joint_3// 関節3 角度制限超過 (0: 正常, 1: エラー)
bool communication_status_joint_4// 関節4 角度制限超過 (0: 正常, 1: エラー)
bool communication_status_joint_5// 関節5 角度制限超過 (0: 正常, 1: エラー)
bool communication_status_joint_6// 関節6 角度制限超過 (0: 正常, 1: エラー)
```

エンドエフェクタポーズ制御：一部の特異点は到達不可能な場合があることに注意してください。

`PosCmd.msg`

```c
float64 x
float64 y
float64 z
float64 roll
float64 pitch
float64 yaw
float64 gripper
int32 mode1
int32 mode2
```

## 注意

- ロボットアームからのメッセージ読み取りや制御を行う前に、CANデバイスを有効化し、正しいボーレートを設定する必要があります。

- 以下のように表示された場合：

  ```shell
  Enable state: False
  <class 'can.exceptions.CanError'> Message NOT sent
  <class 'can.exceptions.CanError'> Message NOT sent
  ```

  これは、ロボットアームがCANモジュールに接続されていないことを示しています。USBを抜き差しし、ロボットアームを再起動し、CANモジュールを再有効化してから、ノードの再起動を試みてください。

- 自動有効化がオンになっていて、5秒以内に有効化が成功しない場合、プログラムは自動的に終了します。

## MoveIt プランナーとシミュレーション環境

| 説明 | ドキュメント |
|---|---|
| MoveIt | [MoveIt README](src/piper_moveit/README(EN).md) |
| Simulation | [Simulation README](src/piper_sim/README(EN).md) |

## Q&A

1.  

```shell
colcon build
Starting >>> piper   
Starting >>> piper_control
Starting >>> piper_description
Starting >>> piper_msgs
Finished <<< piper [0.31s]                                                                                                              
--- stderr: piper_description                                                                                            
CMake Error at CMakeLists.txt:5 (find_package):
  By not providing "Findament_cmake.cmake" in CMAKE_MODULE_PATH this project
  has asked CMake to find a package configuration file provided by
  "ament_cmake", but CMake did not find one.
  (中略：ament_cmakeが見つからないエラー)
---
Failed   <<< piper_description [0.45s, exited with code 1]
Aborted  <<< piper_control [0.45s]
Aborted  <<< piper_msgs [0.45s]
...
```

解決策：

```shell
source /opt/ros/foxy/setup.bash
# 注意：お使いのROSバージョンに合わせて setup.bash を読み込んでください (例: humble)
```

2. 

```shell
Starting >>> piper   
Starting >>> piper_control
Starting >>> piper_description
Starting >>> piper_msgs
Finished <<< piper [0.33s]                                                                                                              
Finished <<< piper_description [0.42s]                                                                                     
--- stderr: piper_control                                                               
CMake Error at CMakeLists.txt:7 (find_package):
  By not providing "Findcontroller_manager.cmake" in CMAKE_MODULE_PATH this
  project has asked CMake to find a package configuration file provided by
  "controller_manager", but CMake did not find one.
  (中略：controller_managerが見つからないエラー)
---
Failed   <<< piper_control [0.80s, exited with code 1]
Aborted  <<< piper_msgs [3.28s]                               
...
```

解決策：

```shell
sudo apt install ros-$ROS_DISTRO-ros2-control
sudo apt install ros-$ROS_DISTRO-ros2-controllers
sudo apt install ros-$ROS_DISTRO-controller-manager
```

3. 

```shell
 "package 'joint_state_publisher_gui' not found
```

解決策：

```shell
sudo apt install ros-$ROS_DISTRO-joint-state-publisher-gui
```

4. 

```shell
sudo apt install ros-$ROS_DISTRO-robot-state-publisher
```

5. 

```shell
sudo apt install ros-foxy-xacro
# 注意：Humbleの場合は ros-humble-xacro になります
```