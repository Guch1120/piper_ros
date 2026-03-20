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

## 2026-03-18 対象あり画像ベンチへの切替と ONNX 切り分け
- `scripts/benchmark_val2017.py` に selection filter を追加し、まず PyTorch 基準で `selection_prompt` の検出数が `1` 以上ある画像だけを候補化し、その中からランダム抽出してベンチするようにした。
- `scripts/compare_image_encoder_backends.py` を追加し、同一画像集合に対して PyTorch / ONNX CUDA / ONNX TensorRT 要求時の `backbone_fpn` 差分 (`MAE`, `max abs diff`, `relative MAE`) と検出数を比較できるようにした。
- `sam3/model/sam3_image_processor.py` の ONNX 経路で `SAM3VLBackbone.scalp=1` を落としていたため、FPN level 数が PyTorch と不一致になっていた。ここを修正した。
- 修正前の比較では `result/compare_image_encoder_backends/20260318_172153_prompt_person_res_854_n_4_pool_12_seed_123` にて feature 差分は小さいのに `onnx_cuda_counts=[0,0,0,0]` となっていた。
- 修正後の比較は `result/compare_image_encoder_backends/20260318_172500_prompt_person_res_854_n_4_pool_12_seed_123` に保存し、`torch_counts=[1,1,3,5]`, `onnx_cuda_counts=[1,1,3,5]` で一致した。
- 同比較での ONNX CUDA の `relative MAE` は level 0/1/2 で約 `0.00068 / 0.00117 / 0.00124` と十分小さく、export 自体の数値整合性は概ね保たれていると判断した。
- `onnxruntime` は `TensorrtExecutionProvider` を列挙するが、実ランタイムでは `libnvinfer.so.10` 不足により provider 初期化に失敗し、CPU へフォールバックした。現コンテナ `sam3-ros2-dev` では本物の TensorRT 検証はまだできない。
- 対象あり画像のみを使った PyTorch 基準ベンチは `result/benchmark_val2017/20260318_172158_prompts_person_dog_car_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt` に保存し、`person approx_fps=3.5815`, `avg_set_image=0.2102s`, `avg_object_count=13.60` だった。
- 同条件の ONNX CUDA ベンチは `result/benchmark_val2017/20260318_172902_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_sam3_encoder_res854_onnx_provider_cuda` に保存し、`avg_set_image=0.4977s`, `approx_fps=1.8889` だった。
- 結論として、**精度崩壊の主因は export ではなく ONNX 経路の `scalp` 契約違反だった**。一方で、現状の ONNX CUDA 実装は CPU 往復のため PyTorch より遅く、TensorRT も未検証なので採用不可。

## 2026-03-18 PyTorch 側の image encoder 軽量化: 非 global block skip
- `sam3/model/vitdet.py` に `inference_skip_block_ids` を追加し、推論時だけ指定 block を恒等通過できるようにした。
- `scripts/benchmark_val2017.py` に `--skip-block-count` を追加し、global attention block を除く window block を等間隔でスキップできるようにした。
- 事前の selection filter は常に baseline PyTorch で行い、skip 適用は本ベンチだけに限定するよう修正した。
- baseline は `result/benchmark_val2017/20260318_173153_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`avg_set_image=0.1694s`, `approx_fps=5.0015`, `avg_object_count=13.60` だった。
- `skip-block-count=4` は `result/benchmark_val2017/20260318_173216_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`avg_set_image=0.1494s`, `approx_fps=5.5624`, `avg_object_count=13.20` だった。
- `skip-block-count=8` は `result/benchmark_val2017/20260318_173246_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_8` に保存し、`avg_set_image=0.1304s`, `approx_fps=6.2093`, `avg_object_count=12.80` だった。
- `skip-block-count=10` は `result/benchmark_val2017/20260318_173457_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_10` に保存し、`avg_set_image=0.1170s`, `approx_fps=6.8075`, `avg_object_count=4.80` だった。
- `skip-block-count=12` は `result/benchmark_val2017/20260318_173311_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_12` に保存し、`avg_set_image=0.1098s`, `approx_fps=7.1375`, `avg_object_count=3.40` まで崩れた。
- 結論として、**block skip は PyTorch 内で有効な改善軸であり、現時点では `skip=8` が速度と精度の実用上限候補** である。`skip=12` は速いが精度維持条件を満たさない。

