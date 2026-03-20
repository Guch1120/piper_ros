# ルールと注意すること
## ルール
1. システムはdockerコンテナ内で実行される．
2. コンテナ名はpiper-humble-devである．docker-compose.ymlは/home/guch1/ssd_yamaguchi/piper_ros/dockerにある．

## 注意すること
1. docker内でのパスとホストのパスが異なるので注意．コンテナでのワーキングディレクトリ設定やユーザ設定名が異なる．
2. コンテナ内ワーキングディレクトリは`/ros2_ws`である．また，コンテナ内ユーザはrootユーザである．