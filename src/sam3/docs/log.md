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

## 2026-03-17 ONNX/TensorRT image encoder の実装と評価
- `scripts/export_sam3_encoder_onnx.py` を追加し、`SAM3` の `vision_backbone` を固定解像度 `854` 向け ONNX として export できるようにした。
- `sam3/model/sam3_image_processor.py` に ONNX Runtime 経路を追加し、`set_image` の image encoder だけを ORT/TensorRT EP へ切り替えられるようにした。
- `scripts/benchmark_val2017.py` に `--image-encoder-onnx`, `--onnx-provider`, `--onnx-trt-cache-dir` を追加し、PyTorch と ONNX の on/off 比較を同一条件で回せるようにした。
- `sam3/model/vitdet.py` には ONNX export 用の RoPE 実数演算分岐を追加し、`view_as_complex` 非対応を回避した。
- Docker 内では `onnxruntime-gpu`, `onnxscript` を導入し、`onnx==1.18.0`, `ml_dtypes==0.5.0` に調整して export を通した。
- export 成果物は `result/onnx/sam3_encoder_res854.onnx` に保存した。
- PyTorch 基準の再計測は `result/benchmark_val2017/20260317_042701_prompts_person_dog_car_res_854_n_4_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt` に保存し、`person=5.3579FPS`, `avg_set_image=0.1581s`, `avg_set_image_forward_image=0.1544s`, `avg_object_count=11.00` だった。
- ONNX/TensorRT 経路の初回比較は `result/benchmark_val2017/20260317_042957_prompts_person_dog_car_res_854_n_2_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_sam3_encoder_res854_onnx_provider_tensorrt` に保存し、`person=8.9549FPS`, `avg_set_image=0.0883s`, `avg_set_image_forward_image=0.0860s` まで改善した。
- ただし同じ ONNX/TensorRT ランでは `person/dog/car` すべて `avg_object_count=0.00` となり、検出精度が崩壊した。
- 結論として、**速度面では 9FPS 近辺まで到達可能性が見えたが、現状の export/実行経路は精度維持条件を満たさないため不採用** とした。

## 2026-03-20 ROS1/ROS2 wrapper added
- Added a new `sam3_ros` package with dual-stack runtime selection (`ros1` / `ros2` / `auto`).
- Exposed image, prompt, annotated image, masks, boxes, and scores topics as ROS parameters and CLI flags.
- Added a `sam3-ros` console script entry point in `pyproject.toml`.
- Syntax-check passed with `python3 -m py_compile` for the new wrapper files.


## 2026-03-20 SAM3 ROS wrapper updated
- Added a separate `sam3_dual_ros` ROS package namespace to avoid collisions with the existing `sam3_ros` package.
- Added ROS2 and ROS1 launch files under `sam3_dual_ros/launch/`.
- `--backend auto` follows a best-effort order: `ROS_VERSION`, then ROS2, then ROS1; explicit backend selection is safer when both stacks may be installed.

