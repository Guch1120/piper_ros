# 手順
以下の手順で実行．ディレクトリはdocker-compose.ymlのある場所で実行．
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
docker compose exec piper-humble-dev bash```
ここからコンテナの中で実行．
```
source /opt/ros/humble/setup.bash
```
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