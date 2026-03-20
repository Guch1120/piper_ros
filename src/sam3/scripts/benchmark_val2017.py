import argparse
import csv
import json
import os
import random
import statistics
import time
from datetime import datetime

import sam3
import torch
from matplotlib import pyplot as plt
from PIL import Image

from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.perflib.compile import compile_wrapper
from sam3.visualization_utils import plot_results


def sync_if_needed(device: str):
    if device == "cuda":
        torch.cuda.synchronize()


def mark_compile_step_begin():
    compiler = getattr(torch, "compiler", None)
    if compiler is not None and hasattr(compiler, "cudagraph_mark_step_begin"):
        compiler.cudagraph_mark_step_begin()


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


def collect_image_paths(image_dir: str, limit: int, random_sample: bool, seed: int):
    image_paths = []
    for file_name in sorted(os.listdir(image_dir)):
        if not file_name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        image_paths.append(os.path.join(image_dir, file_name))
    if random_sample:
        rng = random.Random(seed)
        image_paths = rng.sample(image_paths, k=min(limit, len(image_paths)))
    else:
        image_paths = image_paths[:limit]
    return image_paths


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


def compact_value(text: str, max_len: int = 24):
    value = sanitize_name(text)
    if len(value) <= max_len:
        return value
    return value[:max_len]


def save_visualization(image, results, output_path: str):
    plot_results(image, results)
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def parse_prompts(prompt: str, prompts_csv: str):
    if prompts_csv:
        return [item.strip() for item in prompts_csv.split(",") if item.strip()]
    return [prompt]


def parse_int_csv(text: str):
    if not text:
        return []
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def compute_skip_block_ids(model, skip_block_count: int):
    if skip_block_count <= 0:
        return []
    trunk = model.backbone.vision_backbone.trunk
    non_global_blocks = [
        block_id
        for block_id in range(len(trunk.blocks))
        if block_id not in trunk.full_attn_ids
    ]
    if skip_block_count >= len(non_global_blocks):
        return non_global_blocks
    step = len(non_global_blocks) / float(skip_block_count)
    selected = []
    for index in range(skip_block_count):
        candidate_index = min(
            int(round(index * step)),
            len(non_global_blocks) - 1,
        )
        candidate = non_global_blocks[candidate_index]
        if candidate not in selected:
            selected.append(candidate)
    cursor = 0
    while len(selected) < skip_block_count and cursor < len(non_global_blocks):
        candidate = non_global_blocks[cursor]
        if candidate not in selected:
            selected.append(candidate)
        cursor += 1
    return sorted(selected)


def compute_window_block_ids(model):
    trunk = model.backbone.vision_backbone.trunk
    return [
        block_id
        for block_id in range(len(trunk.blocks))
        if block_id not in trunk.full_attn_ids
    ]


