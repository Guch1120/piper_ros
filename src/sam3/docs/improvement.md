# 改善実装計画

## 現在の課題
- SAM3 はテキストプロンプトで物体検出対象を指示できるが、現状は 1FPS 未満であり、5FPS 目標に届いていない。
- `run_sam3_groceries.py` には段階別計測がなく、どの処理が支配的か分からない。

## 改善方針
- 初回ループで段階別計測は入ったため、次は定常性能の再計測へ進む。
- FPS 議論から可視化保存の固定コストを切り離したまま、`set_image` と `set_text_prompt` の比率を継続監視する。
- `Sam3Processor` 側には既に `@torch.inference_mode()` があるため、次の改善軸は画像側ボトルネックの切り分けに置く。
- ウォームアップ後でも `set_image` が支配的だったため、次は `set_image` 内部の前処理と画像エンコーダ処理を分けて観測する。
- 以後の推論ベンチは `data/val2017` の固定サブセットを優先し、単一画像依存の判断を避ける。
- 16GB VRAM 制約のため、当面は学習よりも推論最適化と軽量評価を優先する。
- 複数画像平均でも `forward_image` が支配的だったため、前処理最適化は優先度を下げる。
- `resolution` 変更と `torch.compile` はそのままでは不安定なので、次はバックボーン内部の安全な最適化余地を探す。
- `compile_wrapper(max-autotune-no-cudagraphs)` も有効な改善にはならなかったため、compile 系の優先度を下げる。
- mixed precision は有効で、現行路線では最も改善幅が大きかったため、今後の比較基準は autocast 有効を標準にする。
- クエリ数削減とデコーダ層削減は改善しなかったため、単純なデコーダ縮小は優先度を下げる。
- ランダムサンプルでも image encoder が約 80% を占めたため、次の改善対象は明確にバックボーン側に置く。
- 解像度縮小は RoPE 修正後に有効で、`854` が現時点の最良トレードオフになった。

## 直近の実装項目
- autocast 有効状態を基準として、残る差分を `forward_image` と `forward_grounding` に再配分して観測する。
- モデル設定や利用するバックボーンの軽量化余地を確認する。
- もし互換性を保った軽量化が難しければ、バックボーン自体の蒸留や軽量版導入の可否を調査する。
- 比較実験ではランダムサンプルと可視化保存を標準化し、`summary.json` の比率を根拠に判断する。
- `854` を新しい基準解像度とし、より大きいランダムサンプルで精度劣化が許容範囲か検証する。
- 次の変更も、単独で on/off 比較できる小さな実験にする。
- 結果を `docs/log.md` に記録し、次に試す最小実装を 1 件に固定する。

---

## 最新計画: Image Encoder 軽量化（2026-03-17）

### 前提
- EfficientSAM3（TinyViT-21m, RepViT-m2.3 等の軽量バックボーン）は速度向上するが精度が著しく低下したため不採用。
- 本家 SAM3 の ViT (depth=32, embed_dim=1024, img_size=1008) を維持しつつ高速化する。
- 現行 ~4 FPS（autocast bfloat16 有効）→ 目標 5 FPS。差分は約 25%。
- `forward_image` が end-to-end の 80.6% を占めており、ここの高速化が必須。

### 試行済み・不採用の手法
| 手法 | 結果 |
|------|------|
| `torch.compile` | 初回コスト大、定常値も改善なし |
| query数削減 (100/50) | むしろ悪化 |
| decoder層数削減 (3層) | 改善なし |
| 解像度変更 (768) | RoPE assertion で失敗 |
| Flash Attention | 既に使用中 |
| bfloat16 autocast | 既に適用済み（2→4 FPS の改善はこれ） |
| EfficientSAM3 | 速度は出るが精度著しく低下 |

### 実験 A: 入力解像度の縮小（RoPE interpolation 修正）

**狙い**: 1008×1008 (72×72 tokens) → 896×896 (64×64 tokens) に縮小。トークン数 21% 減。

**修正箇所**:
1. `sam3/model/vitdet.py` `get_abs_pos()` (L205付近) — position embedding の interpolation を任意解像度に対応
2. `sam3/sam/rope.py` (L51) — RoPE shape assertion を修正し、周波数テーブルを動的に再計算
3. `sam3/model/vitdet.py` `_setup_rope_freqs()` (L421-457) — 入力サイズ変更時に RoPE を再初期化
4. `sam3/model_builder.py` L76 — `img_size` を外部指定可能にする
5. `sam3/model/sam3_image_processor.py` — transform のリサイズ先を設定可能にする

**検証**: 896, 840, 784 等で FPS と検出精度を比較。

### 実験 B: Token Merging (ToMe)

