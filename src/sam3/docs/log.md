# 実行ログ

## 2026-03-17 自律運用文書の整備と初回ループ開始
- `AGENTS.md` を contributor guide ではなく、自律実行向けのランブックに再構成した。
- `docs/plan.md` を ExecPlan 形式へ拡張し、目標、マイルストーン、検証戦略、判断履歴を追加した。
- `docs/improvement.md` に初回ループの改善方針として「まず計測性を入れる」を記載した。
- `piper-humble-dev` コンテナ内に `/ros2_ws/src/sam3` が存在することを確認した。
- `run_sam3_groceries.py` に段階別タイマーを追加し、Docker 内で `python3 run_sam3_groceries.py` を実行した。
- 実測値は `build_model=13.8854s`, `load_image=0.0053s`, `set_image=0.6717s`, `set_text_prompt=0.4193s`, `plot_results=0.2459s`, `save_figure=0.3238s` だった。
- 可視化を除く概算は `0.9166 FPS` で、5FPS 目標とのギャップは大きい。
- `sam3/model/sam3_image_processor.py` を確認した結果、`set_image` と `set_text_prompt` には既に `@torch.inference_mode()` が付いていたため、この方向の改善は優先度を下げた。
- 次の実行は、ウォームアップ後の複数回計測を追加し、定常性能を切り分ける。

## 2026-03-17 データセット利用方針の更新
- `data/` 配下に `train2017` と `val2017` を確認し、全体で約 `19GB / 123287 files` だった。
- ユーザー共有の制約として、学習時に使える VRAM は 16GB であることを記録した。
- 当面は学習着手よりも、`data/val2017` の固定サブセットを使った推論ベンチ整備を優先する。

## 2026-03-17 複数画像ベンチと追加仮説の検証
- `sam3/model/sam3_image_processor.py` に任意のプロファイル機能を追加し、`set_image` の内訳を観測できるようにした。
- `scripts/benchmark_val2017.py` を追加し、`data/val2017` の固定サブセットを使って複数画像平均のベンチを取れるようにした。
- `python3 scripts/benchmark_val2017.py --limit 6 --prompt person --resolution 1008` を Docker 内で実行した。
- 結果は `avg_set_image=0.3854s`, `avg_set_text_prompt=0.0912s`, `avg_set_image_forward_image=0.3808s`, `approx_fps=2.0982` だった。
- `set_image` の遅延は前処理ではなく `forward_image` に集中していることを確認した。
- `--resolution 768` の実験は `sam3/model/vitdet.py` 内で rotary embedding の shape assertion により失敗し、単純な低解像度化は不可だった。
- `--compile-image-backbone` の実験は CUDAGraph 出力上書きエラーで途中失敗し、現状では採用不可と判断した。
- `sam3.perflib.compile.compile_wrapper` を使って `--compile-image-backbone` を再実験し、`max-autotune-no-cudagraphs` では完走した。
- ただし実測は `48.54s`, `27.15s`, `0.43s`, `0.42s`, `0.42s`, `0.40s` と初回コンパイル負荷が極端に重く、定常値も eager と同等だった。
- compile 系は少なくとも今回の単一形状・少数反復ベンチでは改善にならず、不採用とした。
- `scripts/benchmark_val2017.py` を更新し、`result/benchmark_val2017/<run_name>/` に数値サマリと可視化 PNG を保存するようにした。
- 直近の保存先は `result/benchmark_val2017/20260317_023441_prompt_person_res_1008_n_6_compile_0` である。
- 生成物は `summary.json`, `per_image.csv`, `visualizations/*.png` で、目視確認できる状態になった。
- 追加調査で、`build_sam3_image_model` の画像バックボーンは `img_size=1008`, `embed_dim=1024`, `depth=32`, `num_heads=16` に固定されていることを確認した。

## 2026-03-17 複数プロンプト化と mixed precision の導入
- `scripts/benchmark_val2017.py` を拡張し、`--prompts person,dog,car` のように複数プロンプトを一度に評価できるようにした。
- `result/benchmark_val2017/20260317_024206_prompts_person_dog_car_res_1008_n_6_compile_0_autocast_0` に eager の複数プロンプト結果を保存した。
- eager の 6 枚平均は `avg_set_image=0.3923s` で、`person=2.0453FPS`, `dog=2.1029FPS`, `car=2.1019FPS` だった。
- `Sam3Processor` に `autocast(bfloat16)` オプションを追加し、CUDA では既定で有効になるように変更した。
- `result/benchmark_val2017/20260317_024236_prompts_person_dog_car_res_1008_n_6_compile_0_autocast_1` に autocast の複数プロンプト結果を保存した。
- autocast 有効時の 6 枚平均は `avg_set_image=0.2179s` で、`person=3.5526FPS`, `dog=3.8708FPS`, `car=3.8646FPS` まで改善した。
- `run_sam3_groceries.py` 再計測でも `avg_set_image=0.1851s`, `avg_set_text_prompt=0.0386s`, `approx_fps=4.4715` を確認した。
- 現時点の最良改善は compile ではなく mixed precision であり、次段はこれを基準に追加の構成軽量化を探る。