## 2026-03-18 TensorRT 実行環境の構築と再検証
- `sam3-ros2-dev` コンテナ内に `tensorrt-cu12==10.15.1.29`, `tensorrt_cu12_bindings`, `tensorrt_cu12_libs` を pip で導入した。
- TensorRT ライブラリは `/usr/local/lib/python3.10/dist-packages/tensorrt_libs/` に配置されるため、`/etc/ld.so.conf.d/tensorrt.conf` を追加して `ldconfig` を実行し、`libnvinfer.so.10` と `libnvinfer_plugin.so.10` を dynamic linker へ登録した。
- その後の ORT セッション確認では、`result/onnx/sam3_encoder_res854.onnx` に対して `['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']` が active provider になった。
- つまり、**現時点では TensorRT provider は本当に有効化できている**。
- TensorRT 実ベンチは `result/benchmark_val2017/20260318_175132_prompts_person_res_854_n_4_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_sam3_encoder_res854_onnx_provider_tensorrt_skipblocks_off` に保存した。
- この run では `image_encoder_runtime_providers=['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']`, `avg_set_image=0.0954s`, `avg_set_image_forward_image=0.0928s`, `approx_fps=7.7966` だった。
- 一方で `avg_object_count=0.00` で、可視化 `visualizations/person/*.png` も 4 枚保存されたが、検出はすべて 0 件だった。
- 以上より、**TensorRT 未使用が原因だったわけではなく、TensorRT 実行時に feature 表現または最適化結果が壊れている** と判断した。
- `scripts/compare_image_encoder_backends.py` を TensorRT 有効状態で再実行したが、PyTorch / ONNX CUDA / TensorRT を同時に比較しようとして VRAM 16GB 制約に当たり、`FusedMatMul` で約 `886MB` の追加確保に失敗して OOM になった。
- したがって次の切り分けは、比較スクリプトを軽くするか、TensorRT 単独比較に分ける必要がある。
- なお、`visualizations` が空だった旧 run は `--skip-visualizations` 付きで回していたためであり、検出ゼロそのものが原因ではなかった。

## 2026-03-18 TensorRT FP16 が主因であることの確定
- `scripts/compare_image_encoder_backends.py` を順次実行型に作り替え、backend を 1 つずつ評価できるようにした。
- 同スクリプトに `--disable-trt-fp16` と `--skip-detection-counts` を追加し、VRAM 16GB でも TensorRT の数値差分を切り分けられるようにした。
- TensorRT FP16 on の比較結果は `result/compare_image_encoder_backends/20260318_175834_prompt_person_res_854_n_4_pool_12_seed_123_backend_tensorrt_trtfp16_1` に保存した。
- ここでは `avg_torch_count=2.50`, `avg_tensorrt_count=0.00` に加え、feature 差分も `avg_relative_mae` が level 0/1/2 で `1.9686 / 2.5030 / 2.3059` と極端に大きかった。
- よって **TensorRT FP16 engine 自体が image encoder 出力を大きく壊している** と判断した。
- TensorRT FP16 off の feature 差分比較は `result/compare_image_encoder_backends/20260318_180148_prompt_person_res_854_n_4_pool_12_seed_123_backend_tensorrt_trtfp16_0` に保存した。
- こちらでは `avg_relative_mae` が level 0/1/2 で `0.002918 / 0.005380 / 0.006040` と小さく、PyTorch にかなり近い。
- さらに TensorRT FP16 off の実ベンチは `result/benchmark_val2017/20260318_180242_prompts_person_res_854_n_4_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_sam3_encoder_res854_onnx_provider_tensorrt_skipblocks_off` に保存した。
- この run では `image_encoder_runtime_providers=['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']`, `avg_set_image=0.3771s`, `avg_set_image_forward_image=0.3744s`, `approx_fps=2.4587`, `avg_object_count=3.00` だった。
- すなわち **TensorRT FP32 相当では精度は概ね戻るが、PyTorch eager baseline (`5.00 FPS`) より大幅に遅い**。
- 結論として、現状の ONNX/TensorRT 経路は
  - `FP16`: 速いが壊れる
  - `FP32`: 壊れないが遅い
  という状態であり、どちらも採用不可である。

