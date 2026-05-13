[x] piper_ctrlのつトピック通信 ->アクション通信化
[x] /setup/realsense.bash でクローンするパスが$HOME/ros2_wsだけどdockerfileで作業ディレクトリを/ros2_wsにしていてビルドもここでするので作業ディレクトリにrealsense_rosが入っていない． == ビルド時にrealsense2が無いと怒られている． dockerfileを変更する？

[ ]　src/sam3_bridge下のマークダウンをros2 humble仕様に書き直す
[ ] sam3コンテナとpiperコンテナを共存させたterminatorレイアウトの構築。
HSRのterminatorと同じようにする必要がある。

[ ] 静的TF動作
[ ] SAM3を用いて静的TF動作
[ ] SAM3を用いて動的TF動作
[ ] ダイレクトティーチングもどきの実装。動作させるのはMoveItClientParamStateステートを改良させる。パラメータではなくuserdataを使うようにする。

[ ] Unityシミュレータ化
[ ] Kobukiとの連携
[ ] Readmeの中身とファイル名整理と保管場所の統一