## 2026-03-20 ROS 実行差分の確認と可視化経路の修正
- `sam3_dual_ros` / `sam3_ros` の ROS2 ランタイムでローカル checkpoint (`/ros2_ws/src/sam3/sam3.pt`) を使った実行を確認し、ノード起動とテキストプロンプト購読が動作することを確認した。
- Hugging Face gated repo への依存を避けるため、実運用では `--no-load-from-hf --checkpoint-path /ros2_ws/src/sam3/sam3.pt` を付ける前提になった。
- `annotated_topic` にセグメントが重ならない原因は、SAM3 が返す `masks` の shape が `(N,1,H,W)` 系でも `sam3_ros/segmenter.py` 側が 2 次元マスクへ正規化せず、そのまま overlay 描画で捨てていたことだった。
- `sam3_ros/segmenter.py` を修正し、mask を `squeeze()` して 2 次元 bool 配列へ正規化した上で overlay と `/sam3/masks` publish に使うようにした。
- `sam3_ros/bridge.py` も修正し、`mono8` publish 前に mask を 2 次元 `uint8` に正規化するようにした。
- `docs/log.md` の 8.95FPS 近辺は ONNX/TensorRT image encoder の参考値だが、`avg_object_count=0.00` で精度崩壊のため採用不可であることを再確認した。
- `run_sam3_groceries.py` と `val2017` ベンチの 5FPS 台は静止画・ウォームアップ後・`set_image + set_text_prompt` 中心の計測であり、ROS 実行時の `cv_bridge` 変換、PIL 化、overlay 合成、mask/boxes/scores publish、callback 待ち時間は含まれていない。
- 実運用では体感 1FPS 前後だったため、ベンチ値と ROS 実測値に大きな差があることを正式に記録する。少なくとも現時点では「10FPS 達成」とは言えない。
- `sam3_ros/ros2_node.py` に 30 フレーム平均の runtime profiler を追加し、`convert`, `segment`, `annotated`, `mask`, `boxes`, `scores`, `total` をログ出力できるようにした。
- 同時に、subscriber がいない output topic については annotated image 生成と publish を省略するようにし、ROS 実運用時の無駄な callback コストを削減する変更を入れた。
- 次サイクルでは、この runtime profiler の実測値を基準に ROS 実行で 10FPS を阻害している段を特定し、必要なら publish 経路と image encoder 経路を別々に最適化する。

## 2026-03-20 ROS 解像度 540 の試験
- RTX 2070 環境では、autocast dtype を GPU 世代で自動選択するように変更し、Turing 世代では `float16` を使うようにした。
- 起動時に `SAM3 runtime config` を出すようにし、`device`, `resolution`, `autocast`, backend, text cache, query limit, decoder layers を確認できるようにした。
- `--resolution 540` の ROS 実行では、30 フレーム平均で `total=0.2359s (4.24 FPS)`、90 フレーム平均で `total=0.2288s (4.37 FPS)` だった。
- 内訳は 90 フレーム平均で `segment=0.2250s`, `set_image=0.1440s`, `set_text=0.0479s`, `fwd_image=0.1409s`, `fwd_grounding=0.0472s`, `overlay=0.0208s` だった。
- `540` への縮小は `728` より明確に高速だが、ROS 実運用で 10FPS にはまだ届かない。主因は依然として image encoder (`fwd_image`) である。
- 少なくとも RTX 2070 では、解像度低減だけで 10FPS に到達する見込みは薄く、次段はさらに低解像度を試すか、image encoder の別経路を再評価する必要がある。


## 2026-03-20 ROS 解像度 384 の試験と次の仮説
- ユーザー実測の ROS 実運用では、`--resolution 384` で 90 フレーム平均 `total=0.1621s (6.17 FPS)` を確認した。
- 内訳は `segment=0.1596s`, `set_image=0.1035s`, `set_text=0.0441s`, `fwd_image=0.1003s`, `fwd_grounding=0.0435s` で、支配項は依然として image encoder、その次が grounding だった。
- `540` 比では改善しているが、`6 FPS` 前後で頭打ちが見え始めており、解像度を下げるだけで `10 FPS` に到達する見込みは薄い。
- 直近の確認で、現在の `piper-humble-dev` には `onnxruntime` が入っておらず、過去の `result/onnx/*.onnx` 成果物も `/ros2_ws/src/sam3` には存在しなかった。したがって ONNX/TensorRT 再評価は、まず環境復元が必要である。
- 次の小変更として、PyTorch 経路に `channels_last` と CUDA runtime 自動設定を追加した。具体的には、CUDA 時に `vision_backbone` と入力テンソルを `channels_last` 化し、`cudnn.benchmark=True`、Ampere 以降では `TF32` を自動で有効にするようにした。
- ROS CLI には `--channels-last` / `--no-channels-last` を追加し、起動ログにも `channels_last=<bool>` を出すようにした。複数 GPU 世代の PC で切り替えと診断がしやすくなった。
- 変更後の `sam3_ros` / `sam3_dual_ros` は Docker 内で `python3 -m py_compile` と `colcon build --packages-select sam3_ros sam3_dual_ros` を通した。
- 次の計測は `resolution=384` を維持したまま `channels_last` の on/off 差分を見る。効かなければ、さらに低解像度化か ONNX 環境の復元に進む。
