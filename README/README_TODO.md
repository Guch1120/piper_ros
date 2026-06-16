## コチャカ
- [x] piper_ctrlのつトピック通信 ->アクション通信化
- [x] /setup/realsense.bash でクローンするパスが$HOME/ros2_wsだけどdockerfileで作業ディレクトリを/ros2_wsにしていてビルドもここでするので作業ディレクトリにrealsense_rosが入っていない． == ビルド時にrealsense2が無いと怒られている． dockerfileを変更する？

- [x] Kobukiとの連携
- [ ] Kobukiからの/odomを受けてアームのヨー軸回転
- [ ] スピーカー実装
- [ ] 操作コントローラUIとデバイス開発

- [ ]　src/sam3_bridge下のマークダウンをros2 humble仕様に書き直す
- [ ] nvidiaドライバを535 --> 580にしてcudaとtorchの動作保証をする
- [x] sam3コンテナとpiperコンテナを共存させたterminatorレイアウトの構築。
HSRのterminatorと同じようにする必要がある。
- [x] flexbeのGUIで変更が実行時反映されない問題。
怪しいのはinstallやbuildの中身をみて実行していて、変更毎にビルドしないといけない
- [x] URDFの修正。Realsenseの位置姿勢が不当
- [x] RUN-DOCKER-CONTAINER.bash終了時にROSプロセス終了処理を追加
- [ ] ダイレクトティーチング用に重力補償の実装
### SAM3でTF動作編
- [x] 静的TF動作
- [x] sam3_gRPCのオブジェクト名変更をFlexbeのステートでやる
- [x] sam3でTF発行
- [x] TF変換ステート作成
- [x] SAM3を用いて静的TF動作
- [ ] SAM3を用いて動的TF動作

- [x] ダイレクトティーチングの実装。動作させるのはMoveItClientParamStateステートを改良させる。パラメータではなくuserdataを使うようにする。

- [x] ダイレクトティーチング結果をuserdataではない形で保存する。永続化。

### Sim環境
- [ ] Unityシミュレータ化
<details>
<summary>ロードマップ</summary>
    
- [x] Unity内でjoint1だけ動かす
- [ ] ROS2 /joint_statesをUnityで購読してjoint角を反映
- [ ] ROS2 /joint_statesでUnity上のPiperを動作させる　
- [ ] ROS2からPiperの実joint値を流してUnity上Piperを同期
- [ ] Unity CameraをROS2画像としてpublish
</details>
- [ ] Mujoco実装
- [ ] unity mujoco plugin

## VLM,VLA
- [ ] pi0やACTを試してみる
- [ ] 実際VLAは使えるのか．VLMとステートを用いたスキル化とスキル獲得は必要なのか．
<details>
<summary>VLAロードマップ</summary>

LLM planner
- [ ] ProgPrompt
- [ ] SayCan
- [ ] Inner Monologue / ReAct系のフィードバック付きロボットエージェント
- [ ] RT-1 / RT-2
- [ ] OpenVLA
- [ ] π0 / Gemini Robotics
</details>

## リポジトリ管理
- [ ] Readmeの中身とファイル名整理と保管場所の統一