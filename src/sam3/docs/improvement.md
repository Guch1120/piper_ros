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