**狙い**: ViT block 間で類似トークンを統合し、後続ブロックの計算量を漸減させる。再学習不要。

**実装**:
1. `sam3/model/vitdet.py` に `bipartite_soft_matching(metric, r)` を自前実装（外部ライブラリ不要）
2. ViT `forward()` (L836-840) のブロックループ内で、一定間隔ごとに merge を挿入
3. ViT クラスに `tome_r` パラメータを追加し、`model_builder.py` と `sam3_image_processor.py` から設定可能にする

**注意点**:
- merge 後のトークン数変化が neck/FPN (`sam3/model/necks.py`) の出力形状に影響する可能性
- ViT 出力は `[B, H, W, C]` 形状のため、merge 後に unmerge して空間配置を復元する必要あり
- window attention のパディング処理との整合性

**検証**: `tome_r` = 0.05, 0.1, 0.15, 0.2 で FPS と検出精度を sweep。

### 実装順序
1. **実験 A（解像度縮小）を先に試す** — 変更箇所が限定的で、効果予測が明確
2. **実験 B（ToMe）を試す** — 解像度を変えずに高速化できる別軸
3. **両方の結果を比較** — 片方で 5 FPS に達すればそれを採用、不十分なら組み合わせ

### 結果
- 実験 A（解像度縮小）: RoPE 修正後、解像度 854 で **5.27 FPS** を達成。検出精度も許容範囲。
- 実験 B（ToMe）: 未実施。

---

## 最新計画: 10 FPS 目標（2026-03-17）

### 前提
- 解像度 854 + autocast bfloat16 で **5.27 FPS** を達成済み。
- 目標を **10 FPS** に引き上げる。約 **2倍** の高速化が必要。
- `forward_image` = 0.1517s（全体の 80%）、`forward_grounding` = 0.028s（15%）、`forward_text` = 0.007s（3.5%）。
- 現在の総処理時間: ~0.19s/frame → 目標: ~0.10s/frame。
- efficientsam3 側の実験では ONNX + TensorRT FP16 で RepViT-m1.1 が ~9.58 FPS を達成した実績あり。
- ただし EfficientSAM3 バックボーン自体は精度低下のため不採用。本家 SAM3 ViT を維持する。

### 試行済み・不採用の手法（前回までの累積）
| 手法 | 結果 |
|------|------|
| `torch.compile` | 初回コスト大、定常値も改善なし |
| query数削減 (100/50) | むしろ悪化 |
| decoder層数削減 (3層) | 改善なし |
| Flash Attention | 既に使用中 |
| bfloat16 autocast | 既に適用済み（2→4 FPS） |
| EfficientSAM3 | 精度著しく低下 |
| 解像度 1008→854 | 採用済み（4→5.27 FPS） |

### 高速化手法の候補と優先順位

#### 手法 1: Image Encoder の ONNX + TensorRT 化（最有力、期待 ~1.5-2x）

**狙い**: ViT の `forward_image` を ONNX export し、TensorRT FP16 エンジンで実行する。efficientsam3 で実績あり。PyTorch eager 推論と比較して、operator fusion・memory layout 最適化・graph rewrite により大幅な高速化が見込める。

**実装**:
1. `sam3/model/vitdet.py` の ViT forward を ONNX export 可能な形にする（動的軸の定義）
2. export スクリプトを作成（`scripts/export_sam3_encoder_onnx.py`）— efficientsam3 の `export_efficientsam3_onnx.py` を参考にする
3. `sam3/model/sam3_image_processor.py` の `set_image` で、ONNX Runtime（+ TensorRT EP）を使う推論パスを追加
4. TensorRT エンジンキャッシュ（`/tmp/ort_trt_cache`）を利用して初回以降はエンジンビルド不要にする

**前提条件**:
- Docker コンテナ内に `onnxruntime-gpu` と TensorRT（`libnvinfer.so.10`）が必要
- 入力形状は固定（854×854）で export すれば最適化が効きやすい

**検証**: ベンチマークで FPS を比較。可視化で精度維持を確認。

#### 手法 2: Token Merging (ToMe)（中程度、期待 ~1.2-1.4x）

**狙い**: ViT block 間で類似トークンを統合し計算量を漸減。再学習不要。

**実装**: 前回計画の実験 B と同じ。
- `sam3/model/vitdet.py` に `bipartite_soft_matching()` を自前実装
- ブロックループ内で merge を挿入
- `tome_r` パラメータで制御

**注意点**:
- 単独では 2x には届かない見込み（20-40% 程度の改善）
- TensorRT と組み合わせることで効果が加算される可能性

#### 手法 3: 推論時レイヤースキップ（補助的、期待 ~1.1-1.2x）

**狙い**: ViT の 32 層のうち一部をスキップ。decoder に既に `inference_num_layers` パターンがある。