## 2026-03-17 ウォームアップ除外と追加の構成簡略化比較
- `scripts/benchmark_val2017.py` に `--warmup-images` を追加し、集計から初回画像を除外できるようにした。
- `result/benchmark_val2017/20260317_024938_prompts_person_dog_car_res_1008_n_6_compile_0_autocast_1_queries_default_textcache_0_layers_default_warmup_1` を基準結果として保存した。
- ウォームアップ 1 枚除外後の 5 枚平均は `avg_set_image=0.2054s`、`person=4.0121FPS`, `dog=4.0204FPS`, `car=4.0337FPS` だった。
- `query_limit=100` と `50` はそれぞれ `result/benchmark_val2017/20260317_024551_...queries_100` と `result/benchmark_val2017/20260317_024550_...queries_50` に保存し、いずれも悪化したため不採用とした。
- `decoder_layers=3` は `result/benchmark_val2017/20260317_024957_prompts_person_dog_car_res_1008_n_6_compile_0_autocast_1_queries_default_textcache_0_layers_3_warmup_1` に保存し、`person=3.9409FPS` と基準を下回ったため不採用とした。
- 現時点の最良構成は `autocast on`, `query_limit default`, `decoder_layers default`, `warmup_images=1` である。

## 2026-03-17 ランダムサンプリングとボトルネック定量化
- `visualizations` が空に見えた原因を確認したところ、非検出ではなく `--save-visualizations` を付けていないランが混在していたためだった。
- `scripts/benchmark_val2017.py` を更新し、可視化保存を既定で有効、画像抽出をランダムサンプリング既定、選ばれた画像一覧を `summary.json` に保存するようにした。
- さらに `bottleneck_breakdown` を `summary.json` と標準出力に追加し、各段の比率を出すようにした。
- 最新ランは `result/benchmark_val2017/20260317_032834_prompts_person_dog_car_res_1008_n_6_compile_0_autocast_1_queries_default_textcache_0_layers_default_warmup_1_random_1_seed_123` に保存した。
- このランでは、`selected_images` はランダムに選ばれた 6 枚で、可視化 PNG も `visualizations/person`, `visualizations/dog`, `visualizations/car` に保存された。
- ウォームアップ 1 枚除外後の `person` では `avg_set_image=0.2049s`, `avg_set_text_prompt=0.0441s`, `approx_fps=4.0156` だった。
- 比率は `set_image_total=82.3%`, `set_image_forward_image=80.6%`, `set_text_total=17.7%`, `set_text_forward_text=2.9%`, `set_text_forward_grounding=14.7%` で、主要ボトルネックが image encoder であることを数値で確認した。

## 2026-03-17 可変解像度 RoPE 修正と 5FPS 達成
- `sam3/model/vitdet.py` の RoPE 周波数計算を動的化し、入力トークン数が変わっても global attention で落ちないようにした。
- 同条件（`prompts=person,dog,car`, `autocast on`, `warmup_images=1`, `random sample seed=123`）で `896`, `854`, `840` を比較した。
- `896` の結果は `result/benchmark_val2017/20260317_035116_prompts_person_dog_car_res_896_n_6_compile_0_autocast_1_queries_default_textcache_0_layers_default_warmup_1_random_1_seed_123` に保存し、`person=4.9489FPS`, `avg_object_count=8.40` だった。
- `840` の結果は `result/benchmark_val2017/20260317_035213_prompts_person_dog_car_res_840_n_6_compile_0_autocast_1_queries_default_textcache_0_layers_default_warmup_1_random_1_seed_123` に保存し、`person=5.0557FPS`, `avg_object_count=6.20` だった。
- `854` の結果は `result/benchmark_val2017/20260317_035302_prompts_person_dog_car_res_854_n_6_compile_0_autocast_1_queries_default_textcache_0_layers_default_warmup_1_random_1_seed_123` に保存し、`person=5.2750FPS`, `avg_object_count=7.00` だった。
- `854` は 5FPS を超えつつ、`840` より検出数の落ち幅が小さかったため、現時点の最良トレードオフとして採用した。
- `run_sam3_groceries.py` の既定推論解像度を `SAM3_IMAGE_RESOLUTION=854` 相当に変更し、Docker 内再計測で `avg_set_image=0.1554s`, `avg_set_text_prompt=0.0286s`, `approx_fps=5.4353` を確認した。
