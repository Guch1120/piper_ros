"""Entry point for the separate SAM3 ROS package namespace."""

from __future__ import annotations

from pathlib import Path
import sys


def _load_main():
    try:
        from sam3_ros.cli import main as main_fn
        return main_fn
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parents[1]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from sam3_ros.cli import main as main_fn
        return main_fn


def main(argv: list[str] | None = None) -> None:
    _load_main()(argv)