**実装**:
1. `sam3/model/vitdet.py` の ViT クラスに `inference_num_blocks` 属性を追加
2. `forward()` のブロックループで、`full_attn_ids` を含む必要最小限のブロックだけ実行
3. 例: depth 32→28（block 0-6, 8-14, 16-22, 24-30 + global blocks 7,15,23,31）から非 global block を 4 つ削る

**リスク**: 精度劣化の度合いが不明。global attention block（7,15,23,31）は必須だが、その間の windowed block は一部スキップ可能な可能性あり。

#### 手法 4: さらなる解像度縮小（補助的、期待 ~1.1-1.3x）

**狙い**: 854→728 等にさらに下げる。トークン数 61²→52² で約 27% 減。

**リスク**: 精度劣化が顕著になる可能性。854 が現時点の「精度維持できるギリギリ」かどうか要検証。

#### 手法 5: テキストプロンプトキャッシュ（小改善、期待 ~0.03s 削減）

**狙い**: 同一テキストプロンプトの `forward_text` 結果をキャッシュし、画像ごとに再計算しない。

**実装**: `Sam3Processor` に text embedding キャッシュを追加。

### 推奨実装順序

1. **手法 1（ONNX + TensorRT）を最優先で試す**
   - 単独で最大の改善幅（~1.5-2x）が期待できる
   - efficientsam3 に実績と参考実装がある
   - 成功すれば 5.27 * 1.7 ≈ **9 FPS** 前後に到達する見込み
2. **手法 2（ToMe）を重ねる**
   - TensorRT 上でも ToMe は有効（トークン数削減は演算量に直結）
   - `tome_r=0.1` で 10-20% の追加改善 → TensorRT と合わせて **10+ FPS** の可能性
3. **手法 5（テキストキャッシュ）を追加**
   - 実装が容易で副作用なし。~0.03s の固定削減。
4. **手法 3, 4 は上記で不足する場合のみ検討**
   - レイヤースキップや追加の解像度縮小は精度リスクがあるため、他が不十分な場合の最終手段

### 重要ファイル
| ファイル | 役割 |
|---------|------|
| `sam3/model/vitdet.py` | ViT バックボーン（ONNX export 対象、ToMe 挿入箇所） |
| `sam3/model/sam3_image_processor.py` | set_image（ONNX 推論パス追加箇所） |
| `sam3/model_builder.py` | モデル構築（ONNX ランタイム統合箇所） |
| `sam3/model/necks.py` | FPN neck（ToMe 後の形状整合性確認） |
| `../../efficientsam3/sam3/scripts/export_efficientsam3_onnx.py` | ONNX export の参考実装 |
| `../../efficientsam3/sam3/scripts/onnx_encoder_server.py` | ONNX Runtime 推論の参考実装 |
| `scripts/benchmark_val2017.py` | ベンチマーク |

### 検証方法
1. Docker 内 (`piper-humble-dev`) で各手法の on/off 比較
2. `scripts/benchmark_val2017.py` で FPS・検出数を定量比較（res=854, seed=123）
3. 可視化 PNG で精度の目視確認
4. 手法の組み合わせ（TensorRT + ToMe 等）も計測し、最良構成を特定

---

## 最新計画: ONNX/TensorRT の精度崩れ切り分け（2026-03-17）

### 直近結果
- `result/onnx/sam3_encoder_res854.onnx` の export には成功した。
- ONNX/TensorRT image encoder 経路では `avg_set_image=0.0883s`, `person=8.95FPS` まで到達した。
- しかし `person/dog/car` がすべて `avg_object_count=0.00` で、速度向上と引き換えに精度が崩壊した。
- よって「速いが不正確」な状態であり、現時点では採用不可。

### 次にやること
1. **ONNX 出力の数値整合性を確認する**
   - PyTorch `backbone_fpn` と ONNX 出力の差分を、各 FPN level ごとに `MAE`, `max abs diff`, `relative error` で比較する。
   - まずは `CUDAExecutionProvider` と `TensorrtExecutionProvider` を分けて確認し、崩れが export 起因か TensorRT 最適化起因かを切り分ける。
2. **RoPE export 分岐の正当性を検証する**
   - 特に window attention (`24x24`) と global attention (`61x61`) で、PyTorch と同じ回転が掛かっているかを確認する。
   - 必要なら `vitdet.py` の ONNX 用 RoPE 実装をさらに限定的に修正する。
3. **精度が戻らない場合は ONNX/TensorRT を一旦保留する**
   - 精度維持を満たせない場合、ToMe または ViT block skip のような PyTorch 内最適化へ優先度を戻す。

