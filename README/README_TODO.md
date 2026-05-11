[ ] piper_ctrlのつトピック通信 ->アクション通信化
[ ] /setup/realsense.bash でクローンするパスが$HOME/ros2_wsだけどdockerfileで作業ディレクトリを/ros2_wsにしていてビルドもここでするので作業ディレクトリにrealsense_rosが入っていない． == ビルド時にrealsense2が無いと怒られている． dockerfileを変更する？
[ ]　src/sam3_bridge下のマークダウンをors1 noeticからros2 humble仕様に書き直す。

[ ] sam3コンテナとpiperコンテナを共存させたterminatorレイアウトの構築。
HSRのterminatorと同じようにする必要がある。