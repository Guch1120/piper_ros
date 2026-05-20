## コチャカ
[x] piper_ctrlのつトピック通信 ->アクション通信化
[x] /setup/realsense.bash でクローンするパスが$HOME/ros2_wsだけどdockerfileで作業ディレクトリを/ros2_wsにしていてビルドもここでするので作業ディレクトリにrealsense_rosが入っていない． == ビルド時にrealsense2が無いと怒られている． dockerfileを変更する？

[ ]　src/sam3_bridge下のマークダウンをros2 humble仕様に書き直す
[ ] nvidiaドライバを535 --> 580にしてcudaとtorchの動作保証をする
[x] sam3コンテナとpiperコンテナを共存させたterminatorレイアウトの構築。
HSRのterminatorと同じようにする必要がある。
[ ] flexbeのGUIで変更が実行時反映されない問題。
怪しいのはinstallやbuildの中身をみて実行していて、変更毎にビルドしないといけない説。俺そこ直したよなぁぁ？？？？？？？srcの中身ろってさぁ

[x] 静的TF動作
[ ] sam3_gRPCのオブジェクト名変更をFlexbeのステートでやる
[ ] SAM3を用いて静的TF動作
[ ] SAM3を用いて動的TF動作
[x] ダイレクトティーチングの実装。動作させるのはMoveItClientParamStateステートを改良させる。パラメータではなくuserdataを使うようにする。

[ ] ダイレクトティーチング結果をuserdataではない形で保存する。永続化。

[ ] Unityシミュレータ化
[ ] Mujoco実装
[ ] unity mujoco plugin
[ ] Kobukiとの連携
[ ] スピーカー実装
[ ] 操作コントローラUIとデバイス開発


## VLM,VLA
[ ] pi0やACTを試してみる
[ ] 実際VLAは使えるのか．VLMとステートを用いたスキル化とスキル獲得は必要なのか．

## リポジトリ管理
[ ] Readmeの中身とファイル名整理と保管場所の統一