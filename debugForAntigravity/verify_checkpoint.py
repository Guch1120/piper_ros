import torch
import os

def verify():
    checkpoint_path = "/home/guch1/.cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
    print(f"Loading {checkpoint_path}...", flush=True)
    try:
        ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        print("Loaded successfully.", flush=True)
        if "model" in ckpt:
            print("Keys in model:", len(ckpt["model"]))
        else:
            print("Keys in ckpt:", len(ckpt))
    except Exception as e:
        print(f"Failed to load: {e}", flush=True)

if __name__ == "__main__":
    verify()
