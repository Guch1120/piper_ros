import os
import time
import sam3
import torch
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.visualization_utils import plot_results

'''
image_path : 検出したい画像のパス
input_text : 検出したい物体名
'''

def main():
    timings = {}
    benchmark_repeats = 3
    inference_resolution = int(os.environ.get("SAM3_IMAGE_RESOLUTION", "854"))

    def sync_if_needed(current_device):
        # GPU計測のぶれを減らすために必要なときだけ同期する
        if current_device == "cuda":
            torch.cuda.synchronize()

    def measure_step(name, func):
        start = time.perf_counter()
        sync_if_needed(device)
        result = func()
        sync_if_needed(device)
        timings[name] = time.perf_counter() - start
        return result

    def benchmark_repeated_inference(processor, image, input_text, repeats):
        repeated_set_image = []
        repeated_set_text = []

        # 初回計測とは分けて、定常性能だけを観測する
        for _ in range(repeats):
            start = time.perf_counter()
            sync_if_needed(device)
            inference_state = processor.set_image(image)
            sync_if_needed(device)
            repeated_set_image.append(time.perf_counter() - start)

            start = time.perf_counter()
            sync_if_needed(device)
            processor.set_text_prompt(input_text, inference_state)
            sync_if_needed(device)
            repeated_set_text.append(time.perf_counter() - start)

        avg_set_image = sum(repeated_set_image) / len(repeated_set_image)
        avg_set_text = sum(repeated_set_text) / len(repeated_set_text)
        return {
            "avg_set_image": avg_set_image,
            "avg_set_text_prompt": avg_set_text,
            "approx_fps": 1.0 / max(avg_set_image + avg_set_text, 1e-9),
        }

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
    image_path = os.path.join(sam3_root, "assets", "images", "test_image.jpg")
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
    print(f"Inference resolution: {inference_resolution}")
    
    # Build model
    try:
        model = measure_step(
            "build_model",
            lambda: build_sam3_image_model(bpe_path=bpe_path, device=device),
        )
    except (TypeError, RuntimeError) as e:
        print(f"Failed to build model with device {device}: {e}")
        print("Falling back to CPU")
        device = "cpu"
        model = measure_step(
            "build_model_cpu_fallback",
            lambda: build_sam3_image_model(bpe_path=bpe_path, device=device),
        )
    
    if device == "cpu":
        model = model.to("cpu")
    
    # Load image
    print(f"Loading image: {image_path}")
    image = measure_step("load_image", lambda: Image.open(image_path))
    
    # Initialize processor
    # Pass device explicitly
    # confidence_threshold:Presence Head(その概念が画像内にある確率)
    processor = Sam3Processor(
        model,
        confidence_threshold=0.5,
        device=device,
        resolution=inference_resolution,
    )
    
    # Set image
    print("Processing image...")
    # 画像の特徴抽出
    inference_state = measure_step("set_image", lambda: processor.set_image(image))
    
    # Predict
    input_text = "children"
    print(f"Predicting with text prompt: '{input_text}'")
    # Use set_text_prompt instead of predict_text
    results = measure_step(
        "set_text_prompt",
        lambda: processor.set_text_prompt(input_text, inference_state),
    )
    
    # results contains 'masks', 'scores', 'boxes'
    num_objects = len(results["scores"])
    print(f"Found {num_objects} object(s)")
    
    # Visualize
    print("Saving result to groceries_result.png")
    # plot_results signature is (img, results)
    measure_step("plot_results", lambda: plot_results(image, results))
    measure_step("save_figure", lambda: plt.savefig("groceries_result.png"))
    plt.close()
    total_runtime = sum(timings.values())
    print("Timing summary:")
    for name, elapsed in timings.items():
        print(f"  {name}: {elapsed:.4f}s")
    if total_runtime > 0:
        print(f"  total_measured: {total_runtime:.4f}s")
        print(f"  approx_fps_without_plot: {1.0 / max(timings['set_image'] + timings['set_text_prompt'], 1e-9):.4f}")
    repeated_benchmark = benchmark_repeated_inference(
        processor, image, input_text, benchmark_repeats
    )
    print(
        "Repeated benchmark summary:"
        f" avg_set_image={repeated_benchmark['avg_set_image']:.4f}s,"
        f" avg_set_text_prompt={repeated_benchmark['avg_set_text_prompt']:.4f}s,"
        f" approx_fps={repeated_benchmark['approx_fps']:.4f}"
    )
    print("Done!")

if __name__ == "__main__":
    main()
