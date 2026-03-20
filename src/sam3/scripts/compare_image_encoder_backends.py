#!/usr/bin/env python3

import argparse
import gc
import json
import os
import random
import statistics
import time
from datetime import datetime

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image
from torchvision.transforms import v2

import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor


def sync_if_needed(device: str):
    if device == "cuda":
        torch.cuda.synchronize()


def measure_step(device: str, func):
    sync_if_needed(device)
    start = time.perf_counter()
    result = func()
    sync_if_needed(device)
    return result, time.perf_counter() - start


def resolve_device():
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def resolve_bpe_path(repo_root: str):
    local_path = os.path.join(repo_root, "assets", "bpe_simple_vocab_16e6.txt.gz")
    if os.path.exists(local_path):
        return local_path
    package_root = os.path.join(os.path.dirname(sam3.__file__), "..")
    package_path = os.path.join(package_root, "assets", "bpe_simple_vocab_16e6.txt.gz")
    if os.path.exists(package_path):
        return package_path
    raise FileNotFoundError("BPE file not found")


def collect_all_image_paths(image_dir: str):
    image_paths = []
    for file_name in sorted(os.listdir(image_dir)):
        if not file_name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        image_paths.append(os.path.join(image_dir, file_name))
    return image_paths


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def sanitize_name(text: str):
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)


def build_transform(resolution: int):
    return v2.Compose(
        [
            v2.ToDtype(torch.uint8, scale=True),
            v2.Resize(size=(resolution, resolution)),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ]
    )


