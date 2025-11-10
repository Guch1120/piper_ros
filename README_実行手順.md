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
