from ultralytics import YOLO
import os
import yaml
import sys
import torch
import numpy as np

# ==============================================================================
# GLOBAL MONKEYPATCHES (Must be applied before any other logic to persist in workers)
# ==============================================================================

print("Applying global patches for robust execution in Docker environment...")

# 1. Patch torch.from_numpy to handle environment-specific RuntimeError
_original_from_numpy = torch.from_numpy

def safe_from_numpy(array):
    try:
        return _original_from_numpy(array)
    except RuntimeError:
        # Fallback to copy-based creation if shared memory/initialization fails
        return torch.tensor(array)

torch.from_numpy = safe_from_numpy

# 2. Patch torch.Tensor.numpy to handle data retrieval failures
_original_numpy = torch.Tensor.numpy

def safe_numpy(self):
    try:
        return _original_numpy(self)
    except RuntimeError:
        return np.array(self.tolist())

torch.Tensor.numpy = safe_numpy

# 3. Patch torch.tensor constructor for DLPack/numpy interop failures
_original_tensor = torch.tensor

def safe_tensor(data, *args, **kwargs):
    if isinstance(data, np.ndarray):
        try:
            return _original_tensor(data, *args, **kwargs)
        except (RuntimeError, TypeError):
            return _original_tensor(data.tolist(), *args, **kwargs)
    return _original_tensor(data, *args, **kwargs)

torch.tensor = safe_tensor

# 4. Patch torch.load for PyTorch 2.6+ security check (weights_only=True bypass)
_original_load = torch.load

def unsafe_load(*args, **kwargs):
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)

torch.load = unsafe_load

print("Global patches applied successfully.")

# ==============================================================================

def main():
    print(f"Python: {sys.version}")
    
    # モデルパス設定
    model_dir = "./yolov8_hsr/models"
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "yolov8m.pt")

    if not os.path.exists(model_path):
        print(f"Downloading 'yolov8m.pt' to {model_path}...")
        torch.hub.download_url_to_file('https://github.com/ultralytics/assets/releases/download/v8.1.0/yolov8m.pt', model_path)
    else:
        print(f"Using local model at {model_path}")

    # data.yaml のパス自動修正
    data_yaml_path = "./result/data.yaml"
    abs_result_path = os.path.abspath("./result")
    
    if os.path.exists(data_yaml_path):
        with open(data_yaml_path, 'r') as f:
            data_config = yaml.safe_load(f)
        
        if data_config and data_config.get('path') != abs_result_path:
            print(f"Updating data.yaml path to: {abs_result_path}")
            data_config['path'] = abs_result_path
            with open(data_yaml_path, 'w') as f:
                yaml.dump(data_config, f)

    # モデルロード
    try:
        model = YOLO(model_path)
    except Exception as e:
        print(f"Error loading YOLO model: {e}")
        return

    print("Starting training with optimized settings...")
    
    # 学習実行
    # パッチがグローバル適用されたため、workers>0 でも動作する可能性が高い
    model.train(
        data="./result/data.yaml",
        epochs=50,
        imgsz=640,
        batch=16,
        device=0,
        name="yolo_hsr_training",
        patience=20,
        amp=True,     # 高速化のためAMP有効化（パッチで耐えられるか期待）
        workers=8,    # 高速化のためマルチプロセス有効化（パッチで耐えられるか期待）
        exist_ok=True,
        plots=False   # 念のためプロットは無効のまま（ここは速度への影響小）
    )
    
    print("Training completed.")

if __name__ == "__main__":
    main()
