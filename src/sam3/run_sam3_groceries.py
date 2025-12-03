import os
import torch
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.visualization_utils import plot_results
import sam3

'''
image_pash : 検出したい画像のパス
input_test : 検出したい物体名
'''

def main():
    # Device selection
    try:
        if torch.cuda.is_available():
            # Test if CUDA actually works with a real operation (Conv2d)
            # Simple allocation often succeeds even with incompatible arches
            t = torch.randn(1, 1, 32, 32).cuda()
            conv = torch.nn.Conv2d(1, 1, 3).cuda()
            out = conv(t)
            # Force synchronization
            torch.cuda.synchronize()
            
            device = "cuda"
            print("Using CUDA")
            # Enable tfloat32 for Ampere GPUs
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
        else:
            device = "cpu"
            print("Using CPU")
    except RuntimeError as e:
        print(f"CUDA available but failed to initialize (likely arch mismatch): {e}")
        print("Falling back to CPU")
        device = "cpu"

    # Set up paths
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sam3_root = current_dir
    
    # Check if assets exist
    image_path = os.path.join(sam3_root, "assets", "images", "groceries.jpg")
    if not os.path.exists(image_path):
        print(f"Error: Image not found at {image_path}")
        return

    bpe_path = os.path.join(sam3_root, "assets", "bpe_simple_vocab_16e6.txt.gz")
    if not os.path.exists(bpe_path):
        sam3_package_root = os.path.join(os.path.dirname(sam3.__file__), "..")
        bpe_path = os.path.join(sam3_package_root, "assets", "bpe_simple_vocab_16e6.txt.gz")
        if not os.path.exists(bpe_path):
            print(f"Error: BPE file not found at {bpe_path}")
            return

    print(f"Loading model with BPE: {bpe_path}")
    
    # Build model
    try:
        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
    except (TypeError, RuntimeError) as e:
        print(f"Failed to build model with device {device}: {e}")
        print("Falling back to CPU")
        device = "cpu"
        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
    
    if device == "cpu":
        model = model.to("cpu")
    
    # Load image
    print(f"Loading image: {image_path}")
    image = Image.open(image_path)
    
    # Initialize processor
    # Pass device explicitly
    processor = Sam3Processor(model, confidence_threshold=0.5, device=device)
    
    # Set image
    print("Processing image...")
    inference_state = processor.set_image(image)
    
    # Predict
    input_text = "groceries"
    print(f"Predicting with text prompt: '{input_text}'")
    # Use set_text_prompt instead of predict_text
    results = processor.set_text_prompt(input_text, inference_state)
    
    # results contains 'masks', 'scores', 'boxes'
    num_objects = len(results["scores"])
    print(f"Found {num_objects} object(s)")
    
    # Visualize
    print("Saving result to groceries_result.png")
    # plot_results signature is (img, results)
    plot_results(image, results)
    plt.savefig("groceries_result.png")
    plt.close()
    print("Done!")

if __name__ == "__main__":
    main()
