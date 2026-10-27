#!/usr/bin/env python3
"""Upload Stage-2 eval artifacts to Hugging Face.

Mirrors into the same run directories under yoloytang/BVB-results, alongside any
existing Stage-1 config/agent_meta/blends files.

Uploads the available two-axis scores:
``vision_sim.jsonl`` / ``vision_sim_summary.json`` and
``dual_vqa.jsonl`` / ``dual_vqa_summary.json``. Also uploads the shared Dual
VQA answer banks under ``_dual_vqa_shared/`` when that directory exists.

Pass ``--include-camera-renders`` to also push Mac-precomputed ``camera_renders/``
for cluster-side V-JEPA scoring without re-rendering.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi

DEFAULT_REPO_ID = "yoloytang/BVB-results"
DEFAULT_RESULTS_DIR = Path("sandbox/results")
EVAL_PATTERNS = [
    "vision_sim.jsonl",
    "vision_sim_summary.json",
    "dual_vqa.jsonl",
    "dual_vqa_summary.json",
]
CAMERA_PATTERNS = ["camera_renders/*.mp4", "camera_renders/*.error.json"]
SHARED_DIRNAME = "_dual_vqa_shared"
SHARED_PATTERNS = [
    "original_answers.jsonl",
    "text_only_answers.jsonl",
    "import_report.json",
]


def discover_runs(results_dir: Path, *, include_camera_renders: bool) -> list[Path]:
    runs = []
    for path in sorted(results_dir.glob("mini-harness-*")):
        if not path.is_dir():
            continue
        has_vision = (path / "vision_sim_summary.json").is_file()
        has_dual_vqa = (path / "dual_vqa_summary.json").is_file()
        has_renders = (path / "camera_renders").is_dir()
        if (
            has_vision
            or has_dual_vqa
            or (include_camera_renders and has_renders)
        ):
            runs.append(path)
    return runs


def present_patterns(run_dir: Path, allow_patterns: list[str]) -> list[str]:
    present = []
    for pattern in allow_patterns:
        if pattern == "camera_renders/*.mp4":
            if any((run_dir / "camera_renders").glob("*.mp4")):
                present.append(pattern)
        elif pattern == "camera_renders/*.error.json":
            if any((run_dir / "camera_renders").glob("*.error.json")):
                present.append(pattern)
        elif pattern.endswith("/**"):
            root = run_dir / pattern[:-3]
            if root.is_dir() and any(root.rglob("*")):
                present.append(pattern)
        elif (run_dir / pattern).is_file():
            present.append(pattern)
    return present


def upload_folder(
    api: HfApi,
    *,
    folder_path: Path,
    path_in_repo: str,
    repo_id: str,
    allow_patterns: list[str],
    commit_message: str,
    dry_run: bool,
) -> bool:
    present = present_patterns(folder_path, allow_patterns)
    if not present:
        print(f"[skip] nothing to upload: {path_in_repo}")
        return False
    print(f"[upload] {path_in_repo}/ {{{', '.join(present)}}}")
    if dry_run:
        return True
    api.upload_folder(
        folder_path=str(folder_path),
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type="dataset",
        allow_patterns=allow_patterns,
        commit_message=commit_message,
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Optional run directory name; repeatable. Default: evaluated runs.",
    )
    parser.add_argument(
        "--include-camera-renders",
        action="store_true",
        help="Also upload <run>/camera_renders/*.mp4 (and *.error.json).",
    )
    parser.add_argument(
        "--camera-renders-only",
        action="store_true",
        help="Upload only camera_renders/** (implies --include-camera-renders).",
    )
    parser.add_argument(
        "--skip-shared",
        action="store_true",
        help="Do not upload sandbox/results/_dual_vqa_shared/.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    include_renders = args.include_camera_renders or args.camera_renders_only
    if args.camera_renders_only:
        allow_patterns = list(CAMERA_PATTERNS)
    elif include_renders:
        allow_patterns = EVAL_PATTERNS + CAMERA_PATTERNS
    else:
        allow_patterns = list(EVAL_PATTERNS)

    if args.run:
        runs = [args.results_dir / name for name in args.run]
    else:
        runs = discover_runs(args.results_dir, include_camera_renders=include_renders)
    if not runs and (args.skip_shared or args.camera_renders_only):
        raise SystemExit(f"No matching runs found under {args.results_dir}")

    api = HfApi()
    uploaded_runs = 0
    for run_dir in runs:
        if not run_dir.is_dir():
            raise SystemExit(f"Missing run directory: {run_dir}")
        run_name = run_dir.name
        ok = upload_folder(
            api,
            folder_path=run_dir,
            path_in_repo=run_name,
            repo_id=args.repo_id,
            allow_patterns=allow_patterns,
            commit_message=(
                f"Upload camera_renders for {run_name}"
                if args.camera_renders_only
                else f"Upload Latent Similarity / Dual VQA for {run_name}"
            ),
            dry_run=args.dry_run,
        )
        if ok:
            uploaded_runs += 1

    shared = args.results_dir / SHARED_DIRNAME
    uploaded_shared = False
    if (
        not args.skip_shared
        and not args.camera_renders_only
        and shared.is_dir()
    ):
        uploaded_shared = upload_folder(
            api,
            folder_path=shared,
            path_in_repo=SHARED_DIRNAME,
            repo_id=args.repo_id,
            allow_patterns=SHARED_PATTERNS,
            commit_message="Upload Dual VQA shared answer banks",
            dry_run=args.dry_run,
        )

    if uploaded_runs == 0 and not uploaded_shared:
        raise SystemExit(f"No matching runs found under {args.results_dir}")
    print(
        f"Done. uploaded_runs={uploaded_runs} "
        f"uploaded_shared={uploaded_shared} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