### 判断基準
- `person` の検出数が PyTorch 基準から大きく崩れる場合、その構成は不採用。
- 10FPS に近づいても、精度維持できない高速化は採用しない。
- まずは「PyTorch と同等挙動で 7-9FPS が出るか」を確認し、そこで初めて 10FPS への次手を考える。

---

## 最新計画: PyTorch 内最適化へ軸足を戻す（2026-03-18）

### 直近結果
- selection filter により、対象あり画像だけを使った benchmark に切り替えた。
- ONNX のゼロ検出は export 破綻ではなく、ONNX runtime 側で `scalp=1` を落としていた実装ミスが原因だった。修正後は ONNX CUDA の検出数が PyTorch と一致する。
- ただし ONNX CUDA は `session.run()` の CPU 往復により `approx_fps=1.8889` と遅く、現コンテナでは TensorRT も `libnvinfer.so.10` 不足で使えない。
- したがって、少なくとも現環境では ONNX/TensorRT を主戦力にできない。
- 一方、PyTorch 内の非 global block skip は有効だった。
  - baseline: `5.0015 FPS`, `avg_object_count=13.60`
  - `skip=4`: `5.5624 FPS`, `avg_object_count=13.20`
  - `skip=8`: `6.2093 FPS`, `avg_object_count=12.80`
  - `skip=10`: `6.8075 FPS`, `avg_object_count=4.80`
  - `skip=12`: `7.1375 FPS`, `avg_object_count=3.40`

### 今回の判断
- 短期の採用候補は **`skip=8`** とする。速度改善は約 `+24%`、検出数低下は約 `-5.9%` に留まった。
- **`skip=12` は不採用**。10FPS に近づく方向ではあるが、密な画像で検出数が急落し、精度維持条件を満たさない。
- TensorRT ライブラリが無い現環境では、ONNX 方面をこれ以上掘っても速度改善の本命になりにくい。

### 次にやること
1. **`skip=6, 8, 10` を finer sweep する**
   - 速度と検出数の境界が `8` と `12` の間で急に崩れるため、中間点を埋める。
   - まずは `person` で比較し、候補が見えたら `person,dog,car` に広げる。
2. **解像度との組み合わせを試す**
   - `res=854 + skip=8` を基準に、`840 + skip=4/6/8` を比較する。
   - 低解像度単独より、軽い skip を足した方が精度維持しやすい可能性がある。
3. **ToMe は次段候補として設計を詰める**
   - block skip は単純で効くが、一定点を超えると急に壊れる。
   - ToMe は token 数を漸減できるため、同じ速度改善でも精度劣化が緩い可能性がある。

### 判断基準
- `avg_object_count` の低下が baseline 比 `10%` 以内なら継続候補、`20%` を超えたら不採用寄りとする。
- `image encoder` 比率がなお `75%` 以上なら、次の施策も encoder 内に限定する。
- 速度改善は `+10%` 未満なら見送り、`+20%` 以上なら可視化確認対象に進める。

---

## 最新計画: 10FPS 構成の横展開確認と 20FPS 再探索（2026-03-18）

### 直近結果
- `644 + skip=4` は `person` だけでなく、`cat`, `bicycle`, `bus`, `truck`, `chair`, `bottle` でも 10FPS 超を維持した。
- 代表結果は以下のとおり。
  - `person`: `10.8436 FPS / avg_object_count=12.20`
  - `truck`: `11.1266 FPS / avg_object_count=2.00`
  - `chair`: `11.1699 FPS / avg_object_count=1.80`
  - `bottle`: `11.2013 FPS / avg_object_count=0.80`
- よって、現時点の 10FPS マイルストーン構成は **`resolution=644 + skip-block-count=4`** で一旦確定してよい。

### 20FPS に向けた仮説検証
- まずは最も単純で可逆な手法として、同一画像集合・同一 skip 条件のまま解像度だけをさらに下げた。
- 比較条件は `selection_resolution=854`, `selection_prompt=person`, `limit=6`, `skip=4`, `autocast on`, `seed=123` で固定した。
- 結果は以下のとおり。
  - `560`: `12.9192 FPS / avg_object_count=10.60`
  - `504`: `13.7749 FPS / avg_object_count=5.60`
  - `448`: `15.4720 FPS / avg_object_count=3.00`

