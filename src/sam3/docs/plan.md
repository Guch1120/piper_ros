# 目的と全体像
- SAM3 はテキストプロンプトで対象物を指示でき、検出精度も高い。一方で現状は 1FPS 未満であり、実運用には遅い。
- 主目標は `run_sam3_groceries.py` 相当の処理を 5FPS へ近づけること。
- 制約は、速度改善後も検出数とセグメント品質を大きく悪化させないこと、変更を小さく可逆に保つこと、Docker 内で再現できること。

## 現在判明していること

### 確認済みの事実
- 自律実行ルールは `docs/AGENT.md` にあり、複雑な作業では ExecPlan 運用が必須である。
- Docker 実行の不変条件は `docs/architecture_rule.md` にあり、作業コンテナは `piper-humble-dev`、コンテナ内ワークスペースは `/ros2_ws` である。
- `run_sam3_groceries.py` は単発推論スクリプトで、モデル構築、画像読み込み、`set_image`、`set_text_prompt`、可視化保存を 1 回ずつ順に実行している。
- 初回計測では `build_model: 13.8854s`、`set_image: 0.6717s`、`set_text_prompt: 0.4193s`、`plot_results: 0.2459s`、`save_figure: 0.3238s` だった。
- 可視化を除いた `set_image + set_text_prompt` の概算は約 `0.92FPS` で、目標の 5FPS には遠い。
- `sam3/model/sam3_image_processor.py` 側の `set_image` と `set_text_prompt` には既に `@torch.inference_mode()` が付いている。
- ウォームアップ後の反復計測では `avg_set_image: 0.3792s`、`avg_set_text_prompt: 0.0817s`、概算 `2.17FPS` だった。
- 定常状態でも `set_image` が `set_text_prompt` より明確に重く、次の切り分け対象として妥当である。
- `data/` 配下に COOC データセット相当の画像群があり、少なくとも `data/train2017` と `data/val2017`、合計約 `19GB / 123287 files` を確認した。
- 利用可能な計算資源は VRAM 16GB であり、大規模学習は負荷面の制約を受ける。
- `data/val2017` の先頭 6 枚、`prompt=person`、`resolution=1008` の平均ベンチでは `avg_set_image=0.3854s`、`avg_set_text_prompt=0.0912s`、概算 `2.10FPS` だった。
- `set_image` の内訳は `to_device=0.0022s`、`transform=0.0024s`、`forward_image=0.3808s` で、遅延の大半は `forward_image` に集中している。
- `resolution=768` では `sam3/model/vitdet.py` の rotary embedding 形状前提により `AssertionError` が発生した。
- `torch.compile(model.backbone.forward_image)` 実験は CUDAGraph の上書きエラーで継続実行できず、現状のままでは採用できない。
- `sam3.perflib.compile.compile_wrapper(..., mode=\"max-autotune-no-cudagraphs\")` による再実験は完走したが、初回 2 枚に大きなコンパイルコストが乗り、定常値も eager と同等で優位性は見られなかった。
- ベンチスクリプトは `result/benchmark_val2017/<run_name>/` に `summary.json`, `per_image.csv`, `visualizations/*.png` を保存するようになった。
- 現行の `build_sam3_image_model` は `ViT(img_size=1008, embed_dim=1024, depth=32, num_heads=16)` を前提としており、軽量バックボーン選択肢は現時点で公開されていない。
- `person,dog,car` の複数プロンプトでもベンチを回せるようになり、結果をプロンプト別に保存できる。
- `Sam3Processor` に CUDA 時の `autocast(bfloat16)` を導入した結果、`val2017` 6 枚平均で `avg_set_image: 0.3923s -> 0.2179s`、`person` の概算 `2.05FPS -> 3.55FPS` まで改善した。
- `run_sam3_groceries.py` の反復計測でも `avg_set_image=0.1851s`, `avg_set_text_prompt=0.0386s`, `approx_fps=4.4715` を確認した。
- ベンチ集計から初回ウォームアップ画像を除外するようにした結果、`val2017` の 5 枚平均では `avg_set_image=0.2054s`、`person/dog/car` いずれも概算 `約4.0 FPS` まで改善した。
- 推論時クエリ数削減 (`query_limit=100/50`) は改善せず、むしろ遅くなった。
- 推論時デコーダ層削減 (`decoder_layers=3`) も `約4.01 FPS -> 約3.94 FPS` と改善しなかった。
- ベンチ画像の抽出はランダム化され、run ごとに `selected_images` が `summary.json` に残るようになった。
- 可視化保存は既定で有効になり、空の `visualizations/` は「保存しないラン」が原因で、非検出そのものが原因ではないと確認した。
- ランダムサンプル (`seed=123`) の 5 枚平均では、`person` の end-to-end に対して `set_image` が `82.3%`、その内 `forward_image` が `80.6%` を占めた。`set_text_prompt` は `17.7%`、その内 text encoder は `2.9%`、grounding は `14.7%` だった。
- `vitdet.Attention` の RoPE 周波数を動的再計算するように修正したことで、`resolution=896/854/840` のベンチがクラッシュせず実行できるようになった。
- 同一ランダムサンプル (`seed=123`) での比較では、`896` で `person=4.9489FPS`, `avg_object_count=8.40`、`854` で `person=5.2750FPS`, `avg_object_count=7.00`、`840` で `person=5.0557FPS`, `avg_object_count=6.20` だった。
- `854` は 5FPS を超えつつ、`840` より検出数の落ち幅が小さいため、現時点の最良トレードオフ候補である。
- `run_sam3_groceries.py` は既定推論解像度を `854` に切り替え、反復計測で `approx_fps=5.4353` を確認した。
- `scripts/export_sam3_encoder_onnx.py` により `result/onnx/sam3_encoder_res854.onnx` の export に成功した。
- ONNX/TensorRT image encoder 経路では `avg_set_image=0.0883s`, `person=8.95FPS` まで改善したが、`avg_object_count=0.00` で精度維持に失敗した。
- したがって、ONNX/TensorRT は速度面では有望だが、現状の export 実装のままでは採用できない。
- `scripts/benchmark_val2017.py` は対象あり画像のみを候補化する selection filter を持ち、空画像を混ぜずにベンチできるようになった。
- `scripts/compare_image_encoder_backends.py` により、PyTorch / ONNX CUDA / ONNX TensorRT 要求時の feature 差分と検出数を同一画像集合で比較できる。
- ONNX のゼロ検出は export 破綻ではなく、ONNX 経路で `SAM3VLBackbone.scalp=1` を落としていた実装ミスが原因だった。修正後は ONNX CUDA の検出数が PyTorch と一致する。
- 現コンテナ `sam3-ros2-dev` では `libnvinfer.so.10` 不足により TensorRT provider が起動できず、実 TensorRT 比較はまだ未完了である。
- 対象あり画像・`person` 基準の baseline は `approx_fps=5.0015`, `avg_object_count=13.60` だった。
- PyTorch 内の非 global block skip は、`skip=4` で `5.5624FPS / avg_object_count=13.20`、`skip=8` で `6.2093FPS / avg_object_count=12.80`、`skip=10` で `6.8075FPS / avg_object_count=4.80`、`skip=12` で `7.1375FPS / avg_object_count=3.40` だった。
- したがって現時点の次候補は、TensorRT 環境整備が無い前提では `skip=8` 周辺の微調整、または block skip と解像度縮小の併用探索である。
- その後 TensorRT 実行環境自体は整備でき、active provider が本当に `TensorrtExecutionProvider` になった。
- しかし実 TensorRT ベンチでも `approx_fps=7.7966` に対して `avg_object_count=0.00` であり、精度崩壊は再現した。
- よって現在の課題は「TensorRT が使えていない」ことではなく、「TensorRT 実行時の数値差分が致命的」なことである。
- 追加の切り分けで、TensorRT FP16 on は feature 差分自体が極端に大きく、主因が `trt_fp16_enable` 周辺にあることを確認した。
- TensorRT FP16 off では feature 差分は小さくなり、検出数もある程度戻るが、`approx_fps=2.4587` と遅いため実用にならない。
- したがって現状の TensorRT 路線は、速度と精度を同時に満たせていない。
- 一方、固定画像集合を `selection_resolution=854` で揃えた解像度 sweep では、`644` で `9.9839 FPS / avg_object_count=12.80`、`588` で `10.5015 FPS / avg_object_count=10.80` まで到達した。
- これにより、10FPS 目標は TensorRT ではなく **純 PyTorch + 解像度縮小** でもかなり近いことが分かった。
- さらに `644 + skip=4` の保存付き run で `10.8436 FPS / avg_object_count=12.20` を確認した。
- したがって、10FPS 目標は **純 PyTorch + 解像度縮小 + 軽い block skip** で既に達成圏内ではなく、達成済みに近い状態である。
- クラス別画像集合でも、`cat=10.57 FPS`, `bicycle=10.56 FPS`, `bus=11.56 FPS` を確認した。