def create_ort_session(model_path: str, provider: str, trt_cache_dir: str, trt_fp16: bool):
    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if provider == "cuda":
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    elif provider == "tensorrt":
        providers = [
            (
                "TensorrtExecutionProvider",
                {
                    "trt_fp16_enable": "True" if trt_fp16 else "False",
                    "trt_engine_cache_enable": "True",
                    "trt_engine_cache_path": trt_cache_dir,
                },
            ),
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return ort.InferenceSession(model_path, sess_options=session_options, providers=providers)


def run_ort_encoder(session, image_tensor: torch.Tensor, device: str):
    outputs = session.run(
        None,
        {session.get_inputs()[0].name: image_tensor.detach().cpu().numpy()},
    )
    return [torch.as_tensor(np.asarray(output), device="cpu") for output in outputs]


def summarise_feature_diffs(reference_features, target_features):
    level_metrics = []
    for level, (ref_feat, tgt_feat) in enumerate(zip(reference_features, target_features)):
        ref_np = ref_feat.float().cpu().numpy()
        tgt_np = tgt_feat.float().cpu().numpy()
        abs_diff = np.abs(ref_np - tgt_np)
        mae = float(abs_diff.mean())
        max_abs = float(abs_diff.max())
        ref_mean_abs = float(np.abs(ref_np).mean())
        rel_mae = mae / max(ref_mean_abs, 1e-6)
        level_metrics.append(
            {
                "level": level,
                "shape": list(ref_np.shape),
                "mae": mae,
                "max_abs_diff": max_abs,
                "relative_mae": rel_mae,
            }
        )
    return level_metrics


def aggregate_feature_stats(per_image_diffs):
    if not per_image_diffs:
        return []
    aggregated = []
    num_levels = len(per_image_diffs[0])
    for level in range(num_levels):
        maes = [item[level]["mae"] for item in per_image_diffs]
        max_abs = [item[level]["max_abs_diff"] for item in per_image_diffs]
        rel = [item[level]["relative_mae"] for item in per_image_diffs]
        aggregated.append(
            {
                "level": level,
                "avg_mae": statistics.mean(maes),
                "avg_max_abs_diff": statistics.mean(max_abs),
                "avg_relative_mae": statistics.mean(rel),
            }
        )
    return aggregated


def release_backend(*objects):
    for obj in objects:
        del obj
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", default="data/val2017")
    parser.add_argument("--prompt", default="person")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--selection-pool-size", type=int, default=12)
    parser.add_argument("--selection-max-trials", type=int, default=256)
    parser.add_argument("--min-detections", type=int, default=1)
    parser.add_argument("--resolution", type=int, default=854)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--output-dir", default="result/compare_image_encoder_backends")
    parser.add_argument("--onnx-model", required=True)
    parser.add_argument("--trt-cache-dir", default="/tmp/ort_trt_cache")
    parser.add_argument("--backend", choices=["cuda", "tensorrt"], default="tensorrt")
    parser.add_argument("--disable-trt-fp16", action="store_true")
    parser.add_argument("--skip-detection-counts", action="store_true")
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    image_dir = os.path.join(repo_root, args.image_dir)
    output_root = os.path.join(repo_root, args.output_dir)
    ensure_dir(output_root)

    run_name = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        f"_prompt_{sanitize_name(args.prompt)}"
        f"_res_{args.resolution}"
        f"_n_{args.limit}"
        f"_pool_{args.selection_pool_size}"
        f"_seed_{args.seed}"
        f"_backend_{args.backend}"
        f"_trtfp16_{int(not args.disable_trt_fp16)}"
    )
    run_dir = os.path.join(output_root, run_name)
    ensure_dir(run_dir)

    device = resolve_device()
    bpe_path = resolve_bpe_path(repo_root)
    model, build_time = measure_step(
        device,
        lambda: build_sam3_image_model(bpe_path=bpe_path, device=device),
    )
    filter_processor = Sam3Processor(
        model,
        confidence_threshold=0.5,
        device=device,
        resolution=args.resolution,
        use_autocast=False,
        cache_text_features=True,
    )
    torch_processor = Sam3Processor(
        model,
        confidence_threshold=0.5,
        device=device,
        resolution=args.resolution,
        use_autocast=False,
        cache_text_features=True,
    )

    all_images = collect_all_image_paths(image_dir)
    rng = random.Random(args.seed)
    rng.shuffle(all_images)
    selected_pool = []
    scanned_images = []
    for image_path in all_images[: args.selection_max_trials]:
        scanned_images.append(image_path)
        image = Image.open(image_path)
        state = filter_processor.set_image(image)
        results = filter_processor.set_text_prompt(args.prompt, state)
        if len(results["scores"]) >= args.min_detections:
            selected_pool.append(image_path)
        if len(selected_pool) >= args.selection_pool_size:
            break
    if len(selected_pool) < args.limit:
        raise ValueError(
            f"Only found {len(selected_pool)} images with detections >= {args.min_detections}"
        )
    selected_images = rng.sample(selected_pool, k=args.limit)

    transform = build_transform(args.resolution)

    torch_features_by_image = {}
    torch_counts = []
    for image_path in selected_images:
        image = Image.open(image_path)
        tensor = transform(v2.functional.to_image(image).to(device)).unsqueeze(0)
        with torch.inference_mode():
            torch_backbone = model.backbone.forward_image(tensor)
        torch_features_by_image[image_path] = [
            feat.detach().cpu().clone() for feat in torch_backbone["backbone_fpn"]
        ]
        torch_count = len(
            torch_processor.set_text_prompt(args.prompt, torch_processor.set_image(image))[
                "scores"
            ]
        )
        torch_counts.append(torch_count)
        del tensor
        release_backend(torch_backbone)

    release_backend(filter_processor, torch_processor, model)

    backend_model, backend_build_time = measure_step(
        device,
        lambda: build_sam3_image_model(bpe_path=bpe_path, device=device),
    )
    backend_processor = None
    if not args.skip_detection_counts:
        backend_processor = Sam3Processor(
            backend_model,
            confidence_threshold=0.5,
            device=device,
            resolution=args.resolution,
            use_autocast=False,
            cache_text_features=True,
            image_encoder_onnx_path=args.onnx_model,
            onnx_provider=args.backend,
            onnx_trt_cache_dir=args.trt_cache_dir,
            onnx_trt_fp16=not args.disable_trt_fp16,
        )
    backend_session = create_ort_session(
        args.onnx_model,
        args.backend,
        args.trt_cache_dir,
        trt_fp16=not args.disable_trt_fp16,
    )

    per_image = []
    backend_diffs = []
    backend_counts = []
    for image_path, torch_features in torch_features_by_image.items():
        image = Image.open(image_path)
        tensor = transform(v2.functional.to_image(image).to(device)).unsqueeze(0)
        ort_features = run_ort_encoder(backend_session, tensor.float(), device)
        diffs = summarise_feature_diffs(torch_features, ort_features)
        backend_diffs.append(diffs)
        image_summary = {
            "image_path": image_path,
            "torch_count": torch_counts[len(per_image)],
            f"{args.backend}_diffs": diffs,
        }
        if backend_processor is not None:
            backend_count = len(
                backend_processor.set_text_prompt(
                    args.prompt, backend_processor.set_image(image)
                )["scores"]
            )
            backend_counts.append(backend_count)
            image_summary[f"{args.backend}_count"] = backend_count
        per_image.append(image_summary)
        del tensor, ort_features
        release_backend()

    summary = {
        "build_model": build_time,
        "build_backend_model": backend_build_time,
        "device": device,
        "prompt": args.prompt,
        "resolution": args.resolution,
        "seed": args.seed,
        "selection_pool_size": len(selected_pool),
        "selected_images": selected_images,
        "scanned_images": scanned_images,
        "backend": args.backend,
        "trt_fp16_enabled": None if args.backend != "tensorrt" else (not args.disable_trt_fp16),
        "torch_counts": torch_counts,
        f"{args.backend}_counts": backend_counts if backend_counts else None,
        "avg_torch_count": statistics.mean(torch_counts),
        f"avg_{args.backend}_count": statistics.mean(backend_counts)
        if backend_counts
        else None,
        f"{args.backend}_feature_diff": aggregate_feature_stats(backend_diffs),
        f"{args.backend}_providers": backend_session.get_providers(),
        "skip_detection_counts": args.skip_detection_counts,
    }

    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "per_image.json"), "w", encoding="utf-8") as f:
        json.dump(per_image, f, indent=2, ensure_ascii=False)

    print("Summary:")
    print(f"  build_model={build_time:.4f}s")
    print(f"  build_backend_model={backend_build_time:.4f}s")
    print(f"  avg_torch_count={summary['avg_torch_count']:.2f}")
    if summary[f"avg_{args.backend}_count"] is not None:
        print(f"  avg_{args.backend}_count={summary[f'avg_{args.backend}_count']:.2f}")
    else:
        print(f"  avg_{args.backend}_count=skipped")
    for item in summary[f"{args.backend}_feature_diff"]:
        print(
            f"  {args.backend} level={item['level']} "
            f"avg_mae={item['avg_mae']:.6f} "
            f"avg_rel_mae={item['avg_relative_mae']:.6f}"
        )
    print(f"  {args.backend}_providers={summary[f'{args.backend}_providers']}")
    print(f"  saved_run_dir={run_dir}")


if __name__ == "__main__":
    main()