### 判断
- `560` まではまだ許容余地があるが、`504` 以降は速度向上に対して検出数低下が急すぎる。
- 現状の傾向では、**解像度縮小だけで 20FPS に届く前に精度が先に崩れる**。
- したがって次の主軸は「解像度だけをさらに下げる」ではなく、`560` 近辺を下限候補としつつ別軸を足す方が妥当である。
- `560` は `cat` でも `12.9987 FPS / avg_object_count=1.00` を確認しており、少なくとも `person` 固有の偶然ではない。
- `560` は `bus` でも `12.7524 FPS / avg_object_count=1.40` を確認しており、中間マイルストーン候補としてはまだ維持できる。
- 一方で `560 + skip=6` は `13.6216 FPS / avg_object_count=6.80` で、`skip=4` より速度の伸びが小さい割に精度低下が大きかった。
- `644 + skip=5` も `11.0135 FPS / avg_object_count=10.20` で、`skip=4` よりトレードオフが悪かった。
- block 内部だけ一時的に低解像度化して戻す案は `10.2957 FPS / avg_object_count=12.20` と遅く、補間オーバーヘッドの方が大きかったため不採用とした。

### 次にやること
1. `560 + skip=4` の横展開は一旦十分なので、これ以上の解像度 sweep は止める。
2. block skip の細かい sweep も `skip=4` 優位でほぼ収束したとみなす。
3. 20FPS を本気で狙う次段では、PyTorch 内での token 削減系（ToMe など）を本命候補として設計・実装に入る。

---

## 最新計画: global attention の `k/v` だけを縮小する（2026-03-19）

### 直近結果
- block 全体の一時プーリングは遅く、不採用だった。
- その代わり、global attention の `q` はそのまま、`k/v` だけを `stride=2` で縮小する実験を追加した。
- `644 + skip=4 + kvpool(global=4, stride=2)` は `11.2190 FPS / avg_object_count=9.80` だった。
- `644 + skip=4 + kvpool(global=2, stride=2)` は `11.0032 FPS / avg_object_count=11.80` だった。
- `644 + skip=4 + kvpool(global=1, stride=2)` は `11.2911 FPS / avg_object_count=12.20` だった。
- `cat` でも `11.1693 FPS / avg_object_count=1.00`、`bus` でも `11.2119 FPS / avg_object_count=1.20` を確認した。
- `bicycle` でも `11.2161 FPS / avg_object_count=1.00`、`truck` でも `11.3755 FPS / avg_object_count=1.80` を確認した。
- `chair` では `10.2499 FPS / avg_object_count=1.60`、`bottle` では `10.6504 FPS / avg_object_count=0.80` だった。
- 適用 block の明示比較では、`block_id=15` が `11.0622 / 11.40`、`block_id=23` が `11.1878 / 12.20`、`block_id=31` は `4.9840 / 12.20` だった。
- 一方、window attention 1 本だけへ同じ `k/v` 縮小を掛けた実験は `10.7230 / 12.20` で、基準より遅かった。
- global `stride=3` も `4.8133 / 12.00` まで悪化し、強すぎた。
- よって現時点の最良候補は **`644 + skip=4 + kvpool(global=1, stride=2)`** である。

### 判断
- global attention 全適用は強すぎるが、1 本だけなら速度向上を得つつ検出数 proxy を維持できた。
- しかもこの改善は `person` 固有ではなく、少なくとも `cat`, `bus`, `bicycle`, `truck`, `chair`, `bottle` にも横展開できた。
- 適用位置には差があり、最後の global block (`31`) は不適切だった。
- window attention 側へ同じ発想をそのまま持ち込んでも、少なくとも 1 block 実験では改善しなかった。
- global 側でも `stride=3` は明確にやり過ぎで、`stride=2` が現実的な上限である。
- `560` と組み合わせた場合は `13.0 FPS` 付近まで伸びるが、検出数低下がやや大きくなる。
- したがって当面の本命は `644` 側での精度維持路線であり、`560` 側は中間マイルストーン候補として保持する。

### 次にやること
1. `644 + skip=4 + kvpool(global=1, stride=2)` の横展開は 7 クラスまで進んだので、次はこの構成を暫定基準として扱う。
2. 現在の auto は最初の global block を選ぶため、そのまま `block 7` 相当を暫定本命として扱う。
3. window attention 側は一旦優先度を下げ、次は global attention 1 本に対するより軽い付加施策を考える。

### 判断基準
- `644 + skip=4` の `avg_object_count=12.20` を維持しつつ、`11 FPS` を超えるなら継続候補。
- `560` 側は `13 FPS` 近辺まで見えているが、検出数低下が大きいので採用は慎重にする。
- 20FPS を目指すにしても、まずはこの `k/v` 縮小がクラス依存で崩れないかを先に確認する。

### 判断基準
- `644 + skip=4` の `avg_object_count=12.20` を当面の比較基準とし、低下が `15%` を超える構成は強く警戒する。
- 20FPS が未達でも、`12-15 FPS` 帯で精度維持が良い構成があれば中間マイルストーンとして保持する。
- ベンチは引き続き逐次実行し、可視化 PNG 保存を既定のまま維持する。

## 最新計画: TensorRT の真因切り分けと PyTorch 迂回路の並行維持（2026-03-18）

