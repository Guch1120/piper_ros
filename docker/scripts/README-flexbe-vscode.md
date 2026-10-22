# FlexBE App VIEW SOURCE → ホスト VS Code (ROS 2 Humble)

## 対象環境

- `piper_ros` の `fix-humble-dev` ブランチ
- コンテナ: `piper-humble-dev`
- 既存 bind mount: ホスト `piper_ros` ルート → Docker `/ros2_ws`
- FlexBE App: `HSR-OIT/flexbe_app` の Humble 版（NW.js）
- 起動: ホスト上で `bash RUN-DOCKER-CONTAINER.bash`

Docker Compose、X11、ROS ノードの設定変更は不要です。

## 初回設定

ホスト側でリポジトリを最新化してください。

```bash
git switch fix-humble-dev
git pull --ff-only
command -v code    # VS Code の CLI が使えることを確認
bash RUN-DOCKER-CONTAINER.bash
```

ホストから `RUN-DOCKER-CONTAINER.bash` を起動すると、監視スクリプトが `.flexbe/open-requests/` を作成します。監視は Terminator の実行中だけ継続します。初回起動時に `code` コマンドが見つからない場合は警告を出し、監視処理のみ無効になります。

FlexBE App の Configuration → Editor Command で次を設定します（コンテナ側のパスです）。

```text
bash /ros2_ws/docker/scripts/open-in-host-vscode.bash $FILE
```

`$FILE` は FlexBE がファイルパスに置換します。FlexBE App はコマンドを単純に空白分割するため、空白を含むファイルパスは未対応です。

## 動作確認

FlexBE App の VIEW SOURCE からステートを選んでホスト VS Code で開けるか確認してください。実機 GUI 操作は未検証です。自動生成コードの場所によっては、`/ros2_ws` 以外を参照する可能性があります。この場合は既存スクリプトが拒否するため、FlexBE 側のステートファイルの実パスを確認してください。

コマンド単体テスト（FlexBE 内から、監視スクリプト起動後）：

```bash
bash /ros2_ws/docker/scripts/open-in-host-vscode.bash /ros2_ws/src/cotyaka_flexbe_behaviors/cotyaka_omega_behaviors/cotyaka_omega_flexbe_states/cotyaka_omega_flexbe_states/record_joint.py
```

ホスト側の `code --reuse-window` で該当ファイルが開くことを確認します。

## 動作概要・セキュリティ

1. FlexBE App が `$FILE` を送り、コンテナ側スクリプトが実在する `/ros2_ws` 配下の Python ファイルか検証
2. `.flexbe/open-requests/` に要求を書き込み、同ディレクトリ内の rename により原子的に確定
3. ホスト側の監視スクリプトが 0.5 秒ごとに読み、パスをホスト側のリポジトリに変換
4. ホスト側でもパスを解決し、共有フォルダ外への逸脱や Python 以外のファイルを拒否
5. `code --reuse-window` で開き、リクエストを削除

要求ディレクトリはホストの一般ユーザー権限で生成され、`chmod 700` です。コンテナ内 root からの書き込みを想定しています。通常の rootful Docker bind mount を前提としており、rootless Docker / user namespace remapping の場合は権限の再設計が必要です。コンテナを信頼できない場合、ホスト VS Code を開かせる要求を完全に保護する仕組みではありません。

## 終了処理

`RUN-DOCKER-CONTAINER.bash` の既存 cleanup は、最初に監視プロセスを停止した後、従来通り ROS 関連プロセスへ SIGINT / 必要時 SIGTERM を送ります。Docker コンテナは停止しません。

## 注意

- ファイル内のソースへのジャンプのみ対応。FlexBE の `$LINE` 連携には未対応
- 別の端末で起動した FlexBE App にはウォッチャー起動が必要
- 日本語フォント `fonts-noto-cjk` は既存 Dockerfile に含まれています
- `.flexbe/` は Git 管理対象から除外されています
