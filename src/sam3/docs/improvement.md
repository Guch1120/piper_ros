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
