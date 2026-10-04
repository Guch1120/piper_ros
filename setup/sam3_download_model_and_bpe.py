from huggingface_hub import snapshot_download
import os
import urllib.request

# ===== 設定 =====
MODEL_DIR = "/root/.cache/huggingface/sam3"
BPE_PATH = "../sam3/assets/bpe_simple_vocab_16e6.txt.gz"
BPE_URL = "https://github.com/openai/CLIP/raw/main/clip/bpe_simple_vocab_16e6.txt.gz"

print("[INFO] Downloading SAM3 model from Hugging Face...")

try:
    # ===== モデルダウンロード =====
    path = snapshot_download(
        repo_id="facebook/sam3",
        local_dir=MODEL_DIR,
        local_dir_use_symlinks=False
    )

    print("[SUCCESS] Model download completed.")
    print(f"[INFO] Model saved to: {path}")

except Exception as e:
    print("[ERROR] Model download failed.")
    print(e)
    exit(1)

# ===== config確認 =====
config_path = os.path.join(MODEL_DIR, "config.json")
if os.path.exists(config_path):
    print("[CHECK] config.json found.")
else:
    print("[WARNING] config.json is missing!")

# ===== BPEファイル準備 =====
print("[INFO] Checking BPE tokenizer file...")

try:
    os.makedirs(os.path.dirname(BPE_PATH), exist_ok=True)

    if not os.path.exists(BPE_PATH):
        print("[INFO] Downloading BPE vocab file...")
        urllib.request.urlretrieve(BPE_URL, BPE_PATH)
        print("[SUCCESS] BPE file downloaded.")
    else:
        print("[INFO] BPE file already exists.")

except Exception as e:
    print("[ERROR] Failed to prepare BPE file.")
    print(e)
    exit(1)

# ===== 最終確認 =====
if os.path.exists(config_path) and os.path.exists(BPE_PATH):
    print("[SUCCESS] All required files are ready.")
else:
    print("[ERROR] Some required files are missing.")