### 直近結果
- TensorRT runtime 自体はコンテナへ導入できた。
- `ldconfig` 後の ORT セッションでは `TensorrtExecutionProvider` が active provider になり、TensorRT 未使用疑惑は解消した。
- それでも TensorRT 実ベンチは `approx_fps=7.7966` に対して `avg_object_count=0.00` だった。
- したがって、壊れているのは provider の有無ではなく **TensorRT 最適化後の数値整合性** である。
- 一方で PyTorch 側の `skip=8` は `6.2093 FPS / avg_object_count=12.80` と、依然として最も実用的な迂回路である。
- 追加検証により、TensorRT FP16 on は feature の `avg_relative_mae` が `1.9686 / 2.5030 / 2.3059` と極端に大きい一方、TensorRT FP16 off では `0.002918 / 0.005380 / 0.006040` まで改善した。
- ただし TensorRT FP16 off の実ベンチは `approx_fps=2.4587`, `avg_object_count=3.00` で、速度面で PyTorch baseline に負ける。
- その後、固定画像集合を `selection_resolution=854` で揃えたまま解像度 sweep を行ったところ、`644` で `9.9839 FPS / avg_object_count=12.80`、`588` で `10.5015 FPS / avg_object_count=10.80` だった。
- つまり、**10FPS は解像度縮小だけでも到達圏内** であり、短期の本命は TensorRT ではなく pure PyTorch のままの解像度最適化である。
- さらに `644 + skip=4` の保存付き run で `10.8436 FPS / avg_object_count=12.20` を確認した。
- 現時点では、`588` 単独より `644 + skip=4` の方が精度低下が穏やかで、速度目標も超えている。
- さらに `cat`, `bicycle`, `bus` の各 selection prompt でも、`644 + skip=4` が `10.57 / 10.56 / 11.56 FPS` を維持した。

### 次にやること
1. **TensorRT 路線は一旦保留する**
   - 主因が `trt_fp16_enable` であることまでは分かった。
   - しかし FP16 off は遅く、FP16 on は壊れるため、この系統は短期採用候補から外す。
2. **PyTorch 側の本命を前進させる**
   - `644 + skip=4` を最有力候補として扱う。
   - 次は `truck`, `chair`, `bottle` など追加クラスでも再評価し、クラス依存の崩れがないか確認する。
   - 問題がなければ `run_sam3_groceries.py` 側の既定解像度や設定反映を検討する。
3. **ToMe / token 削減の準備を進める**
   - block skip は `8 -> 10` の間で急に壊れるため、より連続的な軽量化手法が必要である。
   - ToMe のように token 数を漸減する案を次段の実装候補にする。

### 判断基準
- TensorRT は `FP16 on` で壊れ、`FP16 off` で遅いので当面不採用。
- TensorRT 切り分けが長引く場合でも、PyTorch 側改善ループは止めない。
- 可視化保存付き run を基準にし、`--skip-visualizations` は純粋な速度比較時だけに限定する。

## 最新計画: `kvpool(global=1)` を基準に token 削減系へ移る（2026-03-19）

### 直近結果
- `644 + skip=4 + kvpool(global=1, stride=2)` は `person` で `11.2911 FPS / avg_object_count=12.20` を維持し、`cat`, `bus`, `bicycle`, `truck`, `chair`, `bottle` へも横展開できた。
- 追加仮説として、global attention の `k/v` head 数だけを grouped-query attention 風にまとめる経路を実装した。
- ただし、最初の global block 1 本へ `group_size=2` を入れた run は `10.7585 FPS / avg_object_count=12.60` で、速度が基準を下回った。
- 適用位置を `block 23` にずらしても `10.3104 FPS / avg_object_count=12.20` で、改善は出なかった。
- よって、少なくとも現状の実装では **`k/v` head grouping は不採用** であり、`kvpool(global=1)` より良い境界にはならなかった。

### 次にやること
1. **基準構成を固定する**
   - 当面の比較基準は `644 + skip=4 + kvpool(global=1, stride=2)` とする。
   - `person` を主指標、`cat`, `bus`, `bicycle`, `truck`, `chair`, `bottle` を副指標に据える。
2. **head grouping 系は深追いしない**
   - `group_size=2` の 2 例で改善が出ていないため、同系統の size sweep は後回しにする。
   - 追加する場合でも、新しい実装を伴わない軽い再確認に留める。
3. **次段は token 数そのものを減らす**
   - `skip` や head grouping は粗すぎるため、より連続的な token 削減系へ移る。
   - 候補は「最初の global attention 前後だけに限定した token merge」または「attention 前の軽い token pruning」である。
   - まずは neck/FPN の shape 契約を壊さない限定導入から始める。

