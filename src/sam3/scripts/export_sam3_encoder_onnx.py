#!/usr/bin/env python3
"""SAM3 image encoder を ONNX に export する。"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from torch import nn

from sam3 import build_sam3_image_model


class _Sam3VisionEncoderOnnxWrapper(nn.Module):
    """SAM3 の visual backbone から FPN 特徴だけを取り出す。"""

    def __init__(self, vision_backbone: nn.Module):
        super().__init__()
        self.vision_backbone = vision_backbone

    def forward(self, image: torch.Tensor):
        sam3_out, _, _, _ = self.vision_backbone(image)
        return tuple(sam3_out)


def _configure_fixed_resolution_rope(model: nn.Module, resolution: int):
    feature_hw = resolution // 14
    trunk = model.backbone.vision_backbone.trunk
    for block in trunk.blocks:
        if not hasattr(block, "attn") or not getattr(block.attn, "use_rope", False):
            continue
        block.attn.input_size = (feature_hw, feature_hw)
        block.attn.dynamic_freqs_cis_cache = {}
        block.attn._setup_rope_freqs()


def parse_args():
    parser = argparse.ArgumentParser(description="Export SAM3 image encoder to ONNX")
    parser.add_argument(
        "--checkpoint",
        default="sam3.pt",
        help="SAM3 checkpoint path",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output ONNX path",
    )
    parser.add_argument(
        "--bpe-path",
        default="assets/bpe_simple_vocab_16e6.txt.gz",
        help="Tokenizer BPE path",
    )
    parser.add_argument(
        "--resolution",
        type=int,
        default=854,
        help="Square input resolution",
    )
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda"],
        help="Export 実行デバイス",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = build_sam3_image_model(
        checkpoint_path=args.checkpoint,
        load_from_HF=False,
        bpe_path=args.bpe_path,
        device=args.device,
        eval_mode=True,
    )
    _configure_fixed_resolution_rope(model, args.resolution)
    encoder = _Sam3VisionEncoderOnnxWrapper(model.backbone.vision_backbone).eval()
    dummy = torch.randn(
        1,
        3,
        args.resolution,
        args.resolution,
        dtype=torch.float32,
        device=args.device,
    )

    torch.onnx.export(
        encoder,
        dummy,
        output_path.as_posix(),
        input_names=["image"],
        output_names=["fpn0", "fpn1", "fpn2", "fpn3"],
        opset_version=args.opset,
        do_constant_folding=True,
        dynamo=False,
    )
    print(f"Exported SAM3 encoder ONNX: {output_path}")


if __name__ == "__main__":
    main()
