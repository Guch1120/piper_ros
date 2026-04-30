"""Entry point for the separate SAM3 ROS package namespace."""

from __future__ import annotations

from pathlib import Path
import sys


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        for candidate in (parent / "src" / "sam3", parent / "sam3"):
            if (candidate / "sam3_ros" / "cli.py").is_file():
                return candidate
    return Path(__file__).resolve().parents[2]


def _load_main():
    repo_root = _repo_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from sam3_ros.cli import main as main_fn
    return main_fn


def main(argv: list[str] | None = None) -> None:
    _load_main()(argv)