### 判断基準
- 基準の `11.2911 FPS / avg_object_count=12.20` を下回る案は採用しない。
- `avg_object_count` の変動が小さくても、速度改善が出なければ不採用とする。
- 次段の token 削減系も、まずは `person` 単独で切り分けてから横展開する。

---

## 最新計画: 20FPS 到達戦略（2026-03-20）

### 前提
- `644 + skip=4 + kvpool(global=1, stride=2)` で **11.29 FPS** を達成済み。
- 目標を **20 FPS** に引き上げる。総処理時間を 0.0929s → 0.050s に短縮する必要がある。
- 処理時間の内訳:
  - `forward_image`（image encoder）: 0.0675s（72.6%）
  - `forward_grounding`: 0.0227s（24.4%）
  - その他（to_device, transform, text）: ~0.003s（3%）
- 連続フレーム処理（ROS カメラストリーム）と単発画像処理の両方のユースケースがある。

### 核心的な問題
- 単一の incremental 最適化では 20 FPS に届かない。
- encoder を 0.0675s → 0.025s にするには **63% 削減** が必要で、global attention 周辺の微調整だけでは先が短い。
- 解像度縮小は 560 以下で精度崩壊、block skip は 10 以上で精度崩壊するため、既存軸の延長では限界。
- **複数手法の積み上げ** が必要。

### 試行済み・不採用の手法（累積）
| 手法 | 結果 |
|------|------|
| `torch.compile` | 初回コスト大、定常値も改善なし |
| query数削減 (100/50) | むしろ悪化 |
| decoder層数削減 (3層) | 改善なし |
| Flash Attention | 既に使用中（`F.scaled_dot_product_attention`） |
| bfloat16 autocast | 既に適用済み（2→4 FPS） |
| EfficientSAM3 | 精度著しく低下 |
| 解像度 1008→854→644 | 採用済み（4→5.27→10 FPS） |
| 解像度 560 以下 | 504 で精度崩壊 |
| block skip=10 以上 | 精度崩壊 |
| ONNX + TensorRT FP16 | feature 数値崩壊、FP32 は遅い |
| ONNX + CUDA EP | session.run の CPU 往復で遅い |
| k/v head grouping (GQA風) | 速度低下 |
| window attention k/v pooling | 速度低下 |
| block 内一時解像度縮小 | 補間オーバーヘッドで遅い |
| global k/v stride=3 | 強すぎて速度崩壊 |

### 戦略: 3 段階の積み上げ

#### 段階 1: Token Merging (ToMe) — 単発・連続両方に有効

**期待効果:** encoder 15-25% 高速化 → 11.3 → ~13-14 FPS

**原理:** ViT block 間で類似トークンを cosine similarity で bipartite matching し、上位 r% を平均統合。後続 block の attention/MLP 計算量が漸減する。再学習不要。

**実装方針:**
1. `sam3/model/vitdet.py` に `bipartite_soft_matching(metric, r)` を追加
2. **global attention block（7, 15, 23, 31）の直前でのみ merge** する
   - global block は全 2116 token に対して O(n^2) attention なので、ここの token 削減が最も効く
   - window block は既に 24×24=576 token 単位なので効果が薄い
3. global block の直後で unmerge し、空間配置を復元
   - FPN neck が `[B, H, W, C]` 形状を期待するため、最終出力前に完全復元が必要
4. `ViT.__init__` に `tome_r` パラメータ追加、`Sam3Processor` から設定可能に

**検証:** `tome_r` = 0.05, 0.10, 0.15 で FPS と検出数を sweep

**リスク:** 低。training-free で on/off が容易。精度劣化が大きければ r を下げるだけ。

**修正ファイル:**
- `sam3/model/vitdet.py` — ToMe 実装 + block loop 修正（L997-1048 付近）
- `sam3/model/sam3_image_processor.py` — `tome_r` パラメータ受け渡し
- `scripts/benchmark_val2017.py` — `--tome-r` オプション追加

#### 段階 2: Temporal Feature Reuse — 連続フレーム時のオプション

**期待効果:** 連続フレーム時に実効 ~2x → 13-14 FPS × 2 = ~26 FPS（連続時）

**原理:** ROS カメラストリームでは連続フレーム間の変化が小さい。encoder を N フレームに 1 回だけ実行し、中間フレームはキャッシュした backbone 特徴を再利用して grounding だけ実行する。

**実装方針:**
1. `Sam3Processor` に temporal モード用のステートを追加:
   - `_cached_backbone_out`: 直前の encoder 出力
   - `_frame_counter`: フレームカウンタ
   - `_temporal_skip`: N（default=2、1=無効）