### 未確認の仮説
- 初回の遅さの大半はモデル初期化と重みロードであり、連続推論では `set_image` と `set_text_prompt` の比率が支配的になる可能性がある。
- `plot_results` と `plt.savefig` はデモ用途としては有用だが、FPS 評価では分離すべき固定コストである。
- 単発計測には CUDA 初期化や初回カーネル準備が混ざるため、ウォームアップ後の定常値はやや改善する可能性がある。
- 真の支配項は `set_image` 内の画像特徴抽出やリサイズ系前処理であり、テキスト側より画像側の最適化余地が大きい可能性がある。
- ウォームアップだけで 2FPS 台までは回復するが、5FPS 達成には画像エンコーダ側でさらに約 2 倍以上の短縮が必要である。
- 解像度を単純に落とす案は、現行実装では入力サイズ不変条件のためそのまま適用できない。
- `torch.compile` は理論上候補だが、少なくとも現行の `forward_image` 経路では安全に反復実行できない可能性が高い。
- `no-cudagraphs` compile は安全性は改善したが、今回のワークロードでは速度改善より初期コストの悪化が支配的だった。
- 5FPS に近づくには、局所最適化だけでなく、軽量バックボーンや構成変更を含むアーキテクチャ改良が必要になる可能性が高い。
- mixed precision は小変更で有効だったが、5FPS 達成にはなお追加の改善が必要である。
- 5FPS 目標は、autocast と入力解像度 `854` の組み合わせで達成した。
- 一方で、クエリ数やデコーダ層数を単純に削るだけでは有効な改善にならなかった。
- したがって主要ボトルネックは、推測どおりではあるが数値上も `image encoder` 経路である。
- ONNX/TensorRT は image encoder の時間をほぼ半減させる可能性がある一方、現状は export か TensorRT 最適化のどこかで特徴表現が壊れている可能性が高い。
- ONNX CUDA は `session.run()` の CPU 往復が大きく、TensorRT が使えない限り PyTorch より遅くなる。
- TensorRT を有効化しても、現状の engine では検出が 0 件になるため、そのままでは採用できない。
- TensorRT FP16 off なら feature は近いが遅すぎるため、仮に精度が戻っても 10FPS 目標の本命にはなりにくい。
- 解像度縮小は少なくとも `644` までは劣化が緩く、`588` 付近から低下が目立つ。
- `644 + skip=4` は `588` 単独より検出数の落ち方が緩く、速度も 10FPS を超えた。
- `644 + skip=4` は単に `person` だけの偶然ではなく、少なくとも複数クラスで 10FPS 前後を維持できている。
- 非 global block skip は 8 本前後までなら精度劣化が比較的小さく、image encoder の主要ボトルネックをそのまま削減できる。
- block skip を増やしすぎると、軽い画像では保っても密な画像で検出数が急減する。