## 2026-03-18 固定画像集合での解像度 sweep
- `scripts/benchmark_val2017.py` に `--selection-resolution` を追加し、画像選定だけを基準解像度で固定できるようにした。
- これにより、`selection_resolution=854` で選んだ同一の 6 枚に対して、評価解像度だけを変えて比較できるようになった。
- 基準 run は `result/benchmark_val2017/20260318_181542_prompts_person_res_854_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` で、`approx_fps=5.1156`, `avg_object_count=13.60` だった。
- `840` は `result/benchmark_val2017/20260318_181607_prompts_person_res_840_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`5.2273 FPS / 13.60` だった。
- `812` は `result/benchmark_val2017/20260318_181630_prompts_person_res_812_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`5.3919 FPS / 13.80` だった。
- `784` は `result/benchmark_val2017/20260318_181658_prompts_person_res_784_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`5.8483 FPS / 13.60` だった。
- `728` は `result/benchmark_val2017/20260318_181736_prompts_person_res_728_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`5.8919 FPS / 13.40` だった。
- `700` は `result/benchmark_val2017/20260318_181808_prompts_person_res_700_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`6.5394 FPS / 13.00` だった。
- `644` は `result/benchmark_val2017/20260318_181835_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`9.9839 FPS / 12.80` だった。
- `616` は `result/benchmark_val2017/20260318_181859_prompts_person_res_616_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`9.6911 FPS / 12.40` だった。
- `588` は `result/benchmark_val2017/20260318_181927_prompts_person_res_588_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、`10.5015 FPS / 10.80` だった。
- この sweep では、`644` までは検出数低下が比較的小さく、`588` で初めて低下幅が目立ち始めた。
- 結論として、**固定画像集合ベースでは `644` がほぼ 10FPS に達しつつ精度劣化も小さい有力候補** である。

## 2026-03-18 可視化保存付き再検証と `644 + skip=4`
- 直前まで `visualizations` が空だった run は、速度優先で `--skip-visualizations` を付けていたためであり、保存バグではなかった。
- その後の run は保存付きで実行し、`result/benchmark_val2017/.../visualizations/<prompt>/*.png` に可視化 PNG が出ることを確認した。
- `644` の複数プロンプト run は `result/benchmark_val2017/20260318_183010_prompts_person_dog_car_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存した。
- ただしこれは `selection_prompt=person` で画像を選んでいるため、`dog` と `car` が 0 件なのは解像度のせいではなく画像集合の偏りである。
- `588` の複数プロンプト run も `result/benchmark_val2017/20260318_183010_prompts_person_dog_car_res_588_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_off` に保存し、同様に PNG を出力した。
- `644 + skip=4` の保存付き run は `result/benchmark_val2017/20260318_183057_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存した。
- この run では `approx_fps=10.8436`, `avg_set_image=0.0702s`, `avg_set_image_forward_image=0.0675s`, `avg_object_count=12.20` だった。
- baseline (`854`, no skip) の `13.60` と比べると、`644 + skip=4` は約 `-10.3%` の検出数低下で 10FPS を超えた。
- 結論として、**現時点の最良候補は `resolution=644 + skip=4`** である。

