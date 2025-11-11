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
dockerfileでterminatorのインストールができていないので，
```
apt get install terminator
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