def pick_evenly_spaced_ids(candidate_ids, pick_count: int):
    if pick_count <= 0:
        return []
    if pick_count >= len(candidate_ids):
        return list(candidate_ids)
    step = len(candidate_ids) / float(pick_count)
    selected = []
    for index in range(pick_count):
        candidate_index = min(int(round(index * step)), len(candidate_ids) - 1)
        candidate = candidate_ids[candidate_index]
        if candidate not in selected:
            selected.append(candidate)
    cursor = 0
    while len(selected) < pick_count and cursor < len(candidate_ids):
        candidate = candidate_ids[cursor]
        if candidate not in selected:
            selected.append(candidate)
        cursor += 1
    return sorted(selected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", default="data/val2017")
    parser.add_argument("--prompt", default="person")
    parser.add_argument("--prompts", default="")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--resolution", type=int, default=1008)
    parser.add_argument("--compile-image-backbone", action="store_true")
    parser.add_argument(
        "--compile-mode", default="max-autotune-no-cudagraphs"
    )
    parser.add_argument("--output-dir", default="result/benchmark_val2017")
    parser.add_argument("--skip-visualizations", action="store_true")
    parser.add_argument("--use-autocast", action="store_true")
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--disable-text-cache", action="store_true")
    parser.add_argument("--decoder-layers", type=int, default=0)
    parser.add_argument("--warmup-images", type=int, default=1)
    parser.add_argument("--temporal-skip", type=int, default=1)
    parser.add_argument("--sequential-sample", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--image-encoder-onnx", default="")
    parser.add_argument(
        "--onnx-provider",
        default="tensorrt",
        choices=["tensorrt", "cuda", "cpu"],
    )
    parser.add_argument("--onnx-trt-cache-dir", default="/tmp/ort_trt_cache")
    parser.add_argument("--disable-onnx-trt-fp16", action="store_true")
    parser.add_argument("--selection-prompt", default="")
    parser.add_argument("--selection-resolution", type=int, default=0)
    parser.add_argument("--selection-min-detections", type=int, default=1)
    parser.add_argument("--selection-pool-size", type=int, default=0)
    parser.add_argument("--selection-max-trials", type=int, default=256)
    parser.add_argument("--disable-selection-filter", action="store_true")
    parser.add_argument("--skip-block-count", type=int, default=0)
    parser.add_argument("--kv-pool-global", action="store_true")
    parser.add_argument("--kv-pool-stride", type=int, default=2)
    parser.add_argument("--kv-pool-global-count", type=int, default=0)
    parser.add_argument("--kv-pool-global-ids", default="")
    parser.add_argument("--kv-pool-window", action="store_true")
    parser.add_argument("--kv-pool-window-count", type=int, default=0)
    parser.add_argument("--kv-pool-window-ids", default="")
    parser.add_argument("--kv-head-group-global", action="store_true")
    parser.add_argument("--kv-head-group-size", type=int, default=2)
    parser.add_argument("--kv-head-group-global-count", type=int, default=0)
    parser.add_argument("--kv-head-group-global-ids", default="")
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    image_dir = os.path.join(repo_root, args.image_dir)
    output_root = os.path.join(repo_root, args.output_dir)
    prompts = parse_prompts(args.prompt, args.prompts)
    device = resolve_device()
    bpe_path = resolve_bpe_path(repo_root)
    selection_prompt = args.selection_prompt or prompts[0]
    print(f"Using device: {device}")
    print(f"Selection prompt: {selection_prompt}")
    print(f"Prompts: {', '.join(prompts)}")
    print(f"Resolution: {args.resolution}")
    print(f"Compile image backbone: {args.compile_image_backbone}")
    print(f"Compile mode: {args.compile_mode}")
    print(f"Use autocast: {args.use_autocast}")
    print(f"Query limit: {args.query_limit if args.query_limit > 0 else 'default'}")
    print(f"Text cache: {not args.disable_text_cache}")
    print(
        f"Decoder layers: {args.decoder_layers if args.decoder_layers > 0 else 'default'}"
    )
    print(f"Warmup images: {args.warmup_images}")
    print(f"Temporal skip: {args.temporal_skip}")
    print(f"Random sample: {not args.sequential_sample}")
    print(f"Seed: {args.seed}")
    print(f"Image encoder ONNX: {args.image_encoder_onnx or 'disabled'}")
    print(f"ONNX provider: {args.onnx_provider}")
    print(f"Selection filter: {not args.disable_selection_filter}")
    print(
        f"Selection resolution: {args.selection_resolution if args.selection_resolution > 0 else args.resolution}"
    )
    print(f"Skip blocks: {args.skip_block_count if args.skip_block_count > 0 else 'disabled'}")
    print(f"KV pool global: {args.kv_pool_global}")
    print(
        f"KV pool stride: {args.kv_pool_stride if args.kv_pool_global else 'disabled'}"
    )
    print(
        "KV pool global count: "
        f"{args.kv_pool_global_count if args.kv_pool_global and args.kv_pool_global_count > 0 else 'all' if args.kv_pool_global else 'disabled'}"
    )
    print(
        "KV pool global ids: "
        f"{args.kv_pool_global_ids if args.kv_pool_global and args.kv_pool_global_ids else 'auto' if args.kv_pool_global else 'disabled'}"
    )
    print(f"KV pool window: {args.kv_pool_window}")
    print(
        "KV pool window count: "
        f"{args.kv_pool_window_count if args.kv_pool_window and args.kv_pool_window_count > 0 else 'all' if args.kv_pool_window else 'disabled'}"
    )
    print(
        "KV pool window ids: "
        f"{args.kv_pool_window_ids if args.kv_pool_window and args.kv_pool_window_ids else 'auto' if args.kv_pool_window else 'disabled'}"
    )
    print(f"KV head group global: {args.kv_head_group_global}")
    print(
        "KV head group size: "
        f"{args.kv_head_group_size if args.kv_head_group_global else 'disabled'}"
    )
    print(
        "KV head group global count: "
        f"{args.kv_head_group_global_count if args.kv_head_group_global and args.kv_head_group_global_count > 0 else 'all' if args.kv_head_group_global else 'disabled'}"
    )
    print(
        "KV head group global ids: "
        f"{args.kv_head_group_global_ids if args.kv_head_group_global and args.kv_head_group_global_ids else 'auto' if args.kv_head_group_global else 'disabled'}"
    )
    print(f"Save visualizations: {not args.skip_visualizations}")
    print(f"Output dir: {output_root}")

    run_parts = [
        datetime.now().strftime("%Y%m%d_%H%M%S"),
        f"p_{compact_value('_'.join(prompts))}",
        f"r_{args.resolution}",
        f"n_{args.limit}",
        f"cmp_{int(args.compile_image_backbone)}",
        f"amp_{int(args.use_autocast)}",
        f"q_{args.query_limit if args.query_limit > 0 else 'def'}",
        f"tc_{int(not args.disable_text_cache)}",
        f"ly_{args.decoder_layers if args.decoder_layers > 0 else 'def'}",
        f"wu_{args.warmup_images}",
        f"tmp_{args.temporal_skip}",
        f"rnd_{int(not args.sequential_sample)}",
        f"sd_{args.seed}",
        f"onnx_{compact_value(os.path.basename(args.image_encoder_onnx)) if args.image_encoder_onnx else 'off'}",
        f"prov_{args.onnx_provider}",
        f"skip_{args.skip_block_count if args.skip_block_count > 0 else 'off'}",
    ]
    if args.kv_pool_global:
        run_parts.append(f"kvg_s{args.kv_pool_stride}")
        run_parts.append(
            f"kvgc_{args.kv_pool_global_count if args.kv_pool_global_count > 0 else 'all'}"
        )
        run_parts.append(
            f"kvgid_{compact_value(args.kv_pool_global_ids) if args.kv_pool_global_ids else 'auto'}"
        )
    if args.kv_pool_window:
        run_parts.append(f"kvw_s{args.kv_pool_stride}")
        run_parts.append(
            f"kvwc_{args.kv_pool_window_count if args.kv_pool_window_count > 0 else 'all'}"
        )
        run_parts.append(
            f"kvwid_{compact_value(args.kv_pool_window_ids) if args.kv_pool_window_ids else 'auto'}"
        )
    if args.kv_head_group_global:
        run_parts.append(f"kvhg_{args.kv_head_group_size}")
        run_parts.append(
            f"kvhgc_{args.kv_head_group_global_count if args.kv_head_group_global_count > 0 else 'all'}"
        )
        run_parts.append(
            f"kvhgid_{compact_value(args.kv_head_group_global_ids) if args.kv_head_group_global_ids else 'auto'}"
        )
    run_name = "_".join(run_parts)
    run_dir = os.path.join(output_root, run_name)
    ensure_dir(run_dir)
    ensure_dir(os.path.join(run_dir, "visualizations"))

    model, build_time = measure_step(
        device,
        lambda: build_sam3_image_model(bpe_path=bpe_path, device=device),
    )
    if args.compile_image_backbone:
        model.backbone.forward_image = compile_wrapper(
            model.backbone.forward_image,
            mode=args.compile_mode,
            fullgraph=False,
        )
    if args.query_limit > 0:
        model.transformer.decoder.inference_num_queries = args.query_limit
    if args.decoder_layers > 0:
        model.transformer.decoder.inference_num_layers = args.decoder_layers
    skip_block_ids = compute_skip_block_ids(model, args.skip_block_count)
    trunk = model.backbone.vision_backbone.trunk
    if hasattr(trunk, "inference_skip_block_ids"):
        delattr(trunk, "inference_skip_block_ids")
    for block in trunk.blocks:
        if hasattr(block.attn, "inference_kv_pool_stride"):
            delattr(block.attn, "inference_kv_pool_stride")
        if hasattr(block.attn, "inference_kv_head_group_size"):
            delattr(block.attn, "inference_kv_head_group_size")
    processor = Sam3Processor(
        model,
        confidence_threshold=0.5,
        device=device,
        resolution=args.resolution,
        use_autocast=args.use_autocast,
        cache_text_features=not args.disable_text_cache,
        image_encoder_onnx_path=args.image_encoder_onnx or None,
        onnx_provider=args.onnx_provider,
        onnx_trt_cache_dir=args.onnx_trt_cache_dir,
        onnx_trt_fp16=not args.disable_onnx_trt_fp16,
        temporal_skip=args.temporal_skip,
    )
    processor.set_profile_enabled(True)
    selection_processor = Sam3Processor(
        model,
        confidence_threshold=0.5,
        device=device,
        resolution=args.selection_resolution if args.selection_resolution > 0 else args.resolution,
        use_autocast=args.use_autocast,
        cache_text_features=True,
    )

    if args.disable_selection_filter:
        image_paths = collect_image_paths(
            image_dir,
            args.limit,
            random_sample=not args.sequential_sample,
            seed=args.seed,
        )
        selection_candidates = image_paths.copy()
    else:
        all_image_paths = collect_all_image_paths(image_dir)
        if not all_image_paths:
            raise ValueError(f"No images found in {image_dir}")
        rng = random.Random(args.seed)
        if not args.sequential_sample:
            rng.shuffle(all_image_paths)
        target_pool_size = (
            args.selection_pool_size
            if args.selection_pool_size > 0
            else max(args.limit * 3, args.limit)
        )
        selection_candidates = []
        scanned_images = []
        for image_path in all_image_paths[: args.selection_max_trials]:
            scanned_images.append(image_path)
            image = Image.open(image_path)
            state = selection_processor.set_image(image)
            results = selection_processor.set_text_prompt(selection_prompt, state)
            if len(results["scores"]) >= args.selection_min_detections:
                selection_candidates.append(image_path)
            if len(selection_candidates) >= target_pool_size:
                break
        if len(selection_candidates) < args.limit:
            raise ValueError(
                f"Only found {len(selection_candidates)} images with "
                f"{selection_prompt} detections >= {args.selection_min_detections} "
                f"within {min(len(all_image_paths), args.selection_max_trials)} scanned images"
            )
        if args.sequential_sample:
            image_paths = selection_candidates[: args.limit]
        else:
            image_paths = rng.sample(selection_candidates, k=args.limit)
    if not image_paths:
        raise ValueError(f"No benchmark images selected from {image_dir}")
    print(f"Benchmark images: {len(image_paths)} from {image_dir}")
    print(f"Selection candidates: {len(selection_candidates)}")
    if skip_block_ids:
        trunk.inference_skip_block_ids = skip_block_ids
    kv_pool_global_ids = []
    if args.kv_pool_global:
        requested_kv_pool_ids = parse_int_csv(args.kv_pool_global_ids)
        if requested_kv_pool_ids:
            kv_pool_global_ids = [
                block_id
                for block_id in requested_kv_pool_ids
                if block_id in trunk.full_attn_ids
            ]
        else:
            kv_pool_global_ids = pick_evenly_spaced_ids(
                list(trunk.full_attn_ids),
                args.kv_pool_global_count if args.kv_pool_global_count > 0 else len(trunk.full_attn_ids),
            )
        for block_id in kv_pool_global_ids:
            trunk.blocks[block_id].attn.inference_kv_pool_stride = args.kv_pool_stride
    kv_pool_window_ids = []
    if args.kv_pool_window:
        requested_kv_pool_window_ids = parse_int_csv(args.kv_pool_window_ids)
        if requested_kv_pool_window_ids:
            kv_pool_window_ids = [
                block_id
                for block_id in requested_kv_pool_window_ids
                if block_id in compute_window_block_ids(model)
            ]
        else:
            kv_pool_window_ids = pick_evenly_spaced_ids(
                compute_window_block_ids(model),
                args.kv_pool_window_count
                if args.kv_pool_window_count > 0
                else len(compute_window_block_ids(model)),
            )
        for block_id in kv_pool_window_ids:
            trunk.blocks[block_id].attn.inference_kv_pool_stride = args.kv_pool_stride
    kv_head_group_global_ids = []
    if args.kv_head_group_global:
        requested_kv_head_group_ids = parse_int_csv(args.kv_head_group_global_ids)
        if requested_kv_head_group_ids:
            kv_head_group_global_ids = [
                block_id
                for block_id in requested_kv_head_group_ids
                if block_id in trunk.full_attn_ids
            ]
        else:
            kv_head_group_global_ids = pick_evenly_spaced_ids(
                list(trunk.full_attn_ids),
                (
                    args.kv_head_group_global_count
                    if args.kv_head_group_global_count > 0
                    else len(trunk.full_attn_ids)
                ),
            )
        for block_id in kv_head_group_global_ids:
            trunk.blocks[block_id].attn.inference_kv_head_group_size = (
                args.kv_head_group_size
            )

    set_image_times = []
    to_device_times = []
    transform_times = []
    forward_image_times = []
    temporal_cache_hits = []
    per_image_rows = []
    prompt_metrics = {
        prompt: {
            "set_text_times": [],
            "forward_text_times": [],
            "forward_grounding_times": [],
            "object_counts": [],
        }
        for prompt in prompts
    }

    for image_path in image_paths:
        image = Image.open(image_path)

        if args.compile_image_backbone:
            mark_compile_step_begin()
        processor.reset_profile_timings()
        inference_state, set_image_time = measure_step(
            device, lambda: processor.set_image(image)
        )
        image_timings = processor.get_profile_timings()

        set_image_times.append(set_image_time)
        to_device_times.append(image_timings.get("set_image_to_device", 0.0))
        transform_times.append(image_timings.get("set_image_transform", 0.0))
        forward_image_times.append(image_timings.get("set_image_forward_image", 0.0))
        temporal_cache_hits.append(1 if processor.last_temporal_cache_hit else 0)
        print(f"{os.path.basename(image_path)} set_image={set_image_time:.4f}s")

        for prompt in prompts:
            if args.compile_image_backbone:
                mark_compile_step_begin()
            processor.reset_profile_timings()
            results, set_text_time = measure_step(
                device, lambda: processor.set_text_prompt(prompt, inference_state)
            )
            text_timings = processor.get_profile_timings()

            object_count = len(results["scores"])
            include_in_summary = len(set_image_times) > args.warmup_images
            if include_in_summary:
                prompt_metrics[prompt]["set_text_times"].append(set_text_time)
                prompt_metrics[prompt]["forward_text_times"].append(
                    text_timings.get("set_text_prompt_forward_text", 0.0)
                )
                prompt_metrics[prompt]["forward_grounding_times"].append(
                    text_timings.get("set_text_prompt_forward_grounding", 0.0)
                )
                prompt_metrics[prompt]["object_counts"].append(object_count)
            image_row = {
                "image_path": image_path,
                "prompt": prompt,
                "included_in_summary": include_in_summary,
                "set_image": set_image_time,
                "set_text_prompt": set_text_time,
                "set_image_to_device": image_timings.get("set_image_to_device", 0.0),
                "set_image_transform": image_timings.get("set_image_transform", 0.0),
                "set_image_forward_image": image_timings.get(
                    "set_image_forward_image", 0.0
                ),
                "temporal_cache_hit": int(processor.last_temporal_cache_hit),
                "set_text_forward_text": text_timings.get(
                    "set_text_prompt_forward_text", 0.0
                ),
                "set_text_forward_grounding": text_timings.get(
                    "set_text_prompt_forward_grounding", 0.0
                ),
                "object_count": object_count,
            }
            per_image_rows.append(image_row)
            if not args.skip_visualizations:
                file_stem = os.path.splitext(os.path.basename(image_path))[0]
                prompt_dir = os.path.join(run_dir, "visualizations", sanitize_name(prompt))
                ensure_dir(prompt_dir)
                save_visualization(
                    image,
                    results,
                    os.path.join(prompt_dir, f"{file_stem}.png"),
                )
            print(
                f"  prompt={prompt} "
                f"set_text_prompt={set_text_time:.4f}s "
                f"objects={object_count}"
            )

    summary_set_image_times = set_image_times[args.warmup_images :]
    summary_to_device_times = to_device_times[args.warmup_images :]
    summary_transform_times = transform_times[args.warmup_images :]
    summary_forward_image_times = forward_image_times[args.warmup_images :]
    summary_temporal_cache_hits = temporal_cache_hits[args.warmup_images :]
    avg_set_image = statistics.mean(summary_set_image_times)
    summary = {
        "device": device,
        "image_dir": image_dir,
        "prompts": prompts,
        "resolution": args.resolution,
        "compile_image_backbone": args.compile_image_backbone,
        "compile_mode": args.compile_mode,
        "use_autocast": args.use_autocast,
        "query_limit": args.query_limit if args.query_limit > 0 else None,
        "text_cache": not args.disable_text_cache,
        "decoder_layers": args.decoder_layers if args.decoder_layers > 0 else None,
        "warmup_images": args.warmup_images,
        "temporal_skip": args.temporal_skip,
        "random_sample": not args.sequential_sample,
        "seed": args.seed,
        "selection_prompt": selection_prompt,
        "selection_resolution": args.selection_resolution if args.selection_resolution > 0 else args.resolution,
        "selection_filter_enabled": not args.disable_selection_filter,
        "selection_min_detections": args.selection_min_detections,
        "selection_pool_size": len(selection_candidates),
        "skip_block_count": args.skip_block_count if args.skip_block_count > 0 else None,
        "skip_block_ids": skip_block_ids,
        "kv_pool_global": args.kv_pool_global,
        "kv_pool_stride": args.kv_pool_stride if args.kv_pool_global else 1,
        "kv_pool_global_ids_arg": parse_int_csv(args.kv_pool_global_ids),
        "kv_pool_global_ids": kv_pool_global_ids,
        "kv_pool_window": args.kv_pool_window,
        "kv_pool_window_ids_arg": parse_int_csv(args.kv_pool_window_ids),
        "kv_pool_window_ids": kv_pool_window_ids,
        "kv_head_group_global": args.kv_head_group_global,
        "kv_head_group_size": (
            args.kv_head_group_size if args.kv_head_group_global else 1
        ),
        "kv_head_group_global_ids_arg": parse_int_csv(
            args.kv_head_group_global_ids
        ),
        "kv_head_group_global_ids": kv_head_group_global_ids,
        "selection_candidates": selection_candidates,
        "image_encoder_onnx": args.image_encoder_onnx or None,
        "onnx_provider": args.onnx_provider if args.image_encoder_onnx else None,
        "onnx_trt_fp16": (not args.disable_onnx_trt_fp16)
        if args.image_encoder_onnx
        else None,
        "image_encoder_runtime_providers": processor.image_encoder_session_providers,
        "selected_images": image_paths,
        "build_model": build_time,
        "avg_set_image": avg_set_image,
        "avg_set_image_to_device": statistics.mean(summary_to_device_times),
        "avg_set_image_transform": statistics.mean(summary_transform_times),
        "avg_set_image_forward_image": statistics.mean(summary_forward_image_times),
        "temporal_cache_hit_rate": statistics.mean(summary_temporal_cache_hits),
        "num_images": len(image_paths),
        "num_images_in_summary": len(summary_set_image_times),
        "run_dir": run_dir,
        "per_prompt": {},
    }

    for prompt in prompts:
        avg_set_text = statistics.mean(prompt_metrics[prompt]["set_text_times"])
        avg_forward_text = statistics.mean(prompt_metrics[prompt]["forward_text_times"])
        avg_forward_grounding = statistics.mean(
            prompt_metrics[prompt]["forward_grounding_times"]
        )
        avg_object_count = statistics.mean(prompt_metrics[prompt]["object_counts"])
        approx_fps = 1.0 / max(avg_set_image + avg_set_text, 1e-9)
        total_path = avg_set_image + avg_set_text
        summary["per_prompt"][prompt] = {
            "avg_set_text_prompt": avg_set_text,
            "avg_set_text_forward_text": avg_forward_text,
            "avg_set_text_forward_grounding": avg_forward_grounding,
            "avg_object_count": avg_object_count,
            "approx_fps": approx_fps,
            "bottleneck_breakdown": {
                "set_image_total_share": avg_set_image / total_path,
                "set_image_to_device_share": summary["avg_set_image_to_device"]
                / total_path,
                "set_image_transform_share": summary["avg_set_image_transform"]
                / total_path,
                "set_image_forward_image_share": summary["avg_set_image_forward_image"]
                / total_path,
                "set_text_total_share": avg_set_text / total_path,
                "set_text_forward_text_share": avg_forward_text / total_path,
                "set_text_forward_grounding_share": avg_forward_grounding / total_path,
            },
        }

    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    with open(os.path.join(run_dir, "per_image.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(per_image_rows[0].keys()))
        writer.writeheader()
        writer.writerows(per_image_rows)

    print("Summary:")
    print(f"  build_model={build_time:.4f}s")
    print(f"  avg_set_image={avg_set_image:.4f}s")
    print(f"  avg_set_image_to_device={statistics.mean(summary_to_device_times):.4f}s")
    print(f"  avg_set_image_transform={statistics.mean(summary_transform_times):.4f}s")
    print(
        f"  avg_set_image_forward_image={statistics.mean(summary_forward_image_times):.4f}s"
    )
    print(f"  temporal_cache_hit_rate={statistics.mean(summary_temporal_cache_hits):.4f}")
    for prompt in prompts:
        prompt_summary = summary["per_prompt"][prompt]
        print(
            f"  prompt={prompt} "
            f"avg_set_text_prompt={prompt_summary['avg_set_text_prompt']:.4f}s "
            f"avg_set_text_forward_text={prompt_summary['avg_set_text_forward_text']:.4f}s "
            f"avg_set_text_forward_grounding={prompt_summary['avg_set_text_forward_grounding']:.4f}s "
            f"avg_object_count={prompt_summary['avg_object_count']:.2f} "
            f"approx_fps={prompt_summary['approx_fps']:.4f}"
        )
        breakdown = prompt_summary["bottleneck_breakdown"]
        print(
            "    shares "
            f"image_total={breakdown['set_image_total_share']:.3f} "
            f"image_encoder={breakdown['set_image_forward_image_share']:.3f} "
            f"text_total={breakdown['set_text_total_share']:.3f} "
            f"text_encoder={breakdown['set_text_forward_text_share']:.3f} "
            f"grounding={breakdown['set_text_forward_grounding_share']:.3f}"
        )
    print(f"  saved_run_dir={run_dir}")


if __name__ == "__main__":
    main()
