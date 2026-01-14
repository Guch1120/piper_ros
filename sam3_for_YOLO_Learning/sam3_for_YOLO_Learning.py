#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import torch
import sam3
import yaml
import numpy as np
from PIL import Image
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
import cv2
import random


# =========================
# ユーザー設定（ダミー）
# =========================

# 入力画像ディレクトリ（後で変更）
IMAGE_DIR = "/path/to/input_images"

# 出力データセットルート（後で変更）
OUTPUT_DATASET_DIR = "/path/to/output_dataset_yolo"

# 使用するテキストプロンプト（＝クラス名）
TEXT_PROMPTS = [
    "long table",
    "square table with long legs"
]

# Presence Head の閾値
CONFIDENCE_THRESHOLD = 0.5


# =========================
# 内部設定
# =========================

IMAGES_OUT_DIR = os.path.join(OUTPUT_DATASET_DIR, "images", "train")
LABELS_OUT_DIR = os.path.join(OUTPUT_DATASET_DIR, "labels", "train")
VIS_OUT_DIR    = os.path.join(OUTPUT_DATASET_DIR, "visualize")
DATA_YAML_PATH = os.path.join(OUTPUT_DATASET_DIR, "data.yaml")


# =========================
# YOLO用ユーティリティ
# =========================

def convert_box_to_yolo(box, img_w, img_h):
    """
    box: [x1, y1, x2, y2] (pixel)
    return: xc, yc, w, h (normalized)
    """
    x1, y1, x2, y2 = box
    xc = ((x1 + x2) / 2.0) / img_w
    yc = ((y1 + y2) / 2.0) / img_h
    w = (x2 - x1) / img_w
    h = (y2 - y1) / img_h
    return xc, yc, w, h


def get_class_colors(class_names):
    random.seed(42)
    colors = {}
    for name in class_names:
        colors[name] = (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255)
        )
    return colors


# =========================
# メイン処理
# =========================

def main():

    # -------------------------
    # デバイス選択（安全版）
    # -------------------------
    try:
        if torch.cuda.is_available():
            t = torch.randn(1, 1, 32, 32).cuda()
            conv = torch.nn.Conv2d(1, 1, 3).cuda()
            _ = conv(t)
            torch.cuda.synchronize()
            device = "cuda"
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            print("Using CUDA")
        else:
            device = "cpu"
            print("Using CPU")
    except RuntimeError as e:
        print("CUDA init failed, fallback to CPU:", e)
        device = "cpu"

    # -------------------------
    # 出力ディレクトリ作成
    # -------------------------
    os.makedirs(IMAGES_OUT_DIR, exist_ok=True)
    os.makedirs(LABELS_OUT_DIR, exist_ok=True)
    os.makedirs(VIS_OUT_DIR, exist_ok=True)

    # -------------------------
    # SAM3 モデル構築
    # -------------------------
    sam3_root = os.path.dirname(os.path.abspath(__file__))
    bpe_path = os.path.join(sam3_root, "assets", "bpe_simple_vocab_16e6.txt.gz")

    if not os.path.exists(bpe_path):
        sam3_package_root = os.path.join(os.path.dirname(sam3.__file__), "..")
        bpe_path = os.path.join(
            sam3_package_root,
            "assets",
            "bpe_simple_vocab_16e6.txt.gz"
        )

    model = build_sam3_image_model(
        bpe_path=bpe_path,
        device=device
    )

    processor = Sam3Processor(
        model=model,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        device=device
    )

    # -------------------------
    # クラス定義
    # -------------------------
    class_map = {name: idx for idx, name in enumerate(TEXT_PROMPTS)}
    class_colors = get_class_colors(TEXT_PROMPTS)

    # -------------------------
    # 画像処理ループ
    # -------------------------
    image_files = sorted([
        f for f in os.listdir(IMAGE_DIR)
        if f.lower().endswith((".jpg", ".png", ".jpeg"))
    ])

    for idx, image_name in enumerate(image_files):
        image_path = os.path.join(IMAGE_DIR, image_name)
        print(f"[{idx+1}/{len(image_files)}] Processing:", image_name)

        image_pil = Image.open(image_path).convert("RGB")
        img_w, img_h = image_pil.size

        image_np = np.array(image_pil)
        vis_image = image_np.copy()

        # 出力画像名
        out_image_name = f"sample_{idx:04d}.jpg"
        image_pil.save(os.path.join(IMAGES_OUT_DIR, out_image_name))

        label_lines = []

        # 特徴抽出（1回だけ）
        inference_state = processor.set_image(image_pil)

        for prompt in TEXT_PROMPTS:
            print(f"  Prompt: {prompt}")
            results = processor.set_text_prompt(prompt, inference_state)

            if len(results["boxes"]) == 0:
                continue

            class_id = class_map[prompt]
            color = class_colors[prompt]

            for box in results["boxes"]:
                x1, y1, x2, y2 = map(int, box)

                # YOLO形式へ変換
                xc, yc, w, h = convert_box_to_yolo(
                    box,
                    img_w,
                    img_h
                )

                label_lines.append(
                    f"{class_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"
                )

                # -------- 可視化 --------
                cv2.rectangle(
                    vis_image,
                    (x1, y1),
                    (x2, y2),
                    color,
                    2
                )

                cv2.putText(
                    vis_image,
                    prompt,
                    (x1, max(y1 - 8, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2
                )

        # ラベル保存
        label_path = os.path.join(
            LABELS_OUT_DIR,
            out_image_name.replace(".jpg", ".txt")
        )

        with open(label_path, "w") as f:
            for line in label_lines:
                f.write(line + "\n")

        # 可視化画像保存
        cv2.imwrite(
            os.path.join(VIS_OUT_DIR, out_image_name),
            cv2.cvtColor(vis_image, cv2.COLOR_RGB2BGR)
        )

    # -------------------------
    # data.yaml 生成
    # -------------------------
    data_yaml = {
        "path": OUTPUT_DATASET_DIR,
        "train": "images/train",
        "val": "images/train",
        "names": TEXT_PROMPTS
    }

    with open(DATA_YAML_PATH, "w") as f:
        yaml.dump(data_yaml, f, allow_unicode=True)

    print("=== Dataset generation completed ===")


# =========================
# エントリポイント
# =========================

if __name__ == "__main__":
    main()
