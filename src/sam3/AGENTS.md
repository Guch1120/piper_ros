# SAM3推論の改善

- 目的は精度を維持した推論高速化。現在の目標・測定条件・採否は [docs/plan.md](docs/plan.md) を参照し、過去のFPS目標を現在の課題として固定しない。
- 実行条件は [docs/architecture_rule.md](docs/architecture_rule.md)。Dockerコンテナ `piper-humble-dev`、コンテナ内 `/ros2_ws/src/sam3` を使用し、ホストは診断のみとする。
- 性能変更では同条件で速度・精度・VRAMを比較する。前処理・初期化・GPU転送・推論・可視化保存の影響を区別し、コマンドと条件を [docs/log.md](docs/log.md) に残す。
- 許可された範囲の計測・実装・検証・修正まで自律的に完了する。実験を続ける範囲は依頼と完了条件で決める。
- 継続的な実験の計画更新は [docs/PLANS.md](docs/PLANS.md)、候補の比較は [docs/improvement.md](docs/improvement.md) を必要時に参照する。