2. `set_image()` で `counter % N != 0` ならキャッシュを返す
3. `reset_temporal_cache()` でシーン切り替え時にリセット
4. `temporal_skip=1` のとき従来と同一動作（単発画像は影響なし）

**修正ファイル:**
- `sam3/model/sam3_image_processor.py` — temporal cache ロジック

#### 段階 3: Async Pipeline — encoder と grounding の重畳（必要なら）

**期待効果:** grounding の 0.023s を encoder と並列化 → ~0.01-0.02s 節約

**原理:** CUDA stream を分けて、前フレームの grounding と現フレームの encoder を同時実行。連続フレーム時に temporal reuse と組み合わせると最も効果的。

**実装方針:**
1. `Sam3Processor` に CUDA stream を追加
2. `set_image_async()` で encoder を別 stream で起動
3. 呼び出し側で前フレームの grounding と並列実行

**リスク:** 中。GPU リソース競合で効果が出ない可能性。段階 1+2 で目標に近ければスキップ可。

**修正ファイル:**
- `sam3/model/sam3_image_processor.py` — async stream 管理

### 到達予測

| 構成 | 単発画像 | 連続フレーム |
|------|---------|------------|
| 現状 (baseline) | 11.3 FPS | 11.3 FPS |
| + ToMe (r=0.1) | ~13-14 FPS | ~13-14 FPS |
| + Temporal (N=2) | — | ~26-28 FPS |
| + Async pipeline | — | ~28-30 FPS |

- **連続フレームでは ToMe + Temporal で 20 FPS 超が見込める。**
- **単発画像では 13-14 FPS が training-free の現実的な上限。** 20 FPS には蒸留・INT8 量子化・軽量バックボーンなど、より踏み込んだ手が必要。

### 実装順序
1. **ToMe 実装 + benchmark sweep** — 両ユースケースに効く基盤
2. **Temporal reuse 実装 + benchmark** — 連続フレーム対応
3. **効果確認後、Async pipeline を検討** — 必要なら追加
4. **ROS ノードへの統合テスト**

### 検証方法
1. `scripts/benchmark_val2017.py` で `--tome-r` と `--temporal-skip` の sweep
2. `person` を主指標、7 クラス横展開で精度確認
3. 連続フレームシミュレーション: val2017 から連続 20 枚を順次処理して実効 FPS 計測
4. 可視化 PNG で精度の目視確認

### 判断基準
- `avg_object_count` の低下が baseline 比 `15%` 以内なら継続候補、`20%` を超えたら不採用寄りとする。
- 単発画像で 20 FPS が未達でも、連続フレームで 20 FPS 超なら ROS 用途として十分と判断する。
- ToMe 単独で `13 FPS` を超えなければ、`560 + ToMe` の組み合わせも検討する。

## 最新計画: Temporal reuse を基準化し、単発と連続を分離して詰める（2026-03-19）

### 直近結果
- `Sam3Processor` に `temporal_skip` を実装し、連続フレーム時に image encoder 出力を再利用できるようにした。
- `assets/videos/0001` の先頭 12 フレーム、`644 + skip=4 + kvpool(global=1, stride=2)` を基準として比較した。
- baseline (`temporal_skip=1`) は `10.3132 FPS / avg_object_count=2.50` だった。
- `temporal_skip=2` は `17.0369 FPS / avg_object_count=2.60` まで改善した。
- `temporal_skip=3` は `21.0785 FPS / avg_object_count=2.80` となり、**連続フレーム条件では 20FPS を超えた**。
- よって、ROS カメラのような連続入力に対しては、目標達成の主戦力は `ToMe` より先に `temporal reuse` であることが実証された。

### 次にやること
1. **連続フレーム 20FPS を安定化する**
   - `assets/videos/0001` でフレーム数を 12 より増やし、`temporal_skip=2/3` の安定性を確認する。
   - 可視化 PNG を見て、cache hit frame での取りこぼしや追従遅れがないかを確認する。
2. **単発画像系は別軸で継続する**
   - 単発画像ではまだ `11.2911 FPS` が上限なので、こちらは `ToMe` や別の token 削減系を次段候補として維持する。
   - ただし 20FPS 目標の優先順位としては、先に temporal 系を ROS 想定で固める。
3. **Temporal benchmark を標準化する**
   - `scripts/benchmark_val2017.py` の `--temporal-skip` を使い、`assets/videos/0001` も公式ベンチ条件として扱う。
   - 以後は「静止画ランダム」と「連続フレーム」を分けて記録する。

### 判断基準
- 連続フレームでは `temporal_skip=3` を暫定目標達成候補として扱う。
- ただし目視で明確な遅延・見逃しがあれば `temporal_skip=2` を安全候補に戻す。
- 単発画像の改善は、連続フレーム 20FPS を壊さない範囲で並行検討する。
