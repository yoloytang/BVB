#!/usr/bin/env python3
"""Write one self-contained HTML survey per rater.

Each survey embeds exactly the JPEG frames the Dual VQA judge received
(same indices, resize and JPEG quality), the question text and options, and
nothing else: no ground truth, model name, judge answer or DV result.

Within a survey, scenes appear one after another. For each scene the rater
first answers every reconstruction item (shuffled, reconstructions labelled
only "重建 A/B/C" with a per-scene random letter), and only then sees the
source frames and answers each distinct question once on the source.

Example::

  python eval/human/fact_audit/export_pack.py --study eval/human/fact_audit/study/wave1
  python eval/human/fact_audit/export_pack.py --study ... --pilot
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import string
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from common import (
    INSTRUMENT_ID,
    INSTRUMENT_VERSION,
    JUDGE_N_FRAMES,
    REASON_TAGS,
    RESULTS,
    TEST_JSONL,
    VSI_BENCH,
    b64,
    iter_jsonl,
    judge_frames_jpeg,
    load_metadata,
    rec_frameset,
    rec_item_id,
    render_path,
    source_path,
    src_frameset,
    src_item_id,
    write_json,
)

FORM = Path(__file__).resolve().parent / "form" / "fact_audit.html"
PLACEHOLDER = "/*__PACK_JSON__*/null"


def answer_format(qa: dict) -> str:
    if qa["question_type"] == "object_counting":
        return "count"
    return "mc" if qa.get("options") else "number"


def build_packs(units: list[dict], metadata: dict, seed: int, *, kind: str) -> dict[str, dict]:
    """Return rater -> pack skeleton (frames referenced by frameset key)."""
    by_rater_scene: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for unit in units:
        for rater in unit["raters"]:
            by_rater_scene[rater][unit["scene"]].append(unit)

    packs: dict[str, dict] = {}
    for rater in sorted(by_rater_scene):
        rng = random.Random(f"{seed}:{rater}:{kind}")
        scenes = sorted(by_rater_scene[rater])
        rng.shuffle(scenes)
        blocks = []
        for scene in scenes:
            scene_units = sorted(by_rater_scene[rater][scene], key=lambda u: u["unit_id"])
            runs = sorted({u["run"] for u in scene_units})
            letters = list(string.ascii_uppercase[: len(runs)])
            rng.shuffle(letters)
            run_letter = dict(zip(runs, letters))
            recon_items = []
            for unit in scene_units:
                qa = metadata[unit["qa_id"]]
                recon_items.append({
                    "item_id": rec_item_id(seed, unit["unit_id"]),
                    "unit_id": unit["unit_id"],  # back-end copy only; stripped from the survey
                    "stage": "recon",
                    "label": f"重建 {run_letter[unit['run']]}",
                    "frameset": rec_frameset(seed, unit["run"], scene),
                    "question": qa["question"],
                    "options": qa.get("options") or [],
                    "answer_format": answer_format(qa),
                })
            rng.shuffle(recon_items)
            source_items = []
            for qa_id in sorted({u["qa_id"] for u in scene_units}, key=int):
                qa = metadata[qa_id]
                source_items.append({
                    "item_id": src_item_id(seed, qa_id),
                    "qa_id": qa_id,  # back-end copy only; stripped from the survey
                    "stage": "source",
                    "label": "原视频",
                    "frameset": src_frameset(seed, scene),
                    "question": qa["question"],
                    "options": qa.get("options") or [],
                    "answer_format": answer_format(qa),
                })
            rng.shuffle(source_items)
            blocks.append({
                "scene_key": hashlib.sha1(f"{seed}:{scene}".encode()).hexdigest()[:8],
                "scene": scene,
                "dataset": scene_units[0]["dataset"],
                "recon_items": recon_items,
                "source_items": source_items,
            })
        packs[rater] = {
            "pack_id": f"fact-{kind}-{rater}",
            "rater_slot": rater,
            "instrument_id": INSTRUMENT_ID,
            "instrument_version": INSTRUMENT_VERSION,
            "is_pilot": kind == "pilot",
            "mode": "video" if kind == "review" else "frames",
            "reason_tags": REASON_TAGS,
            "blocks": blocks,
        }
    return packs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--vsi-bench", type=Path, default=VSI_BENCH)
    parser.add_argument("--qa-metadata", type=Path, default=TEST_JSONL)
    parser.add_argument("--n-frames", type=int, default=JUDGE_N_FRAMES)
    parser.add_argument("--pilot", action="store_true", help="Export pilot_sample.jsonl instead of sample.jsonl.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    design = json.loads((args.study / "design.json").read_text())
    sample_file = "pilot_sample.jsonl" if args.pilot else "sample.jsonl"
    units = list(iter_jsonl(args.study / sample_file))
    metadata = load_metadata(args.qa_metadata)
    out_dir = args.study / ("packs_pilot" if args.pilot else "packs")
    if out_dir.exists() and not args.force:
        raise SystemExit(f"{out_dir} exists; pass --force to rebuild")
    out_dir.mkdir(parents=True, exist_ok=True)

    packs = build_packs(units, metadata, design["seed"], kind="pilot" if args.pilot else "main")

    # Extract every frameset once; record provenance for the analysis.
    seed = design["seed"]
    needed: dict[str, Path] = {}
    for unit in units:
        needed[rec_frameset(seed, unit["run"], unit["scene"])] = render_path(args.results_dir, unit["run"], unit["scene"])
        needed[src_frameset(seed, unit["scene"])] = source_path(args.vsi_bench, unit["dataset"], unit["scene"])
    framesets: dict[str, list[str]] = {}
    provenance: dict[str, dict] = {}
    for key in sorted(needed):
        video = needed[key]
        if not video.is_file():
            raise SystemExit(f"missing video for {key}: {video}")
        frames = judge_frames_jpeg(video, args.n_frames)
        framesets[key] = [b64(f) for f in frames]
        provenance[key] = {
            "video": str(video),
            "n_frames_requested": args.n_frames,
            "n_frames_shown": len(frames),
            "sha1": [hashlib.sha1(f).hexdigest() for f in frames],
        }

    template = FORM.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit("form template lost its pack placeholder")
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for rater, pack in packs.items():
        used = {item["frameset"] for b in pack["blocks"] for item in b["recon_items"] + b["source_items"]}
        payload = dict(pack, created_utc=created, framesets={k: framesets[k] for k in sorted(used)})
        # Scene ids stay in the back-end copy only.
        public = json.loads(json.dumps(payload))
        for block in public["blocks"]:
            block.pop("scene")
            block.pop("dataset")
            for item in block["recon_items"] + block["source_items"]:
                item.pop("unit_id", None)
                item.pop("qa_id", None)
        html = template.replace(PLACEHOLDER, json.dumps(public, ensure_ascii=False).replace("</", "<\\/"))
        (out_dir / f"survey-{rater}.html").write_text(html, encoding="utf-8")
        skeleton = dict(pack, created_utc=created)
        write_json(out_dir / f"pack-{rater}.json", skeleton)
    write_json(out_dir / "frames_provenance.json", provenance)
    short = {k: v["n_frames_shown"] for k, v in provenance.items() if v["n_frames_shown"] < args.n_frames}
    print(f"wrote {len(packs)} surveys → {out_dir}")
    if short:
        print(f"{len(short)} framesets have fewer than {args.n_frames} frames (judge saw the same): {short}")


if __name__ == "__main__":
    main()
