import sys
import os
import numpy as np
from PIL import Image
import torch

# Add package to path if running from src/sam3_ros
# Assuming running from src/sam3_ros
sys.path.append(os.getcwd())

try:
    from sam3_ros.sam3_ros.test_online_tracker import Sam3OnlineTracker
except ImportError:
    # Try adding the parent directory to path
    sys.path.append(os.path.dirname(os.getcwd()))
    from sam3_ros.sam3_ros.test_online_tracker import Sam3OnlineTracker

def main():
    print("Initializing tracker...", flush=True)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    # device = 'cpu'
    print(f"Using device: {device}", flush=True)
    
    # Dynamic path for container compatibility
    import pathlib
    home = pathlib.Path.home()
    checkpoint_path = home / ".cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
    tracker = Sam3OnlineTracker(device=device, checkpoint_path=checkpoint_path)
    print("Tracker initialized.", flush=True)
    
    # Create dummy images
    H, W = 480, 640
    img1 = np.zeros((H, W, 3), dtype=np.uint8)
    # Draw a red square
    img1[100:200, 100:200] = [255, 0, 0]
    
    img2 = np.zeros((H, W, 3), dtype=np.uint8)
    # Move square
    img2[100:200, 110:210] = [255, 0, 0]
    
    print("Initializing track with prompt 'red square'...", flush=True)
    # Note: 'red square' might not be understood by SAM3 text encoder if it's too specific or abstract.
    # But let's try. Or use "square".
    mask1 = tracker.init_track(img1, "square")
    
    if mask1:
        print(f"Frame 0 mask shape: {mask1[0].shape}", flush=True)
        print(f"Frame 0 mask sum: {mask1[0].sum()}", flush=True)
    else:
        print("Frame 0: No mask found", flush=True)
        
    print("Stepping to frame 1...", flush=True)
    mask2 = tracker.step(img2)
    
    if mask2:
        print(f"Frame 1 mask shape: {mask2[0].shape}", flush=True)
        print(f"Frame 1 mask sum: {mask2[0].sum()}", flush=True)
    else:
        print("Frame 1: No mask found", flush=True)

if __name__ == "__main__":
    main()
