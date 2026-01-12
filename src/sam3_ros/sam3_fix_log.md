# リソース制約環境向け SAM3 アーキテクチャ修正ログ

本文書は、限られたVRAM環境（例：BFloat16精度の使用、低解像度 384x384 への変更）で SAM3 Video Tracker を動作させるために行ったコードベースの修正内容を記録したものです。主に型（Dtype）の不整合や、Tensorサイズの不整合を解消しています。

## 1. 型（Dtype）の不整合修正 (Float32 vs BFloat16)

オリジナルの SAM3 実装では、いくつかの場所で `float32` と `bfloat16` が暗黙的に混在しており、BFloat16 でモデルを強制実行しようとすると `RuntimeError: mat1 and mat2 must have the same dtype` エラーが発生していました。

### `sam3/model/model_misc.py`
**問題**: `gen_sineembed_for_position` が明示的に `dtype=torch.float32` でサイン埋め込みを作成していました。
**修正**: 入力 Tensor の dtype を継承するように変更しました。
```python
- dim_t = torch.arange(num_feats, dtype=torch.float32, device=pos_tensor.device)
+ dim_t = torch.arange(num_feats, dtype=pos_tensor.dtype, device=pos_tensor.device)
```

### `sam3/model/decoder.py`
**問題**: `forward_ffn` 内で、`tgt`（入力特徴量）が（Float32のPosEnc加算などの影響で）Float32に昇格してしまうことがあり、`autocast` が無効な状態で BFloat16 の重みと計算しようとしてエラーになっていました。
**修正**: FFNブロックに入る前に、重みの dtype に合わせて `tgt` をキャストする安全策を追加しました。
```python
    def forward_ffn(self, tgt):
+       # [Fix] Ensure tgt matches weight dtype (needed because autocast is disabled)
+       weight_dtype = self.linear1.weight.dtype
+       if tgt.dtype != weight_dtype:
+            tgt = tgt.to(dtype=weight_dtype)
        with torch.amp.autocast(device_type="cuda", enabled=False):
```

### `sam3/model/sam3_image.py`
**問題**: `_run_decoder` が、BFloat16 のメモリと Float32 のクエリ埋め込みを混在させて Transformer に渡していました。
**修正**: デコーダに入力する前に、`memory` を `tgt`（クエリ）の dtype に合わせるようにしました。
```python
        # [Fix] Ensure memory has same dtype as tgt (BF16/FP16 compatibility)
        if memory is not None and tgt.dtype != memory.dtype:
            memory = memory.to(dtype=tgt.dtype)
```

---

## 2. 動的解像度変更のサポート (1008x1008 -> 384x384)

モデルは高解像度（例: 1008x1008）向けに事前設定/コンパイルされています。実行時に解像度を変更（速度向上のため 384x384 へ）すると、内部コンポーネント（RoPE, PromptEncoder, Memory）がハードコードされた、あるいは事前に計算されたサイズを使用し続けるため、"Tensor size mismatch" エラーが発生していました。

### `sam3/model/vitdet.py` (ViT Backbone)
**問題**: `_apply_rope` 内で、事前計算された RoPE 周波数テーブル (`freqs_cis`) が初期化時の形状（1008ベース）を保持しており、384ベースの特徴量マップとサイズが合わずクラッシュしていました。
**修正**: 入力シーケンス長がキャッシュされたテーブルと一致しない場合、動的に `freqs_cis` を再計算するロジックを追加しました。
```python
        # [Fix] Dynamically recompute freqs_cis if dimensions mismatch
        seq_len = q.shape[-2]
        if self.freqs_cis.shape[0] != seq_len:
             # ... Logic to recompute self.freqs_cis based on new size ...
```

### `sam3/model/sam3_tracker_base.py` (PromptEncoder & Constraints)
**問題1**: `_forward_sam_heads` が、バックボーン特徴量がハードコードされた `sam_image_embedding_size` と一致することをアサート（強制確認）していました。
**問題2**: `PromptEncoder` が古いサイズのまま位置エンコーディング（PE）を生成していました。
**修正**: アサーションを緩和し、実行時の実際のバックボーン特徴量サイズに基づいて `PromptEncoder` のサイズ属性（`image_embedding_size`, `input_image_size`, `mask_input_size`）を動的に更新するようにしました。
```python
+       # [Fix] Allow dynamic backbone feature size
+       # assert backbone_features.size(2) == self.sam_image_embedding_size
+
+       # [Fix] Update prompt encoder image size dynamically if needed
+       curr_embedding_size = (backbone_features.size(2), backbone_features.size(3))
+       if curr_embedding_size != self.sam_prompt_encoder.image_embedding_size:
+            self.sam_prompt_encoder.image_embedding_size = curr_embedding_size
+            self.sam_prompt_encoder.input_image_size = (...)
+            self.sam_prompt_encoder.mask_input_size = (...)
```

### `sam3/model/sam3_tracker_base.py` (Memory Encoder)
**問題**: メモリエンコーディングで使用される `SimpleMaskDownSampler` の `interpol_size` が固定値（例: 1152x1152）になっており、マスク入力が誤ったサイズにリサイズされ、視覚特徴量と加算する際に不整合が起きていました。
**修正**: `_encode_new_memory` 内で、特徴量マップの解像度とストライド（16）に基づいて、適切な `interpol_size` を動的に計算・更新するようにしました。
```python
+           # [Fix] Update mask_downsampler interpol_size dynamically
+           resolution_scaling = 16
+           expected_interpol_size = [...]
+           if list(current_interpol_size) != expected_interpol_size:
+                self.maskmem_backbone.mask_downsampler.interpol_size = expected_interpol_size
```

## 3. トラッカーラッパーの修正

### `sam3_ros/test_sam3_online_tracker.py`
**問題**: トラッカーの初期化 `init_state` がモデルのデフォルト `image_size` 属性（1008）を使用して画像を読み込む一方、`step` 関数は `processing_size` (384) を使用していました。これにより、初期フレームのデータと後続フレームのデータ形式が一致しなくなっていました。
**修正**: モデル作成直後に、`model.image_size` と `model.tracker.image_size` を `processing_size` (384) で上書きするようにしました。
```python
        self.model = build_sam3_video_model(...)
+       # [Fix] Overwrite default image_size (1008) with processing_size (384)
+       self.model.image_size = self.processing_size
+       if hasattr(self.model, "tracker"):
+            self.model.tracker.image_size = self.processing_size
```
