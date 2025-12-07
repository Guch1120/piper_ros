from huggingface_hub import hf_hub_download
import os

def download_ckpt_from_hf():
    print("Downloading config...", flush=True)
    SAM3_MODEL_ID = "facebook/sam3"
    SAM3_CKPT_NAME = "sam3.pt"
    SAM3_CFG_NAME = "config.json"
    try:
        path = hf_hub_download(repo_id=SAM3_MODEL_ID, filename=SAM3_CFG_NAME)
        print(f"Config downloaded to {path}", flush=True)
        
        print("Downloading checkpoint...", flush=True)
        checkpoint_path = hf_hub_download(repo_id=SAM3_MODEL_ID, filename=SAM3_CKPT_NAME)
        print(f"Checkpoint downloaded to {checkpoint_path}", flush=True)
        return checkpoint_path
    except Exception as e:
        print(f"Download failed: {e}", flush=True)

if __name__ == "__main__":
    download_ckpt_from_hf()