## マイルストーン
1. ベースライン計測
完了条件: Docker 内で現行スクリプトを再現実行し、モデル初期化、前処理、推論、可視化の時間内訳を取得する。
2. ボトルネック切り分け
完了条件: 5FPS 達成を阻害する主因を 1 つ以上特定し、改善仮説を `docs/improvement.md` に落とす。
3. 最小改善の実装
完了条件: 無関係な設計変更なしで、計測可能な小変更を 1 件実装する。
4. 再計測と判断
完了条件: 速度差分と精度影響を比較し、採用・見送りの判断を `docs/log.md` に残す。

## 検証戦略
- まずは `run_sam3_groceries.py` を Docker 内で実行し、段階別計測を入れる前後で挙動を比較する。
- 指標は総実行時間、推論区間時間、概算 FPS、検出数、保存画像の見た目を使う。
- 可視化保存は推論本体と分離して扱い、FPS 議論に混ぜない。
- 次段では `data/val2017` から小さな固定サブセットを使い、単一画像の偶然差ではなく複数画像平均で評価する。
- 学習を試す場合でも、16GB VRAM を超えないように小バッチ、低解像度、少数ステップで限定する。

## 進捗
- 2026-03-17: `AGENTS.md` を自律運用向けに再構成した。
- 2026-03-17: `piper-humble-dev` コンテナ内に `/ros2_ws/src/sam3` が存在することを確認した。
- 2026-03-17: `run_sam3_groceries.py` に段階別計測を追加し、Docker 内でベースラインを取得した。
- 2026-03-17: 同スクリプトに反復ベンチマークを追加し、ウォームアップ後の定常値を取得した。
- 2026-03-17: `Sam3Processor` にプロファイル機能を追加し、`scripts/benchmark_val2017.py` で複数画像平均ベンチを実行した。
- 2026-03-17: `compile_wrapper` を使った `forward_image` compile 実験を行い、不採用判断まで完了した。
- 2026-03-17: ベンチ結果を `result/benchmark_val2017/` 配下へ保存する仕組みを追加した。
- 2026-03-17: `autocast(bfloat16)` を推論経路へ導入し、現行ベースラインを大きく短縮した。
- 2026-03-17: ベンチにウォームアップ除外を導入し、比較の再現性を改善した。
- 2026-03-17: クエリ数削減とデコーダ層削減を比較し、不採用判断まで完了した。
- 2026-03-17: ベンチのランダムサンプリング、可視化既定保存、ボトルネック比率出力を追加した。
- 2026-03-17: RoPE の動的再計算を入れて可変解像度化を成立させ、`854` で 5FPS 超を確認した。
- 2026-03-17: ONNX export と ORT/TensorRT image encoder 経路を実装し、速度改善と精度崩れの両方を確認した。
- 2026-03-18: 対象あり画像のみを使う selection filter と backend 差分比較スクリプトを追加した。
- 2026-03-18: ONNX ゼロ検出の主因が `scalp=1` 抜けであることを特定し、ONNX CUDA の検出数一致まで確認した。
- 2026-03-18: TensorRT provider が現コンテナでは使えないことを確認した。
- 2026-03-18: PyTorch 内の非 global block skip を実装し、`skip=8` で `6.21FPS` まで改善した。
- 2026-03-18: TensorRT ライブラリを導入して provider を有効化し、実 TensorRT ベンチで再び精度崩壊することを確認した。
- 2026-03-18: TensorRT FP16 が feature を壊していること、FP16 off では遅すぎることまで確認した。
- 2026-03-18: 固定画像集合ベースの解像度 sweep を行い、`644` が有力候補、`588` で 10FPS 超だが精度低下が大きくなることを確認した。
- 2026-03-18: `644 + skip=4` で `10.84 FPS / avg_object_count=12.20` を確認した。
- 2026-03-18: `cat`, `bicycle`, `bus` の各 selection prompt でも `644 + skip=4` が 10FPS 前後を維持することを確認した。

