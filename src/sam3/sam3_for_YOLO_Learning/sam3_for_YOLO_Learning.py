import sys
import os
import numpy as np  # Move numpy import to top to avoid conflict with torch/pycocotools

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
# ユーザー設定（ダミー）
# =========================

# 入力画像ディレクトリ（後で変更）
IMAGE_DIR = "./image"

# 出力データセットルート（後で変更）
OUTPUT_DATASET_DIR = "./result"

# 使用するテキストプロンプト（＝クラス名）
TEXT_PROMPTS = [
    "long table",
    "square table with long legs",
    "black box",
    "shelf"
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
    # -------------------------
    # 出力ディレクトリ作成
    # -------------------------
    # ディレクトリ構成を変更: train/val分割対応
    IMAGES_TRAIN_DIR = os.path.join(OUTPUT_DATASET_DIR, "images", "train")
    LABELS_TRAIN_DIR = os.path.join(OUTPUT_DATASET_DIR, "labels", "train")
    IMAGES_VAL_DIR = os.path.join(OUTPUT_DATASET_DIR, "images", "val")
    LABELS_VAL_DIR = os.path.join(OUTPUT_DATASET_DIR, "labels", "val")
    
    os.makedirs(IMAGES_TRAIN_DIR, exist_ok=True)
    os.makedirs(LABELS_TRAIN_DIR, exist_ok=True)
    os.makedirs(IMAGES_VAL_DIR, exist_ok=True)
    os.makedirs(LABELS_VAL_DIR, exist_ok=True)
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
    image_files = []
    # Recursive search for supported extensions
    for ext in ["jpg", "png", "jpeg", "JPG", "PNG", "JPEG"]:
        image_files.extend(glob.glob(os.path.join(IMAGE_DIR, "**", f"*.{ext}"), recursive=True))
    
    image_files = sorted(list(set(image_files)))
    
    # 画像リストをシャッフルして分割 (80% train, 20% val)
    random.seed(42)  # 再現性のため固定
    random.shuffle(image_files)
    
    split_idx = int(len(image_files) * 0.8)
    train_files = set(image_files[:split_idx])
    # val_files = set(image_files[split_idx:]) # remainder is val

    print(f"Total images: {len(image_files)}")
    print(f"Training set: {len(train_files)}")
    print(f"Validation set: {len(image_files) - len(train_files)}")

    for idx, image_path in enumerate(tqdm(image_files, desc="Processing Images")):
        # image_path is already the full path
        image_name = os.path.basename(image_path)
        
        # Train/Val 振り分け判定
        is_train = image_path in train_files
        
        target_images_dir = IMAGES_TRAIN_DIR if is_train else IMAGES_VAL_DIR
        target_labels_dir = LABELS_TRAIN_DIR if is_train else LABELS_VAL_DIR

        try:
            image_pil = Image.open(image_path).convert("RGB")
        except Exception as e:
            print(f"Warning: Failed to load {image_path}: {e}")
            continue

        img_w, img_h = image_pil.size

        # image_np = np.array(image_pil) # Unused
        # Use PIL for visualization
        vis_image = image_pil.copy()
        draw = ImageDraw.Draw(vis_image)

        # 出力画像名 (ユニークにするためidxを入れる)
        out_image_name = f"sample_{idx:04d}.jpg"
        image_pil.save(os.path.join(target_images_dir, out_image_name))

        label_lines = []

        # 特徴抽出（1回だけ）
        inference_state = processor.set_image(image_pil)

        for prompt in TEXT_PROMPTS:
            # print(f"  Prompt: {prompt}") # Suppressed for tqdm
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
                # Draw rectangle (可視化用画像にはすべて描画)
                draw.rectangle([x1, y1, x2, y2], outline=color, width=3)

                # Draw text
                text_position = (x1, max(y1 - 10, 0))
                draw.text(text_position, prompt, fill=color)

        # ラベル保存 (振り分け先へ)
        label_path = os.path.join(
            target_labels_dir,
            out_image_name.replace(".jpg", ".txt")
        )

        with open(label_path, "w") as f:
            for line in label_lines:
                f.write(line + "\n")

        # 可視化画像保存 (これは一か所にまとめる、または分ける？既存は一か所)
        vis_image.save(os.path.join(VIS_OUT_DIR, out_image_name))

    # -------------------------
    # data.yaml 生成
    # -------------------------
    data_yaml = {
        "path": os.path.abspath(OUTPUT_DATASET_DIR),
        "train": "images/train",
        "val": "images/val",
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