## 2026-03-18 クラス別画像集合での `644 + skip=4` 確認
- `selection_prompt` を各クラス自身に変え、画像集合の偏りを避けた保存付き benchmark を逐次実行した。
- `cat` の run は `result/benchmark_val2017/20260318_184104_prompts_cat_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`10.5722 FPS / avg_object_count=1.00` だった。
- `bicycle` の run は `result/benchmark_val2017/20260318_184223_prompts_bicycle_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`10.5601 FPS / avg_object_count=0.80` だった。
- `bus` の run は `result/benchmark_val2017/20260318_184352_prompts_bus_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`11.5581 FPS / avg_object_count=1.20` だった。
- いずれも `visualizations/<prompt>/*.png` が保存されており、目視確認可能である。
- 少なくとも `person`, `cat`, `bicycle`, `bus` では、`644 + skip=4` はクラス別画像集合でも 10FPS 前後を維持できている。

## 2026-03-18 追加クラス確認と 20FPS に向けた低解像度探索
- 10FPS 構成の有意性確認を広げるため、逐次実行で `truck`, `chair`, `bottle` も保存付き benchmark を実行した。
- `truck` の run は `result/benchmark_val2017/20260318_185953_prompts_truck_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`11.1266 FPS / avg_object_count=2.00` だった。
- `chair` の run は `result/benchmark_val2017/20260318_190211_prompts_chair_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`11.1699 FPS / avg_object_count=1.80` だった。
- `bottle` の run は `result/benchmark_val2017/20260318_190254_prompts_bottle_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`11.2013 FPS / avg_object_count=0.80` だった。
- これにより、`644 + skip=4` は少なくとも `person`, `cat`, `bicycle`, `bus`, `truck`, `chair`, `bottle` の 7 クラスで 10FPS 超を維持した。
- 次の目標を 20FPS に引き上げ、まずはアーキテクチャ変更ではなく解像度縮小の単純路線を継続した。
- 比較条件は固定し、`selection_resolution=854`, `selection_prompt=person`, `limit=6`, `skip=4`, `autocast on`, `seed=123` のまま評価解像度だけを下げた。
- `560` の run は `result/benchmark_val2017/20260318_190346_prompts_person_res_560_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`12.9192 FPS / avg_object_count=10.60` だった。
- `504` の run は `result/benchmark_val2017/20260318_190413_prompts_person_res_504_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`13.7749 FPS / avg_object_count=5.60` だった。
- `448` の run は `result/benchmark_val2017/20260318_190441_prompts_person_res_448_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` に保存し、`15.4720 FPS / avg_object_count=3.00` だった。
- 低解像度化は速度に効く一方、`504` 以降で検出数低下が急激に大きくなった。
- 結論として、**解像度縮小だけで 20FPS を狙う路線は、現状の精度 proxy では悪化が急すぎる** と判断した。
- `560` が `person` 固有の偶然でないかを確認するため、`cat` でも `result/benchmark_val2017/20260318_190702_prompts_cat_res_560_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` を実行し、`12.9987 FPS / avg_object_count=1.00` を確認した。
- `bus` でも `result/benchmark_val2017/20260319_151348_prompts_bus_res_560_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4` を実行し、`12.7524 FPS / avg_object_count=1.40` を確認した。
- さらに `560 + skip=6` の `person` run を `result/benchmark_val2017/20260318_190812_prompts_person_res_560_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_6` に保存し、`13.6216 FPS / avg_object_count=6.80` だった。
- これは `560 + skip=4` の `12.9192 FPS / 10.60` と比べて、速度上積みが小さい一方で検出数低下が大きく、採用候補にはならなかった。
- `644 + skip=5` の `person` run も `result/benchmark_val2017/20260319_151531_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_5` に保存し、`11.0135 FPS / avg_object_count=10.20` だった。
- これは `644 + skip=4` の `10.8436 FPS / 12.20` と比べて、速度差が小さい一方で検出数低下が大きく、`skip=4` の方が良い境界だと判断した。
- 追加で、ViT の一部ブロックだけ内部を一時的に低解像度化してから元サイズへ戻す実験も 1 本だけ試した。
- `result/benchmark_val2017/20260319_151732_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_poolblocks_4_poolfactor_2` では `10.2957 FPS / avg_object_count=12.20` で、基準の `644 + skip=4` より遅かった。
- 原因は block 内部の補間オーバーヘッドが勝ったためと考えられ、この案は採用せず実装も巻き戻した。

## 2026-03-19 global attention の `k/v` のみを縮小する実験
- block 全体のプーリングは遅かったため、次はより副作用の小さい案として「global attention の `k/v` だけを縮小し、`q` と出力解像度は維持する」経路を `sam3/model/vitdet.py` に実装した。
- `scripts/benchmark_val2017.py` には `--kv-pool-global`, `--kv-pool-stride`, `--kv-pool-global-count` を追加し、global attention block のうち何本へ適用するかをベンチから切り替えられるようにした。
- 構文チェックは Docker 内で `python3 -m py_compile scripts/benchmark_val2017.py sam3/model/vitdet.py` を通した。
- まず 4 本すべての global attention に `stride=2` を掛けた run は `result/benchmark_val2017/20260319_153103_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2` に保存し、`11.2190 FPS / avg_object_count=9.80` だった。
- 速度は伸びたが、`644 + skip=4` 基準の `12.20` からの低下がやや大きかった。
- 次に global attention のうち 2 本だけへ絞った run は `result/benchmark_val2017/20260319_153159_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_2` に保存し、`11.0032 FPS / avg_object_count=11.80` だった。
- さらに 1 本だけへ絞った run は `result/benchmark_val2017/20260319_153302_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_1` に保存し、`11.2911 FPS / avg_object_count=12.20` だった。
- これは `644 + skip=4` の `10.8436 FPS / 12.20` を上回りつつ、検出数 proxy を維持したため、**今回の新しい最良候補** と判断した。
- 参考として `560 + skip=4 + kvpool(global=2, stride=2)` は `result/benchmark_val2017/20260319_153231_prompts_person_res_560_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_2` で `13.0093 FPS / avg_object_count=8.40`、`global=1` は `result/benchmark_val2017/20260319_153331_prompts_person_res_560_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_1` で `13.0101 FPS / avg_object_count=9.60` だった。
- 20FPS にはまだ遠いが、解像度や単純 skip の sweep と違って「速度を上げつつ精度低下をかなり抑える」方向の改善が見え始めた。
- `kvpool(global=1)` の横展開として、`cat` の run を `result/benchmark_val2017/20260319_160039_prompts_cat_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_1` に保存し、`11.1693 FPS / avg_object_count=1.00` を確認した。
- 同様に `bus` の run を `result/benchmark_val2017/20260319_160258_prompts_bus_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_1_kvpoolids_auto` に保存し、`11.2119 FPS / avg_object_count=1.20` を確認した。
- これにより、`kvpool(global=1)` は少なくとも `person`, `cat`, `bus` で 11FPS 前後を維持しつつ、各クラスの検出数 proxy を概ね維持している。
- さらに `scripts/benchmark_val2017.py` に `--kv-pool-global-ids` を追加し、どの global attention block に適用するかを明示指定できるようにした。
- `block_id=31` の run は `result/benchmark_val2017/20260319_160116_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_all_kvpoolids_31` で `4.9840 FPS / avg_object_count=12.20` と極端に遅く、不適切だった。
- `block_id=15` の run は `result/benchmark_val2017/20260319_160158_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_all_kvpoolids_15` で `11.0622 FPS / avg_object_count=11.40` だった。
- `block_id=23` の run は `result/benchmark_val2017/20260319_160227_prompts_person_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_all_kvpoolids_23` で `11.1878 FPS / avg_object_count=12.20` だった。
- 実装上、`kvpool(global=1)` の auto は最初の global block を選ぶため、現時点では **最初の global attention にだけ `k/v` 縮小を掛ける構成が最良** と判断した。
- さらに `bicycle` の run を `result/benchmark_val2017/20260319_160711_prompts_bicycle_res_644_n_6_compile_0_autocast_1_queries_default_textcache_1_layers_default_warmup_1_random_1_seed_123_onnx_off_provider_tensorrt_skipblocks_4_kvpoolglobal_1_kvpoolstride_2_kvpoolcount_1_kvpoolids_auto` に保存し、`11.2161 FPS / avg_object_count=1.00` を確認した。
- `truck` の run も `result/benchmark_val2017/20260319_161006_p_truck_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto` に保存し、`11.3755 FPS / avg_object_count=1.80` を確認した。
- これにより、`kvpool(global=1)` は少なくとも `person`, `cat`, `bus`, `bicycle`, `truck` の 5 クラスで 11FPS 前後を維持した。
- 続いて、window attention 1 本だけへ同じ `k/v` 縮小を掛ける最小実験も追加した。
- `result/benchmark_val2017/20260319_160933_p_person_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvw_s2_kvwc_1_kvwid_auto` では `10.7230 FPS / avg_object_count=12.20` で、基準 `644 + skip=4` よりも遅かった。
- したがって、少なくとも現状の実装では **window attention 側の `k/v` 縮小は有効でない** と判断した。
- 追加で `chair` の run を `result/benchmark_val2017/20260319_161806_p_chair_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto` に保存し、`10.2499 FPS / avg_object_count=1.60` を確認した。
- `bottle` の run は `result/benchmark_val2017/20260319_161905_p_bottle_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto` に保存し、`10.6504 FPS / avg_object_count=0.80` だった。
- これで `kvpool(global=1)` は `person`, `cat`, `bus`, `bicycle`, `truck`, `chair`, `bottle` の 7 クラスで確認した。
- 一方、global `stride=3` の強い縮小も 1 本だけ試した。
- `result/benchmark_val2017/20260319_161904_p_person_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvg_s3_kvgc_1_kvgid_auto` では `4.8133 FPS / avg_object_count=12.00` まで悪化した。
- よって **global attention でも `stride=2` が上限であり、`stride=3` は強すぎて逆効果** と判断した。

## 2026-03-19 global attention の `k/v` head grouping 実験
- `kvpool(global=1, stride=2)` の次候補として、global attention の `k/v` head 数だけを grouped-query attention 風に間引く経路を `sam3/model/vitdet.py` に追加した。
- これに合わせて `scripts/benchmark_val2017.py` に `--kv-head-group-global`, `--kv-head-group-size`, `--kv-head-group-global-count`, `--kv-head-group-global-ids` を追加し、ベンチから block 単位で切り替えられるようにした。
- 構文チェックは Docker 内で `python3 -m py_compile scripts/benchmark_val2017.py sam3/model/vitdet.py` を通した。
- まず現ベスト `644 + skip=4 + kvpool(global=1, stride=2)` に対し、最初の global block 1 本へ `kv_head_group_size=2` を追加した run を `result/benchmark_val2017/20260319_162945_p_person_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto_kvhg_2_kvhgc_1_kvhgid_auto` に保存した。
- 結果は `10.7585 FPS / avg_object_count=12.60` で、検出数 proxy は維持したが、基準の `11.2911 FPS / 12.20` より遅かった。
- 次に適用位置だけを後段 global block へずらし、`block_id=23` へ `kv_head_group_size=2` を掛けた run を `result/benchmark_val2017/20260319_163016_p_person_r_644_n_6_cmp_0_amp_1_q_def_tc_1_ly_def_wu_1_rnd_1_sd_123_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto_kvhg_2_kvhgc_all_kvhgid_23` に保存した。
- こちらは `10.3104 FPS / avg_object_count=12.20` で、速度・検出数ともに基準を上回れなかった。
- よって、**現状の `k/v` head grouping は少なくとも `group_size=2` では有効でなく、不採用** と判断した。
- 今回の結果から、global attention 側の軽量化でも「空間方向の `k/v` 縮小」は有効だが、「head 数の集約」はむしろオーバーヘッドが勝つ可能性が高いことが分かった。

## 2026-03-19 Temporal Feature Reuse 実装と連続フレーム検証
- `Sam3Processor` に `temporal_skip`、`reset_temporal_cache()`、`last_temporal_cache_hit` を追加し、連続フレーム時に image encoder 出力を再利用できるようにした。
- 再利用時に `set_text_prompt()` が cached `backbone_out` を汚染しないよう、テンソル本体は共有しつつ dict/list/tuple だけを複製する `_clone_backbone_out()` を実装した。
- `scripts/benchmark_val2017.py` に `--temporal-skip` を追加し、`summary.json` と `per_image.csv` に `temporal_cache_hit_rate` / `temporal_cache_hit` を保存するようにした。
- 連続フレーム検証には `assets/videos/0001` を使い、`--sequential-sample --disable-selection-filter` で先頭 12 フレームを順番に処理した。
- baseline として `644 + skip=4 + kvpool(global=1, stride=2) + temporal_skip=1` を `result/benchmark_val2017/20260319_180506_p_person_r_644_n_12_cmp_0_amp_1_q_def_tc_1_ly_def_wu_2_tmp_1_rnd_0_sd_42_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto` に保存した。
- この baseline は `avg_set_image=0.0740s`, `avg_set_image_forward_image=0.0702s`, `avg_object_count=2.50`, `approx_fps=10.3132` だった。
- 続いて `temporal_skip=2` を `result/benchmark_val2017/20260319_180532_p_person_r_644_n_12_cmp_0_amp_1_q_def_tc_1_ly_def_wu_2_tmp_2_rnd_0_sd_42_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto` に保存した。
- `temporal_cache_hit_rate=0.5000` で、`avg_set_image=0.0367s`, `avg_set_image_forward_image=0.0329s`, `avg_object_count=2.60`, `approx_fps=17.0369` まで改善した。
- さらに `temporal_skip=3` を `result/benchmark_val2017/20260319_180602_p_person_r_644_n_12_cmp_0_amp_1_q_def_tc_1_ly_def_wu_2_tmp_3_rnd_0_sd_42_onnx_off_prov_tensorrt_skip_4_kvg_s2_kvgc_1_kvgid_auto` に保存した。
- `temporal_cache_hit_rate=0.7000` で、`avg_set_image=0.0246s`, `avg_set_image_forward_image=0.0206s`, `avg_object_count=2.80`, `approx_fps=21.0785` となり、**連続フレーム条件では 20FPS を超えた**。
- ただしこの結果は静止画ランダム集合ではなく短い動画列での値であり、精度 proxy として `avg_object_count` だけでは temporal lag を完全には測れない。次段では可視化確認と、より長い連続列での安定性確認が必要である。
