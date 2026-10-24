# Piper アーム起動手順(piper-arm-nuc)

![piper-arm-nuc 起動手順](../0920%20Piper%E6%93%8D%E4%BD%9C.jpg)

Terminator で `piper-arm-nuc` レイアウトを開くと、下記のように6つのペインが並ぶ。各ペインは
`cotyaka-piper-robot-core` コンテナに `exec` で入り、コマンドを実行する仕組みになっている。
各ペインとも、コマンドが表示された後に **Enter を押すと実行**

## 実行手順

### ① RealSense カメラ起動

```bash
ros2 launch realsense2_camera rs_launch.py align_depth.enable:=true depth_module.enable:=true enable_rgbd:=true pointcloud.enable:=true
```

### ② CAN の activate

```bash
bash can_activate.sh can0 1000000
```

### ③ Piper シングルアーム MoveIt 起動

```bash
ros2 launch piper start_single_moveit.launch.py
```

### ④ Piper (グリッパー付き) real MoveIt 起動

```bash
ros2 launch piper with_gripper_moveit real_piper_real_moveit.launch.py
```

### ⑤ enable_flag トピックの操作

```bash
ros2 topic pub --once /enable_flag std_msgs/msg/Bool '{data: false}'
```

- **`{data: false}` の前後に必ずシングルクォーテーション(`'`)を付けること。**
　　表示ではシングルクォーテーションが消えてしまっている。
  　bashファイルの実行仕様上どうしようもないのでコピー時に手動で追加する。
- **`enable_flag` を `false` にすると、アームが脱力する(トルクが抜けて動かせる状態になる)。**
  アームを掴んでいないと落下・脱力落下のおそれがあるので、実行前に必ずアームを支えること。

### ⑥ rosbag record

```bash
ros2 bag record -e "^/camera/.*|^/joint_states$" -o /ros2_ws/bags/realsense_joint_20260920_082153
```

- `-o` の出力先ディレクトリ名(日時部分)は実行時刻に合わせて変更する。

## 注意点まとめ

- ⑤ の `enable_flag` を `false` にする操作は**アームが脱力する**ため、アームの下や周囲に
  物や人がいないか、落下しても問題ないかを確認してから実行する。
- ⑤ のコマンドは `'{data: false}'` のように**シングルクォーテーションを付け忘れないこと**。
  付けないとパースエラーになり実行できない。
