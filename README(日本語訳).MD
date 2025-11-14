piper メカニカルアームROS(humble)EN (英語)python_version >= "3.10"テスト:PYTHONSTATEgit clone [https://github.com/agilexrobotics/piper_ros.git](https://github.com/agilexrobotics/piper_ros.git)
cd piper_ros
git checkout humble
説明ドキュメントMoveitMoveit READMEシミュレーションシミュレーション README0 URDFバージョンに関する注意S-V1.6-3ファームウェアバージョン以前のDHパラメータは、各関節が接触リミットにある位置を初期座標として取得されていますS-V1.6-3ファームウェアバージョン以降のDHパラメータは、j2とj3の座標系が2度オフセットされています現在のデフォルトURDFは後者ですファームウェアバージョンurdfcurrent version < S-V1.6-3piper_description_old.urdfcurrent version >= S-V1.6-3piper_description.urdf1 インストール方法1.1 依存関係のインストール注: python-canのバージョンは4.3.1より高い必要がありますpip3 install python-can
pip3 install scipy
pip3 install piper_sdk
sudo apt install ros-$ROS_DISTRO-ros2-control
sudo apt install ros-$ROS_DISTRO-ros2-controllers
sudo apt install ros-$ROS_DISTRO-controller-manager
2 CANモジュールの使用注意：ここでいうCANモジュールは、メカニカルアーム付属のCANモジュールのみをサポートしており、他のCANモジュールはサポートしていませんCANツールのインストールsudo apt update && sudo apt install can-utils ethtool
これら2つのツールはCANモジュールの設定に使用されますbashスクリプトの実行中にip: command not foundが表示された場合は、ipコマンドをインストールしてください。通常はsudo apt-get install iproute2です2.1 CANモジュールの検索実行bash find_all_can_port.sh
パスワード入力後、CANモジュールがPCに挿入され、PCによって検出されると、以下のような出力が表示されます：Both ethtool and can-utils are installed.
Interface can0 is connected to USB port 3-1.4:1.0
複数ある場合は、以下のように出力されます：Both ethtool and can-utils are installed.
Interface can0 is connected to USB port 3-1.4:1.0
Interface can1 is connected to USB port 3-1.1:1.0
CANモジュールの数だけInterface can1 is connected to USB port 3-1.1:1.0のような行が出力されますここでcan1はシステムが見つけたCANモジュールの名前、3-1.1:1.0はそのCANモジュールが接続されているUSBポートです以前にCANモジュールをアクティベートし、別の名前（ここではcan_piperと仮定）を付けていた場合、出力は以下のようになりますBoth ethtool and can-utils are installed.
Interface can_piper is connected to USB port 3-1.4:1.0
Interface can0 is connected to USB port 3-1.1:1.0
CANモジュールが検出されない場合は、以下のようにのみ出力されます：Both ethtool and can-utils are installed.
2.2 単一CANモジュールのアクティベート, ここではcan_activate.shスクリプトを使用単一のCANモジュールをアクティベートするケースは2つあります。1つはPCにCANモジュールが1つだけ接続されている場合、もう1つは複数のCANモジュールがPCに挿入されているが、そのうちの1つだけをアクティベートする場合です。2.2.1 PCにUSB-CANモジュールが1つだけ挿入されている場合直接実行bash can_activate.sh can0 1000000
ここでcan0は任意の名前に変更可能です。1000000はボーレートで、メカニカルアームを使用する場合は変更できません2.2.2 PCに複数のUSB-CANモジュールが挿入されているが、一度に1つのCANモジュールのみアクティベートする場合注： これは、メカニカルアームとシャーシを同時に使用する場合に用いられます(1) CANモジュールが挿入されているUSBポートのハードウェアアドレスを確認します。すべてのCANモジュールを取り外し、メカニカルアームに接続されているCANモジュールのみをPCに挿入して、実行しますbash find_all_can_port.sh
そしてUSB portの値を記録します（例：3-1.4:1.0）(2) CANデバイスをアクティベートします。上記のUSB portの値が3-1.4:1.0であったと仮定し、実行します：bash can_activate.sh can_piper 1000000 "3-1.4:1.0"
説明：ハードウェアエンコード3-1.4:1.0のUSBポートに挿入されたCANデバイスの名前をcan_piperに変更し、ボーレートを1000000に設定してアクティベートします(3) アクティベートが成功したか確認ifconfigを実行し、can_piperがあるか確認します。あればCANモジュールの設定は成功です2.3 複数のCANモジュールを同時にアクティベート, ここではcan_muti_activate.shスクリプトを使用まず、公式のCANモジュールがPCにいくつ挿入されているかを確認します。ここでは2つと仮定します注：現在PCに5つのCANモジュールが挿入されていても、指定したCANモジュールのみをアクティベートすることが可能です2.3.1 各CANモジュールに対応するUSBポートのハードウェアアドレスを記録CANモジュールを1つずつ抜き差しし、各モジュールに対応するUSBポートのハードウェアアドレスを1つずつ記録しますcan_muti_activate.sh内のUSB_PORTSパラメータの要素数は、アクティベート予定のCANモジュールの数です。ここでは2と仮定します(1) CANモジュールのうちの1つを単独でPCに挿入し、実行しますbash find_all_can_port.sh
そしてUSB portの値を記録します（例：3-1.4:1.0）(2) 次に、次のCANモジュールを挿入します。注意：前回CANモジュールを挿入したUSBポートと同じであってはいけません。その後、実行しますbash find_all_can_port.sh
2番目のCANモジュールのUSB portの値を記録します（例：3-1.1:1.0）注：一度もアクティベートしたことがない場合、最初に挿入されたCANモジュールはデフォルトでcan0、2番目はcan1となります。アクティベートしたことがある場合は、以前アクティベートした際の名称になります2.3.2 USBポート、ターゲットインターフェース名、およびそのボーレートを事前定義上記操作で記録したUSB portの値がそれぞれ3-1.4:1.0、3-1.1:1.0であったと仮定し、以下のUSB_PORTS["1-9:1.0"]="can_left:1000000"の角括弧内のダブルクォーテーション内部のパラメータを3-1.4:1.0と3-1.1:1.0に置き換えます。最終結果は以下のようになります：USB_PORTS["3-1.4:1.0"]="can_left:1000000"
USB_PORTS["3-1.1:1.0"]="can_right:1000000"
説明：ハードウェアエンコード3-1.4:1.0のUSBポートに挿入されたCANデバイスの名前をcan_leftに変更し、ボーレートを1000000に設定してアクティベートします2.3.3 複数のCANモジュールをアクティベートbash can_muti_activate.shを実行します2.3.4 複数のCANモジュールが正常に設定されたか確認ifconfigを実行し、can_leftとcan_rightがあるか確認します3 ノードの実行コンパイルcd piper_ros
colcon build
source install/setup.bash
3.1 単一メカニカルアームの制御起動ノード名：piper_single_ctrlパラメータcan_port: 開くCANポートの名前
auto_enable: 自動で有効化するかどうか。Trueの場合、プログラム開始時に自動で有効化されます
# 注意：これをFalseに設定すると、プログラムを中断した後にノードを再起動した場合、メカニカルアームは前回のプログラム起動時の状態を保持します
# もし前回のプログラム起動時にアームが有効化されていた場合、中断後にノードを再起動してもアームは有効化されたままです
# もし前回のプログラム起動時にアームが無効化されていた場合、中断後にノードを再起動してもアームは無効化されたままです
gripper_exist: エンドグリッパーが存在するかどうか。Trueの場合、エンドグリッパーが存在することを示し、グリッパー制御が有効になります
rviz_ctrl_flag: rvizを使用して関節角度メッセージを送信するかどうか。Trueの場合、rvizから送信される関節角度メッセージを受信します
gripper_val_mutiple: グリッパー制御の倍率を設定
# rviz内のjoint7の範囲は[0, 0.04]ですが、実際のグリッパーのストロークは0.08mであるため、rvizで実際のグリッパーを制御するには、グリッパー倍率を2倍に設定する必要があります
単一アームを起動するためのlaunchファイルはstart_single_piper_rviz.launch.pyとstart_single_piper.launch.pyの2つがあります前者はrvizも一緒に起動でき、スライドバーをドラッグしてメカニカルアームを制御できます制御ノードを起動します。以下のいずれかの方法で実行してくださいros2 run 方式# ノードの起動
ros2 run piper piper_single_ctrl --ros-args -p can_port:=can0 -p auto_enable:=false -p gripper_exist:=true -p gripper_val_mutiple:=2
# ログレベルの設定 --log-level DEBUG/INFO/WARN/ERROR
ros2 run piper piper_single_ctrl --ros-args -p can_port:=can0 -p auto_enable:=false -p gripper_exist:=true -p gripper_val_mutiple:=2 --log-level WARN
ros2 topic list/arm_status #メカニカルアームの状態、詳細は後述
/enable_flag #有効化フラグ、ノードに送信し、trueを送信して有効化する
/end_pose #メカニカルアームのエンドエフェクタの姿勢状態フィードバック
/end_pose_stamped #タイムスタンプ付きのendposeメッセージ
/joint_ctrl #メカニカルアームの制御関連メッセージのフィードバック
/joint_ctrl_single #関節メッセージを購読。このトピックに関節位置を送信するとメカニカルアームを制御できる
/joint_states_single #メカニカルアームの関節状態フィードバック
/joint_states_feedback #同上、トピック名を変更しただけ
/pos_cmd #エンドエフェクタ制御メッセージ、xyzrpy、グリッパー単位はm、mode1とmode2パラメータはデフォルトで0でOK
ros2 launch 方式launchファイルは/joint_ctrl_singleトピックをリマップし、/joint_statesをメカニカルアーム制御用のメッセージとすることで、rvizとの連携を容易にし、rvizで実際のメカニカルアームを制御できるようにしています# ノードの起動
ros2 run piper piper_single_ctrl --ros-args -p can_port:=can0 -p auto_enable:=false -p gripper_exist:=true -p gripper_val_mutiple:=2
# ログレベルの設定 --log-level DEBUG/INFO/WARN/ERROR
ros2 run piper piper_single_ctrl --ros-args -p can_port:=can0 -p auto_enable:=false -p gripper_exist:=true -p gripper_val_mutiple:=2 --log-level WARN
# launchノードも使用可能
ros2 launch piper start_single_piper.launch.py can_port:=can0 auto_enable:=false gripper_exist:=false gripper_val_mutiple:=2
# log_levelの設定を追加
ros2 launch piper start_single_piper.launch.py can_port:=can0 auto_enable:=false gripper_exist:=false gripper_val_mutiple:=2 log_level:=warn
# または、デフォルトパラメータで実行
ros2 launch piper start_single_piper.launch.py
# rvizを使用して制御を開始することも可能、変更が必要なパラメータは上記参照
ros2 launch piper start_single_piper_rviz.launch.py
ros2 topic list/arm_status #メカニカルアームの状態、詳細は後述
/enable_flag #有効化フラグ、ノードに送信し、trueを送信して有効化する
/end_pose #メカニカルアームのエンドエフェクタの姿勢状態フィードバック
/end_pose_stamped #タイムスタンプ付きのendposeメッセージ
/joint_ctrl #メカニカルアームの制御関連メッセージのフィードバック
/joint_states #関節メッセージを購読。このトピックに関節位置を送信するとメカニカルアームを制御できる
/joint_states_single #メカニカルアームの関節状態フィードバック
/joint_states_feedback #同上、トピック名を変更しただけ
/pos_cmd #エンドエフェクタ制御メッセージ、xyzrpy、グリッパー単位はm、mode1とmode2パラメータはデフォルトで0でOK
ros2 service list/enable_srv #メカニカルアーム有効化サービスサーバー
メカニカルアームの有効化# サービスサーバーをcall
ros2 service call /enable_srv piper_msgs/srv/Enable enable_request:\ true\ 
# topicをpub
ros2 topic pub /enable_flag std_msgs/msg/Bool data:\ true\ 
メカニカルアームの無効化# サービスサーバーをcall
ros2 service call /enable_srv piper_msgs/srv/Enable enable_request:\ false\ 
# topicをpub
ros2 topic pub /enable_flag std_msgs/msg/Bool data:\ false\ 
関節メッセージのパブリッシュ注意：メカニカルアームが持ち上がりますので、アームの作業範囲内に障害物がないことを確認してくださいメカニカルアームはデフォルト速度の10%で動作し、グリッパーのトルクは0.5Nに設定されます速度範囲は1〜100に制限され、1未満の場合は1とみなされます位置は以下の通りros2 topic pub /joint_states sensor_msgs/msg/JointState "{header: {stamp: {sec: 0, nanosec: 0}, frame_id: 'piper_single'}, name: ['joint1', 'joint2','joint3','joint4','joint5','joint6','joint7'], position: [0.2,0.2,-0.2,0.3,-0.2,0.5,0.01], velocity: [0,0,0,0,0,0,10], effort: [0,0,0,0,0,0,0.5]}"

3.2 単一メカニカルアームの関節メッセージ読み取りを起動し、rvizで追従表示関節データ読み取りノードの起動# グリッパーあり
ros2 run piper piper_read_slave_joint --ros-args -p can_port:=can0 -p gripper_exist:=true
# グリッパーなし
ros2 run piper piper_read_slave_joint --ros-args -p can_port:=can0 -p gripper_exist:=false
実行後、メカニカルアームのメッセージフィードバック用として/joint_statesのみが存在しますグリッパーありで起動した場合、メッセージ内容にはjoint7、joint8のデータが含まれます。これはrvizが追従表示機能として使用するために必要ですrviz追従表示launchの起動# グリッパーあり
ros2 launch piper_description  display_urdf_follow.launch.py
# グリッパーなし
ros2 launch piper_description  display_no_gripper_urdf_follow.launch.py
note:rvizの表示のみを起動し、関節データの読み取りを起動しない場合、/joint_statesデータがパブリッシュされず、rviz内のモデルのすべてのlinkが原点に集まってしまい、正常に表示されません実機のメカニカルアームデータ読み取りノードを起動したくない場合は、rvizの表示launchのみを起動し、他のプログラムやターミナルからjoint_statesトピックをパブリッシュすることができます。以下に例を示します# グリッパーあり
ros2 topic pub /joint_states sensor_msgs/msg/JointState "header:
  stamp:
    sec: 1757669668
    nanosec: 196177482
  frame_id: ''
name: ['joint1','joint2','joint3','joint4','joint5','joint6','gripper','joint7','joint8']
position: [0,0,0,0,0,0,0,0,0]
velocity: [0,0,0,0,0,0,0,0,0]
effort: [0,0,0,0,0,0,0,0,0]" 
# グリッパーなし
ros2 topic pub /joint_states sensor_msgs/msg/JointState "header:
  stamp:
    sec: 1757669668
    nanosec: 196177482
  frame_id: ''
name: ['joint1','joint2','joint3','joint4','joint5','joint6']
position: [0,0,0,0,0,0]
velocity: [0,0,0,0,0,0]
effort: [0,0,0,0,0,0]" 
注意：header内のタイムスタンプは必須です。さもないと、rvizで表示されるモデルが依然として正常に表示されません3.3 両腕の同時制御各アームがそれぞれ1つのCANモジュールに接続され、2つのCANモジュールをアクティベートする必要がありますlaunchファイル内で読み取られる2つのCANモジュールの名前はどちらもcan0になっています。各自で手動で左右のアームのシステム上の名前に変更する必要があります。確認方法は以下の通りです：ifconfig -a | grep can
両腕起動の実行# デフォルトでは、両方のノードがcan0メッセージを読み取るように起動します
ros2 launch piper start_two_piper.launch.py auto_enable:=false
# 読み取るCANポート名をカスタマイズ
ros2 launch piper start_two_piper.launch.py can_left_port:=can_left can_right_port:=can_right auto_enable:=true girpper_exist:=true
launch内部でtopicのリマップが行われています# piper_left_node
remappings=[
            # 制御
            ('pos_cmd', '/pos_cmd_left'),
            ('joint_ctrl_single', '/joint_ctrl_cmd_left'),
            # フィードバック
            ('joint_states_single', '/joint_states_left'),
            ('joint_states_feedback', '/joint_left'),
            ('joint_ctrl', '/joint_states_ctrl_left'),
            ('arm_status', '/arm_status_left'),
            ('end_pose', '/end_pose_left'),
            ('end_pose_stamped', '/end_pose_stamped_left'),
        ]
# piper_right_node
remappings=[
            # 制御
            ('pos_cmd', '/pos_cmd_right'),
            ('joint_ctrl_single', '/joint_ctrl_cmd_right'),
            # フィードバック
            ('joint_states_single', '/joint_states_right'),
            ('joint_states_feedback', '/joint_right'),
            ('joint_ctrl', '/joint_states_ctrl_right'),
            ('arm_status', '/arm_status_right'),
            ('end_pose', '/end_pose_right'),
            ('end_pose_stamped', '/end_pose_stamped_right'),
        ]
上記単一ノードのtopic説明と対照して、リマップ後のtopicの意味を理解してください/arm_status_left
/arm_status_right
/enable_flag
/end_pose_left
/end_pose_right
/end_pose_stamped_left
/end_pose_stamped_right
/joint_ctrl_cmd_left
/joint_ctrl_cmd_right
/joint_left
/joint_right
/joint_states_ctrl_left
/joint_states_ctrl_right
/joint_states_left
/joint_states_right
/pos_cmd_left
/pos_cmd_right
3.4 piperカスタムメッセージROSパッケージ：piper_msgsメカニカルアーム自身の状態フィードバックメッセージ。CANプロトコルのid=0x2A1のフィードバックメッセージに対応しますPiperStatusMsg.msguint8 ctrl_mode
/*
0x00 スタンバイモード
0x01 CANコマンド制御モード
0x02 ティーチングモード
0x03 イーサネット制御モード
0x04 WiFi制御モード
0x05 リモートコントローラー制御モード
0x06 連携ティーチング入力モード
0x07 オフライン軌道モード*/
uint8 arm_status
/*
0x00 正常
0x01 非常停止
0x02 解なし
0x03 特異点
0x04 目標角度がリミット超過
0x05 関節通信異常
0x06 関節ブレーキ未解除
0x07 メカニカルアーム衝突
0x08 ドラッグティーチング中の速度超過
0x09 関節状態異常
0x0A その他の異常
0x0B ティーチング記録
0x0C ティーチング実行
0x0D ティーチング一時停止
0x0E メインコントロールNTC過熱
0x0F 放電抵抗NTC過熱*/
uint8 mode_feedback
/*
0x00 MOVE P
0x01 MOVE J
0x02 MOVE L
0x03 MOVE C*/
uint8 teach_status
/*
0x00 終了
0x01 ティーチング記録開始（ドラッグティーチングモードに入る）
0x02 ティーチング記録終了（ドラッグティーチングモードを終了する）
0x03 ティーチング軌道実行（ドラッグティーチング軌道再現）
0x04 実行一時停止
0x05 実行継続（軌道再現継続）
0x06 実行中止
0x07 軌道開始点へ移動*/
uint8 motion_status
/*
0x00 指定ポイント到達
0x01 指定ポイント未到達*/
uint8 trajectory_num
/*0~255 (オフライン軌道モードでのフィードバック)*/
int64 err_code//エラーコード
bool joint_1_angle_limit//1番関節通信異常（0：正常 1：異常）
bool joint_2_angle_limit//2番関節通信異常（0：正常 1：異常）
bool joint_3_angle_limit//3番関節通信異常（0：正常 1：異常）
bool joint_4_angle_limit//4番関節通信異常（0：正常 1：異常）
bool joint_5_angle_limit//5番関節通信異常（0：正常 1：異常）
bool joint_6_angle_limit//6番関節通信異常（0：正常 1：異常）
bool communication_status_joint_1//1番関節角度リミット超過（0：正常 1：異常）
bool communication_status_joint_2//2番関節角度リミット超過（0：正常 1：異常）
bool communication_status_joint_3//3番関節角度リミット超過（0：正常 1：異常）
bool communication_status_joint_4//4番関節角度リミット超過（0：正常 1：異常）
bool communication_status_joint_5//5番関節角度リミット超過（0：正常 1：異常）
bool communication_status_joint_6//6番関節角度リミット超過（0：正常 1：異常）
メカニカルアームのエンドエフェクタ姿勢制御、注意：一部の特異点には到達できませんPosCmd.msgfloat64 x
float64 y
float64 z
float64 roll
float64 pitch
float64 yaw
float64 gripper
int32 mode1
int32 mode2
注意事項先にCANデバイスをアクティベートし、正しいボーレートを設定しなければ、メカニカルアームのメッセージを読み取ったり、制御したりすることはできませんもし  shell   使能状态: False   <class 'can.exceptions.CanError'> Message NOT sent   <class 'can.exceptions.CanError'> Message NOT sent     が表示された場合、メカニカルアームがCANモジュールと通信できていないことを示します。USBを抜き差しし、メカニカルアームを再起動し、再度CANモジュールをアクティベートしてから、ノードの再起動を試みてください自動有効化がオンになっている場合、5秒間有効化を試みて成功しないと、プログラムは自動的に終了しますQ&A以下が発生した場合colcon build
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

  Could not find a package configuration file provided by "ament_cmake" with
  any of the following names:

    ament_cmakeConfig.cmake
    ament_cmake-config.cmake

  Add the installation prefix of "ament_cmake" to CMAKE_PREFIX_PATH or set
  "ament_cmake_DIR" to a directory containing one of the above files.  If
  "ament_cmake" provides a separate development package or SDK, be sure it
  has been installed.


---
Failed   <<< piper_description [0.45s, exited with code 1]
Aborted  <<< piper_control [0.45s]
Aborted  <<< piper_msgs [0.45s]

Summary: 1 package finished [0.55s]
  1 package failed: piper_description
  2 packages aborted: piper_control piper_msgs
  3 packages had stderr output: piper_control piper_description piper_msgs
source /opt/ros/$ROS_DISTRO/setup.bash
2. Starting >>> piper   
Starting >>> piper_control
Starting >>> piper_description
Starting >>> piper_msgs
Finished <<< piper [0.33s]                                                                              ...
Finished <<< piper_description [0.42s]                                                                  ...
--- stderr: piper_control                                                               
CMake Error at CMakeLists.txt:7 (find_package):
  By not providing "Findcontroller_manager.cmake" in CMAKE_MODULE_PATH this
  project has asked CMake to find a package configuration file provided by
  "controller_manager", but CMake did not find one.

  Could not find a package configuration file provided by
  "controller_manager" with any of the following names:

    controller_managerConfig.cmake
    controller_manager-config.cmake

  Add the installation prefix of "controller_manager" to CMAKE_PREFIX_PATH or
  set "controller_manager_DIR" to a directory containing one of the above
  files.  If "controller_manager" provides a separate development package or
  SDK, be sure it has been installed.


---
Failed   <<< piper_control [0.80s, exited with code 1]
Aborted  <<< piper_msgs [3.28s]                               

Summary: 2 packages finished [3.38s]
  1 package failed: piper_control
  1 package aborted: piper_msgs
  1 package had stderr output: piper_control
sudo apt install ros-$ROS_DISTRO-ros2-control
sudo apt install ros-$ROS_DISTRO-ros2-controllers
sudo apt install ros-$ROS_DISTRO-controller-manager
3. 発生： "package 'joint_state_publisher_gui' not found
インストール：sudo apt install ros-$ROS_DISTRO-joint-state-publisher-gui
4. sudo apt install ros-$ROS_DISTRO-robot-state-publisher
5. sudo apt install ros-$ROS_DISTRO-xacro
