"""Shared constants and helpers for the BVB fact-retention audit.

The audit checks, question by question, whether a Dual VQA pass or fail on a
reconstruction matches what a human can read from the same frames the judge
saw. See README.md for the full protocol.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / "eval"
RESULTS = REPO / "sandbox" / "results"
TEST_JSONL = EVAL / "test.jsonl"
VSI_BENCH = REPO / "VSI-Bench"

sys.path.insert(0, str(EVAL))
from dual_vqa_scoring import (  # noqa: E402
    ORIGINAL_ANSWERS,
    SHARED_DIRNAME,
    semantic_correct,
)

INSTRUMENT_ID = "bvb-human-fact-v1"
INSTRUMENT_VERSION = "1.0"
SOURCE_ORDER = ["arkitscenes", "scannet", "scannetpp"]

# Judge frame protocol, copied from eval/dual_vqa_metric.py. The test suite
# checks that these stay identical whenever that module can be imported.
JUDGE_N_FRAMES = 16
JUDGE_MAX_SIDE = 384
JUDGE_JPEG_QUALITY = 80

# Question types a person can answer by eye from 16 primitive-render frames.
# Metric-scale tasks (sizes, absolute distances, room size) are left to the
# .blend geometry check because humans cannot read metres off untextured
# primitives any better than the judge can.
HUMAN_TASKS = {
    "object_counting": "counting",
    "object_rel_distance": "rel_distance",
    "object_rel_direction_easy": "rel_direction",
    "object_rel_direction_medium": "rel_direction",
    "object_rel_direction_hard": "rel_direction",
    "route_planning": "route_planning",
    "obj_appearance_order": "appearance_order",
}
METRIC_TASKS = {
    "object_size_estimation": "size",
    "object_abs_distance": "abs_distance",
    "room_size_estimation": "room_size",
}

DEFAULT_RUNS = [
    "mini-harness-gpt-6-astra-reasoning-high-run01",
    "mini-harness-gpt-5.6-sol-reasoning-xhigh-run01",
    "mini-harness-qwen3.5-397b-a17b-run01",
]

# Final labels.
H_RETAINED = "retained"          # source verified, recon supports the right answer
H_ERROR = "error"                # source verified, recon supports a wrong answer
H_UNDECIDABLE = "undecidable"    # source verified, recon evidence insufficient
SRC_UNVERIFIED = "source_unverified"  # human could not confirm the target on source
PENDING = "pending"              # raters disagree, no adjudication yet
LABELS = [H_RETAINED, H_ERROR, H_UNDECIDABLE, SRC_UNVERIFIED]

REASON_TAGS = [
    "object_identity_unclear",
    "occluded_or_out_of_view",
    "scale_unclear",
    "temporal_order_unclear",
    "question_ambiguous",
    "other",
]
LOCUS_TAGS = ["perception", "implementation", "both", "unclear"]


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_metadata(path: Path = TEST_JSONL) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in iter_jsonl(path)}


def run_code(run: str) -> str:
    """Short stable name used in unit ids, e.g. gpt-6-astra-reasoning-high."""
    name = run
    if name.startswith("mini-harness-"):
        name = name[len("mini-harness-"):]
    if name.endswith("-run01"):
        name = name[: -len("-run01")]
    return name


def render_path(results: Path, run: str, scene: str) -> Path:
    return results / run / "camera_renders" / f"{scene}.mp4"


def source_path(vsi_bench: Path, dataset: str, scene: str) -> Path:
    return vsi_bench / dataset / f"{scene}.mp4"


def judge_frames_jpeg(video: Path, n: int = JUDGE_N_FRAMES) -> list[bytes]:
    """Return the exact JPEG bytes the Dual VQA judge receives for ``video``.

    Mirrors ``sample_frames_b64`` in eval/dual_vqa_metric.py, including its
    behaviour of silently skipping frames that fail to decode, so the human
    sees the same (possibly fewer than 16) frames as the judge.
    """
    import cv2  # local import keeps manifest/sampling free of OpenCV

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    idxs = [int(i * (total - 1) / max(n - 1, 1)) for i in range(n)]
    out: list[bytes] = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        scale = JUDGE_MAX_SIDE / max(height, width)
        if scale < 1:
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JUDGE_JPEG_QUALITY]
        )
        if not ok:
            continue
        out.append(buf.tobytes())
    cap.release()
    if len(out) < 2:
        raise RuntimeError(f"too few frames from {video}")
    return out


def opaque(seed: int, *parts: str) -> str:
    """Stable id that reveals nothing about model, scene or result."""
    import hashlib

    return hashlib.sha1(":".join([str(seed), *parts]).encode()).hexdigest()[:10]


def rec_item_id(seed: int, unit_id: str) -> str:
    return f"rec:{opaque(seed, 'rec', unit_id)}"


def src_item_id(seed: int, qa_id: str) -> str:
    return f"src:{opaque(seed, 'src', qa_id)}"


def rec_frameset(seed: int, run: str, scene: str) -> str:
    return f"fs:{opaque(seed, 'fs', run, scene)}"


def src_frameset(seed: int, scene: str) -> str:
    return f"fs:{opaque(seed, 'fs', 'source', scene)}"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def answer_correct(answer: Any, qa: dict[str, Any]) -> bool:
    """Score a human answer with the benchmark's own matching rules."""
    return semantic_correct(answer, qa)
