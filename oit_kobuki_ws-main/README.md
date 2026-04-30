# oit_kobuki_ws

1. このリポジトリをクローンする
```bash
git clone 
```

2. ビルドする 
NUC等の場合はオプションを追加する
``` bash
cd oit_kobuki_ws
colcon build --executor sequential
```

3. USBが反応するようにグループに入れる
```
sudo su -
# vimなので注意
vi /etc/group
```
<img src=./pictures/group_usb_vim.png width="800px" height="200px">

usb接続確認
```
cat /dev/ttyUSB0
more /dev/ttyUSB0
```

## LIDERとkobukiの接続方法
1. kobukiにLiDARを赤い四角いところに刺す

<img src=./pictures/kobuki_LiDAR1.png width="250px" height="250px">

2. NUCに、LiDARを赤い四角いところに刺す

<img src=./pictures/kobuki_LiDAR2.png width="250px" height="250px">


### コマンド集
- launch
```
# oit_kobuki_wsで行う
ros2 launch kobuki_node kobuki_node-launch.py
```
- キーオペ
```
ros2 run kobuki_keyop kobuki_keyop_node cmd_vel:=/commands/velocity
```
- rviz2
```
ros2 launch kobuki_description robot_description.launch.py rviz:=true
```
- topicの確認方法
```
ros2 topic list
ros2 topic info <topic名>
ros2 topic echo <topic名>
```
※ ros2 humble関連を動かすときは以下のコマンドを実行する(rosのおまじない)
```
source install/setup.bash
```

## tfの合わせ方
1. oit_kobuki_wsでlaunchを起動する
```
ros2 launch kobuki_node kobuki_node-launch.py
```
2. 
```
ros2 launch urg_node2 urg_node2.launch.py
```
```
rviz2
```
```
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 "base_footprint" "laser"
```
```
ros2 launch slam_toolbox online_async_launch.py
```

3. USBが反応するようにグループに入れる
```
sudo su -
# vimなので注意
vi /etc/group
```
<img src=./pictures/group_usb_vim.png width="800px" height="200px">

usb接続確認
```
cat /dev/ttyUSB0
more /dev/ttyUSB0
```

## LIDERとkobukiの接続方法
1. kobukiにLiDARを赤い四角いところに刺す

<img src=./pictures/kobuki_LiDAR1.png width="250px" height="250px">

2. NUCに、LiDARを赤い四角いところに刺す

<img src=./pictures/kobuki_LiDAR2.png width="250px" height="250px">


### コマンド集
- launch
```
# oit_kobuki_wsで行う
ros2 launch kobuki_node kobuki_node-launch.py
```
- キーオペ
```
ros2 run kobuki_keyop kobuki_keyop_node cmd_vel:=/commands/velocity
```
- rviz2
```
ros2 launch kobuki_description robot_description.launch.py rviz:=true
```
- topicの確認方法
```
ros2 topic list
ros2 topic info <topic名>
ros2 topic echo <topic名>
```
※ ros2 humble関連を動かすときは以下のコマンドを実行する(rosのおまじない)
```
source install/setup.bash
```

## tfの合わせ方
1. oit_kobuki_wsでlaunchを起動する
```
ros2 launch kobuki_node kobuki_node-launch.py
```
2. 
```
ros2 launch urg_node2 urg_node2.launch.py
```
```
rviz2
```
```
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 "base_footprint" "laser"
```
```
ros2 launch slam_toolbox online_async_launch.py
```


# ドキュメント整備中！

- [x] ホスト環境でキーオペ
- [x] Hokuyo 2D LiDAR起動
- [ ] slam toolboxのonline_async_launch.pyから地図作成
- [x] Docker環境でキーオペ
- [ ] ホスト環境・Docker環境の構築方法ドキュメント(2D LiDAR設定・配線写真・実行ノードなど)


  - 前進キー: [keyop.cpp](/home/robo25/yamaguchi/oit_kobuki_ws/src/kobuki_ros/kobuki_keyop/src/keyop.cpp):360
    cmd_->linear.x += linear_vel_step
  - 後退キー: [keyop.cpp](/home/robo25/yamaguchi/oit_kobuki_ws/src/kobuki_ros/kobuki_keyop/src/keyop.cpp):381
    cmd_->linear.x -= linear_vel_step
  - 左旋回キー: [keyop.cpp](/home/robo25/yamaguchi/oit_kobuki_ws/src/kobuki_ros/kobuki_keyop/src/keyop.cpp):402
    cmd_->angular.z += angular_vel_step
  - 右旋回キー: [keyop.cpp](/home/robo25/yamaguchi/oit_kobuki_ws/src/kobuki_ros/kobuki_keyop/src/keyop.cpp):423
    cmd_->angular.z -= angular_vel_step