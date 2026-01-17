#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import numpy as np

# Force preload pycocotools to init before torch triggers CPU/Numpy conflict
try:
    import pycocotools.mask
except ImportError:
    pass

# Add parent directory to path to find 'sam3' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import torch
import sam3
import yaml
from PIL import Image
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
import random
import glob
from tqdm import tqdm
from PIL import ImageDraw


# =========================
# ユーザー設定
# =========================

IMAGE_DIR = "./output_images_rosbag"
OUTPUT_DATASET_DIR = "./result_sam3"

# SAM3 プロンプト → YOLO クラス名
PROMPT_TO_YOLO_CLASS = {
    "black box": "Bin",
    "chair": "Chair",
    "a single tall shelving unit including vertical side panels and all shelves, as one object": "Drawer",
    "long table": "Long_table",
    "white storage unit containing red storage boxes": "Shelf",
    "small white table with four legs": "Tall_table"
}

CONFIDENCE_THRESHOLD = 0.5


# =========================
# 内部設定
# =========================

IMAGES_TRAIN_DIR = os.path.join(OUTPUT_DATASET_DIR, "images", "train")
LABELS_TRAIN_DIR = os.path.join(OUTPUT_DATASET_DIR, "labels", "train")
IMAGES_VAL_DIR   = os.path.join(OUTPUT_DATASET_DIR, "images", "val")
LABELS_VAL_DIR   = os.path.join(OUTPUT_DATASET_DIR, "labels", "val")
VIS_OUT_DIR      = os.path.join(OUTPUT_DATASET_DIR, "visualize")
DATA_YAML_PATH   = os.path.join(OUTPUT_DATASET_DIR, "data.yaml")


# =========================
# YOLO 用ユーティリティ
# =========================

def convert_box_to_yolo(box, img_w, img_h):
    x1, y1, x2, y2 = box
    xc = ((x1 + x2) / 2.0) / img_w
    yc = ((y1 + y2) / 2.0) / img_h
    w = (x2 - x1) / img_w
    h = (y2 - y1) / img_h
    return xc, yc, w, h


def get_class_colors(class_names):
    random.seed(42)
    return {
        name: (random.randint(0,255), random.randint(0,255), random.randint(0,255))
        for name in class_names
    }


# =========================
# メイン処理
# =========================

def main():

    # -------------------------
    # デバイス選択
    # -------------------------
    try:
        if torch.cuda.is_available():
            _ = torch.randn(1,1,32,32).cuda()
            device = "cuda"
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            print("Using CUDA")
        else:
            device = "cpu"
            print("Using CPU")
    except RuntimeError:
        device = "cpu"
        print("CUDA init failed, fallback to CPU")

    # -------------------------
    # ディレクトリ作成
    # -------------------------
    for d in [
        IMAGES_TRAIN_DIR, LABELS_TRAIN_DIR,
        IMAGES_VAL_DIR, LABELS_VAL_DIR,
        VIS_OUT_DIR
    ]:
        os.makedirs(d, exist_ok=True)

    # -------------------------
    # SAM3 モデル構築
    # -------------------------
    sam3_root = os.path.dirname(os.path.abspath(__file__))
    bpe_path = os.path.join(sam3_root, "assets", "bpe_simple_vocab_16e6.txt.gz")

    if not os.path.exists(bpe_path):
        bpe_path = os.path.join(
            os.path.dirname(sam3.__file__),
            "..", "assets", "bpe_simple_vocab_16e6.txt.gz"
        )

    model = build_sam3_image_model(bpe_path=bpe_path, device=device)
    processor = Sam3Processor(
        model=model,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        device=device
    )

    # -------------------------
    # クラス定義
    # -------------------------
    TEXT_PROMPTS = list(PROMPT_TO_YOLO_CLASS.keys())
    YOLO_CLASSES = sorted(set(PROMPT_TO_YOLO_CLASS.values()))
    YOLO_CLASS_ID = {name: idx for idx, name in enumerate(YOLO_CLASSES)}
    class_colors = get_class_colors(YOLO_CLASSES)

    # -------------------------
    # 画像収集
    # -------------------------
    image_files = []
    for ext in ["jpg", "png", "jpeg", "JPG", "PNG", "JPEG"]:
        image_files += glob.glob(os.path.join(IMAGE_DIR, "**", f"*.{ext}"), recursive=True)

    image_files = sorted(set(image_files))
    random.seed(42)
    random.shuffle(image_files)

    split = int(len(image_files) * 0.8)
    train_set = set(image_files[:split])

    # -------------------------
    # 画像処理ループ
    # -------------------------
    for idx, image_path in enumerate(tqdm(image_files, desc="SAM3 Annotation")):

        is_train = image_path in train_set
        img_out_dir = IMAGES_TRAIN_DIR if is_train else IMAGES_VAL_DIR
        lbl_out_dir = LABELS_TRAIN_DIR if is_train else LABELS_VAL_DIR

        image = Image.open(image_path).convert("RGB")
        w, h = image.size

        vis = image.copy()
        draw = ImageDraw.Draw(vis)

        out_name = f"sample_{idx:04d}.jpg"
        image.save(os.path.join(img_out_dir, out_name))

        labels = []
        state = processor.set_image(image)

        for prompt in TEXT_PROMPTS:
            results = processor.set_text_prompt(prompt, state)
            if len(results["boxes"]) == 0:
                continue

            yolo_name = PROMPT_TO_YOLO_CLASS[prompt]
            class_id = YOLO_CLASS_ID[yolo_name]
            color = class_colors[yolo_name]

            for box in results["boxes"]:
                xc, yc, bw, bh = convert_box_to_yolo(box, w, h)
                labels.append(f"{class_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")

                x1, y1, x2, y2 = map(int, box)
                draw.rectangle([x1,y1,x2,y2], outline=color, width=3)
                draw.text((x1, max(0,y1-10)), yolo_name, fill=color)

        with open(os.path.join(lbl_out_dir, out_name.replace(".jpg",".txt")), "w") as f:
            for l in labels:
                f.write(l + "\n")

        vis.save(os.path.join(VIS_OUT_DIR, out_name))

    # -------------------------
    # data.yaml 生成
    # -------------------------
    with open(DATA_YAML_PATH, "w") as f:
        yaml.dump({
            "path": os.path.abspath(OUTPUT_DATASET_DIR),
            "train": "images/train",
            "val": "images/val",
            "names": YOLO_CLASSES
        }, f, allow_unicode=True)

    print("=== Dataset generation completed ===")


if __name__ == "__main__":
    main()
