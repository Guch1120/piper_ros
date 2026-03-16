# Repository Guidelines

## 役割と目的
このリポジトリのエージェントは、SAM3 の推論速度を改善しつつ精度を維持することを主目的に動作する。現在の主目標は `1FPS未満 -> 5FPS` であり、単なるコード変更ではなく、計測、比較、実装、再計測までを 1 つのループとして扱う。

## 最初に読むファイル
優先順位は `docs/` 配下のルールが最上位である。特に以下を起点にする。

- `docs/AGENT.md`: 自律実行ポリシー
- `docs/architecture_rule.md`: Docker 実行条件と不変条件
- `docs/PLANS.md`: `docs/plan.md` の更新規則
- `docs/plan.md`: 現在の正規計画
- `docs/improvement.md`: 直近の改善案
- `docs/log.md`: 実行結果の時系列ログ

## 実行環境
ホストは診断のみ許可し、ビルド・実行・テストは Docker 内で行う。作業対象コンテナは `piper-humble-dev`、コンテナ内ワークスペースは `/ros2_ws`、このリポジトリは `/ros2_ws/src/sam3` を前提とする。コンテナが未起動なら `docker compose up -d` を試す。GPU 利用時は `nvidia-smi` と PyTorch の CUDA 初期化を確認する。

```bash
docker exec piper-humble-dev bash -lc 'cd /ros2_ws/src/sam3 && python run_sam3_groceries.py'
```

## 自律実行ワークフロー
1. `docs/plan.md` で目的、現状、次の打ち手を確認する。
2. `docs/improvement.md` に直近 1 サイクルの改善案を書く。
3. Docker 内で必要最小限の計測・実装・検証を行う。
4. 実行結果、失敗、判断理由を `docs/log.md` に残す。
5. 目標に未達なら `docs/plan.md` と `docs/improvement.md` を更新して次の 1 手を決める。

## 判断基準
- 危険操作と破壊的変更以外は確認なしで進めてよい。
- 比較候補が複数ある場合は、速度、精度、VRAM 使用量の順で評価する。
- 変更は小さく、可逆で、測定可能にする。
- 無関係なリファクタや設計変更はしない。
- 破壊的操作、秘密情報の露出、大規模方針転換が必要な場合だけ停止する。

## 実装の原則
- まず計測し、ボトルネックを事実で特定してから最小変更を入れる。
- 推論の前処理、モデル初期化、GPU 転送、可視化保存を分けて計測する。
- ベンチマーク条件、使用コマンド、主要指標を再現可能な形で残す。
- 1 回のループで 1 つの仮説を検証し、結果が悪ければ即座に次案へ進む。
