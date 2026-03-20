# 手順
以下の手順で実行．ディレクトリはdocker-compose.ymlのある場所で実行. \
やってることはディスプレイ権限を付与してdockerコンテナのビルドと立ち上げ．

```
xhost +local:docker
```
```
docker compose build
```
```
docker compose up -d
```
```
docker compose exec piper-humble-dev bash
```
ここからコンテナの中で実行．
```
source /opt/ros/humble/setup.bash
```
rosdep関係はコンテナ作成後1度でいい．
```
rosdep init && rosdep update
```
```
rosdep install -i --from-path src --rosdistro humble -y
```
```
colcon build --symlink-install
```
```
source install/setup.bash
```

シミュレータ実行
```
ros2 launch piper_description display_xacro.launch.py
```

実機で動かすとき，ホストPCでCAN通信を有効にする．ポートは```can0```で```ボーレートは1000000```
```
bash can_activate.sh can0 1000000
```
立ち上がっているか確認するには
```
ifconfig can0
```
で，こんな感じに```<UP,RUNNING,NOARP>```になっていればOK． \
```<NOARP>```しかないときは通信が確率できていない． \
通信はdocker-compose.ymlでコンテナとホストを共有しているのでコンテナからでも通信認識できる． 
```
robo25@robo25-Alienware-m15-R3:~/yamaguchi/piper_ros$ ifconfig can0
can0: flags=193<UP,RUNNING,NOARP>  mtu 16
        unspec 00-00-00-00-00-00-00-00-00-00-00-00-00-00-00-00  txqueuelen 10  (不明なネット)
        RX packets 0  bytes 0 (0.0 B)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 0  bytes 0 (0.0 B)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```

ホストPCで
```
bash RUN-DOCKER-CONTAINER.bash
```
これでコンテナ起動→コンテナ入り→コンテナ内のterminator起動までできる

# 自動実行コマンドについて
Terminator起動時 (`bash RUN-DOCKER-CONTAINER.bash` 実行時)、以下のコマンドが各ウィンドウで自動的に実行されます。
これにより、手動で `source` コマンドや長い `ros2 launch` コマンドを入力する手間が省けます。

1. `ros2 launch realsense2_camera rs_launch.py align_depth.enable:=true enable_sync:=true enable_rgbd:=true`
2. `ros2 run detic_onnx_ros2 detic_onnx_ros2_node`
3. `ros2 launch piper start_single_moveit_piper.launch.py`
4. `ros2 run piper piper_moveit_bridge`
5. `ros2 launch piper_with_gripper_moveit piper_real_moveit.launch.py`
6. `ros2 run piper moveit_client`

## コマンド実行ラッパースクリプト (`run_ros_cmd.sh`)
これらの自動実行は、`/ros2_ws/run_ros_cmd.sh` というスクリプトを使用しています。
このスクリプトは、ROS環境 (`/opt/ros/humble/setup.bash` および `install/setup.bash`) を読み込んだ上で、引数として渡されたコマンドを実行します。

### 使い方
Terminatorの設定 (`.config/terminator/config`) で、`command` に以下のように記述することで、任意のコマンドを環境設定済みで実行できます。

```bash
bash /ros2_ws/run_ros_cmd.sh [実行したいコマンド]
```

例:
```bash
bash /ros2_ws/run_ros_cmd.sh ros2 topic list
```

**動作仕様:**
1. 起動すると「Press Enter to execute...」と表示され、待機状態になります。実行するコマンドは**シアン色**で表示されます。
2. エンターキーを押すとコマンドが実行されます。
3. 終了するには **'q'** を入力してエンターを押してください。
4. コマンド終了後（または Ctrl+C で中断後）、再び待機状態に戻ります。これにより、エラー発生時のログ確認や、コマンドの再実行が容易に行えます。

---

terminator画面(4分割版)
```
ros2 launch piper start_single_piper.launch.py gripper_exist:=false
```
gripperを付けていない場合で，付けてるときはgrrpper_existの指定はいらない．デフォがtrue. \
これがrosでのアーム起動で．これを起動しないとトピックは全然出てこない．
```
ros2 topic pub /enable_flag std_msgs/msg/Bool "data: false"
```
これでアームが励磁解除される．trueで励磁



そして大事なのがゼロ点設定． \
/piper_sdk/piper_sdk/demo/V2下にある```piper_set_joint_zero.py```を実行する． \
最後6個目のモータを完了してもプログラムは終了しないので終わったらQを入力してエンターを2回行えばプログラムは終了する． \
それで完了
```
python3 piper_set_joint_zero.py
```
ゼロ点になっているか確認したければ，```piper_ctrl_go_zero.py```を実行する．これもV2下にある．
```
python3 piper_ctrl_go_zero.py
```
関節のゼロ点合わせが終われば次はグリッパーのゼロ点合わせ． \
V2下にある```V2_piper_set_gripper_zero.py```を実行する． \
仕様としてプログラム内の数値を変更して実行することでグリッパーのストロークが決まるようになっている． \
なので．ここまでのように実行して数値を代入とかではなく，実行時の数値がパラメータとなる．
```
python3 piper_set_gripper_zero.py
```


deticのインストールはros2_wsにあるsetup_detic.bashを実行する． \
まずsetup_detic.bashに実行権限を与える．
```
chmod +x setup_detic.bash setup_detic_ros.bash
```
```
bash setup_detic.bash
```
```
bash setup_detic_ros.bash
```