## 発見と驚き
- リポジトリ直下の `AGENTS.md` は contributor guide よりも、自律実行のランブックとして使う方が実態に合っている。
- 既存の計画・改善・ログ文書は存在するが、内容はまだ骨組みだけで、計測結果が未記録である。
- 当初の想定どおりモデル構築は重いが、定常推論部だけ見てもまだ 1FPS 未満であり、初期化だけを削っても 5FPS には届かない。
- `torch.inference_mode()` は既に入っていたため、単純な no-grad 化では改善しない。
- 反復計測により、初回単発値だけを見るより定常性能はかなり良いことが分かったが、それでも目標には未達である。
- `set_image` の前処理コストはごく小さく、改善余地の中心は画像バックボーン本体であることが確認できた。
- 任意解像度化と `torch.compile` は、それぞれ形状制約と実行時エラーで直ちには使えなかった。
- `compile_wrapper` により完走自体は可能になったが、ウォームアップ込み・定常値ともに eager を上回れなかった。
- ONNX/TensorRT は 9FPS 近辺まで見えたが、検出数 0 件に崩れたため「速いが不正確」という別の失敗モードが出た。
- 実際には ONNX export 自体はかなり近く、壊れていたのは runtime 側の feature 契約だった。
- 画像に対象が本当に存在する条件で測ると、空画像混在時より FPS は下がるが、精度判断としてはこちらが妥当である。
- block skip は想定以上に効いたが、`skip=12` では一気に検出数が崩れ、速度と精度の境界が比較的鋭い。
- TensorRT は「使えていない」のではなく「使うと壊れる」状態であり、問題の焦点がより明確になった。
- TensorRT はさらに「FP16 だけが特に壊れる」ことまで分かり、現段階では PyTorch 側改善の優先度が高い。
- 解像度縮小は想定以上に効いており、CNN 化のような別アーキテクチャへ行かなくても 10FPS に迫れる可能性が高い。
- 目標達成には重いアーキテクチャ変更より、入力 token 数削減と軽い block skip の組み合わせが有効だった。

