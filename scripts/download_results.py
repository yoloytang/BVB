#!/usr/bin/env python3
"""Download BVB Stage-1 result artifacts from Hugging Face.

The Hugging Face dataset repository mirrors the contents of ``sandbox/results``.
Downloading into that same local directory lets ``sandbox/run_model.sh --resume``
continue from previously generated ``.blend`` files.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import snapshot_download


DEFAULT_REPO_ID = "yoloytang/BVB-results"
DEFAULT_LOCAL_DIR = Path("sandbox/results")
RETIRED_PATTERNS = [
    "*/unit_tests*.jsonl", "*/summary.json", "*/summary_*.json",
    "*/summary.shard-*.json", "*/introspection-cache*/**",
    # Large reusable analysis caches stay on HF/GPU hosts unless explicitly
    # requested; normal result restoration must not pull them to laptops.
    "_pairwise_vjepa_features/**",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download BVB result artifacts.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="Hugging Face dataset repo id.")
    parser.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_DIR,
                        help="Where to restore the results tree.")
    parser.add_argument("--run", action="append",
                        help="Download only this run directory. Repeat for multiple runs.")
    args = parser.parse_args()

    allow_patterns = None
    if args.run:
        allow_patterns = [f"{run.rstrip('/')}/**" for run in args.run]

    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
    snapshot_download(
        repo_id=args.repo_id,
        repo_type="dataset",
        local_dir=str(args.local_dir),
        allow_patterns=allow_patterns,
        ignore_patterns=RETIRED_PATTERNS,
    )


if __name__ == "__main__":
    main()