サンプル実行方法 (参考)
モデルやサンプル画像は別途ダウンロード/配置が必要です。
モデルのダウンロード (例)

サンプル画像の配置 (例) なんでもいいから好きなやつをmodels/の中に入れて
(./models/sample.JPG に画像を配置する)

デモの実行はこれ． --input のあとのパスがあっているか確認してね
python3 demo.py \
    --config-file configs/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.yaml \
    --input ./models/sample.JPG \
    --output out.jpg \
    --vocabulary lvis \
    --opts MODEL.WEIGHTS models/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth
'

#実行にはsudo chown -R $USER:$USER ./deticが必要


detic_onxx_rosの使い方 \
realsenseノードを起動
```
ros2 launch realsense2_camera rs_launch.py \
  align_depth.enable:=true \
  enable_sync:=true \
  enable_rgbd:=true
```
```
ros2 run detic_onnx_ros2 detic_onnx_ros2_node
```
実行後黄色文字で警告が出る．(対応予定) \
しばらく起動を待って
```
/detic_result/
```

detic_onxxのtfを見る
fixed frameを

# Moveit実機編

- moceit仕様に変更した（Joint.nameでgripper -> joint7）にしたものを実行
```
ros2 launch piper start_single_moveit_piper.launch.py
```
- Moveitのアクション通信をpiperのrosコントローラに合わせるブリッジを起動
```
ros2 run piper piper_moveit_bridge
```
- Moveitとrvizがセットで起動
```
ros2 launch piper_with_gripper_moveit piper_real_moveit.launch.py 
```
- rvizで表示されるアームの球か矢印を動かしてPlanボタン押してExecuteを押すと動く

# Moveit rvizではなくコードから実行編
rviz立ち上げるまではMoveit実践編まんま同じ． \
- ここからが違うとこ． \
- rviz上で動作させるのではなくコードから指定した**角度(ラジアン)**を目標に動く．
```
ros2 run piper moveit_client
```
- 実行するとアクション通信で角度がmoveitのPlannerへ送られてTrajectry(軌跡)が出てくる． \
- Trajecryを受け取ってmoveitのコントローラがアクション通信でFollowJointTrajectryを出す． \
- これをPiperのコントローラのpiper_ctrl_single_nodeで受け取りたいがトピック通信なのでブリッジをかます． \
- それがpiper_moveit_bridgeである．\

moveit_clientのログ(成功例)
```
[INFO] [1764505661.883104917] [move_arm_client]: Sending goal...
[INFO] [1764505661.885222897] [move_arm_client]: Goal accepted! Moving...
[INFO] [1764505662.193592280] [move_arm_client]: Result code: 1
```
このときmoveit_bridgeの出力は，
```
[INFO] [1764503706.083124040] [piper_moveit_bridge]: Received Goal Request
[INFO] [1764503706.083931981] [piper_moveit_bridge]: Executing goal...
```


# Terminatorレイアウトの変更・追加するとき
Terminatorの「レイアウト保存」機能でコマンド設定を維持するためには**「プロファイル」**を使用する. \
以下の手順で行えば設定ファイルを直接編集することなくGUI操作だけで完結できる. \

手順
### 1. 新しいプロファイルを作成する（コマンドの登録）
1. Terminatorのウィンドウ上で右クリックし、**[設定 (Preferences)]** を開きます。
2. **[プロファイル (Profiles)]** タブを選択します。
3. 左側のリストから `default` を選択し、下にある **[追加 (Add)]** ボタンを押します。
    - `default` の設定（背景色など）がコピーされた新しいプロファイルが作成されます。
4. 新しいプロファイルの名前をわかりやすいものに変更します（例: `cmd_new_node`）。
5. 右側の **[コマンド (Command)]** タブを選択します。
6. **[独自のコマンドを実行する (Run a custom command instead of my shell)]** にチェックを入れます。
7. **[独自のコマンド (Custom command)]** 欄に、実行したいコマンドを入力します。
    - 例: `bash /ros2_ws/run_ros_cmd.sh ros2 run my_pkg my_node; bash`
    - ※ 最後に `; bash` をつけると、コマンド終了後もターミナルが閉じずに残ります。

### 2. ターミナルにプロファイルを割り当てる
1. 設定ウィンドウを閉じます。
2. コマンドを割り当てたいターミナル（画面分割した枠）の上で右クリックします。
3. **[プロファイル (Profiles)]** メニューから、先ほど作成したプロファイル（例: `cmd_new_node`）を選択します。
    - これで、そのターミナルは指定したコマンドを実行する設定になります。

### 3. レイアウトを保存する
1. 全てのターミナルの配置とプロファイル割り当てが完了したら、右クリックして **[設定 (Preferences)]** を開きます。
2. **[レイアウト (Layouts)]** タブを選択します。
3. 左側のリストから `default`（または保存したいレイアウト名）を選択します。
4. **[保存 (Save)]** ボタンを押します。
5. 設定ウィンドウを閉じます。

これで、次回起動時もこのレイアウトとコマンド設定が復元されます。


# 円弧軌道・三角軌道・台形軌道・直線軌道のmoveit動作
moveit_client_interactive_nodeを起動した状態(=tfを出している状態)で実行する．
```
ros2 run piper pick_and_place_trajectory
```

# ビルドを簡単にする魔法のコマンド
```
alias cb='colcon build --symlink-install'
```