## 判断履歴
- 2026-03-17: 最初の改善対象は設計変更ではなく、現行スクリプトの計測性向上に置く。
- 2026-03-17: Docker 実行先は `docs/architecture_rule.md` に従い `piper-humble-dev` を正とする。
- 2026-03-17: 次の改善対象は `set_image` 周辺の定常性能切り分けとし、`inference_mode` 追加は見送る。
- 2026-03-17: 次の実装候補は `set_image` 内の前処理と画像エンコーダ処理の分離計測とする。
- 2026-03-17: 次の実装候補は `forward_image` の内部最適化余地を探すことであり、少なくとも前処理削減では不十分と判断した。
- 2026-03-17: 低解像度化と compile 系は一旦見送り、次の候補はバックボーン構成やモデル設定の軽量化余地の調査とした。
- 2026-03-17: 次の候補は ONNX 出力の数値整合性検証であり、精度を維持できない場合は ToMe など PyTorch 内最適化へ優先度を戻す。
- 2026-03-18: TensorRT が使えない現環境では、次の候補を `skip=8` 周辺の微調整、解像度との併用、または ToMe のような PyTorch 内 token 削減へ置く。
- 2026-03-18: 次の候補は TensorRT 単独の feature 差分比較を OOM しない形へ組み直すこと、並行して PyTorch 側は `skip=8` を基準に維持することとした。
- 2026-03-18: 次の候補は PyTorch 側の `skip=8` 基準と解像度の組み合わせ探索、または ToMe のような token 削減へ移ることとした。
- 2026-03-18: 次の候補は `644` を新しい基準解像度候補として、`person,dog,car` での再確認と、軽い `skip=4/6` 併用探索へ置く。
- 2026-03-18: 次の候補は `644 + skip=4` を新基準候補として、クラス別画像集合での再確認と、実運用スクリプト側への反映可否の判断へ置く。
- 2026-03-18: 次の候補は `truck`, `chair`, `bottle` など残りの代表クラス確認と、実運用既定値を `644 + skip=4` へ寄せる判断へ置く。

## リスクと未解決点
- コンテナ内依存関係や Hugging Face 認証状態により、モデルロードが失敗する可能性がある。
- 5FPS という目標は単発デモスクリプトではなく、連続推論モードの再設計を要する可能性がある。
- COOC 画像群には解像度ばらつきがあるため、平均 FPS を議論するにはサンプリング条件を固定する必要がある。
- ONNX/TensorRT 経路は export・provider・後処理のどこでも誤差を増幅し得るため、速度だけで採用すると精度崩壊を見逃すリスクがある。

## 最新状態（2026-03-18 時点）
- 10FPS マイルストーンは **`resolution=644 + skip-block-count=4`** で到達済みである。
- 保存付きベンチで、`person`, `cat`, `bicycle`, `bus`, `truck`, `chair`, `bottle` の 7 クラスに横展開しても 10FPS 超を維持した。
- よって短期の既定構成候補は `644 + skip=4` としてよい。
- 一方で 20FPS を目標に再探索した結果、同一画像集合・同一 skip 条件で
  - `560`: `12.9192 FPS / avg_object_count=10.60`
  - `504`: `13.7749 FPS / avg_object_count=5.60`
  - `448`: `15.4720 FPS / avg_object_count=3.00`
  となった。
- このため、**解像度縮小だけで 20FPS を狙う路線は精度低下が先に急増する** と判断する。
- `560` は `cat` でも `12.9987 FPS / avg_object_count=1.00` を確認しており、中間マイルストーン候補としては妥当である。
- `560` は `bus` でも `12.7524 FPS / avg_object_count=1.40` を確認しており、少なくとも複数クラスで大崩れはしていない。
- ただし `560 + skip=6` は `13.6216 FPS / avg_object_count=6.80` で、`560 + skip=4` よりトレードオフが悪かった。
- `644 + skip=5` も `11.0135 FPS / avg_object_count=10.20` で、`skip=4` の優位を崩せなかった。
- block 内部だけ一時的に低解像度化して戻す案も `10.2957 FPS / avg_object_count=12.20` と遅く、不採用だった。
- 一方で、global attention の `k/v` だけを `stride=2` で縮小する案は前進があった。
- `644 + skip=4 + kvpool(global=1, stride=2)` は `11.2911 FPS / avg_object_count=12.20` で、基準の `10.8436 / 12.20` を上回った。
- `644 + skip=4 + kvpool(global=2, stride=2)` は `11.0032 / 11.80`、`global=4` は `11.2190 / 9.80` で、global 1 本だけが最も良い境界だった。
- `cat` では `11.1693 / 1.00`、`bus` では `11.2119 / 1.20` で、`kvpool(global=1)` は `person` 固有ではなかった。
- `bicycle` では `11.2161 / 1.00`、`truck` では `11.3755 / 1.80` で、横展開はさらに進んだ。
- `chair` では `10.2499 / 1.60`、`bottle` では `10.6504 / 0.80` で、やや落ちるが大崩れではなかった。
- 適用 block を明示比較すると、`block 15` は `11.0622 / 11.40`、`block 23` は `11.1878 / 12.20`、`block 31` は `4.9840 / 12.20` で、最後段は不適切だった。
- window attention 1 本だけへの `k/v` 縮小は `10.7230 / 12.20` で、基準より遅かった。
- global `stride=3` も `4.8133 / 12.00` まで悪化し、強すぎた。
- 現在の次候補は `560` や `skip` の微調整そのものではなく、この `k/v` 縮小を基準化しつつ、最初の global block を本命として軽い組み合わせを詰めることである。
- その後、global attention の `k/v` head 数だけを grouped-query attention 風にまとめる実験も追加した。
- `group_size=2` を最初の global block 1 本へ入れた run は `10.7585 FPS / avg_object_count=12.60`、`block 23` へ入れた run は `10.3104 FPS / avg_object_count=12.20` で、どちらも基準の `11.2911 / 12.20` を上回れなかった。
- したがって、**`k/v` head grouping は現状では不採用** とし、当面の暫定ベストは引き続き `644 + skip=4 + kvpool(global=1, stride=2)` とする。
- 次の候補は、解像度や head grouping の微調整ではなく、最初の global attention 周辺に限定した token 削減系の導入である。
- その後、連続フレーム用途に向けて `Sam3Processor` へ `temporal_skip` を追加し、image encoder 出力の再利用を実装した。
- `assets/videos/0001` 先頭 12 フレームでの比較では、baseline `temporal_skip=1` が `10.3132 FPS / avg_object_count=2.50`、`temporal_skip=2` が `17.0369 / 2.60`、`temporal_skip=3` が `21.0785 / 2.80` だった。
- これにより、**連続フレーム条件では `temporal_skip=3` で 20FPS を達成済み** である。
- したがって、計画は「単発画像の高速化」と「連続フレームの 20FPS 運用」を分けて扱うべき段階に入った。
- 次の候補は、連続フレーム側では `temporal_skip=2/3` の安定性と可視化確認、単発画像側では引き続き token 削減系の導入である。
