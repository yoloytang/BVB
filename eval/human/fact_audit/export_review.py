#!/usr/bin/env python3
"""Export the optional full-video review round.

Run this only after the main round is scored and locked. It takes
``review_candidates.jsonl`` from the main scoring output: units where a rater
could not verify the answer on 16 frames, where the two raters disagreed, or
where the human label contradicts DV. The same two raters see those units
again, this time with the full reconstruction video and then the full source
video, both re-encoded to at most 640 px wide.

The review answers never replace the main labels. ``score_review.py`` reports
them as a frame-sampling sensitivity analysis.

Each rater gets a folder with ``survey.html`` and a ``videos/`` directory,
zipped as ``survey-review-rNN.zip``. Raters unzip it and open
``survey.html``; the videos load from the folder, so nothing goes online.

Example::

  python eval/human/fact_audit/export_review.py --study eval/human/fact_audit/study/wave1 \\
      --scored eval/human/fact_audit/study/wave1/scored
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from common import (
    REVIEW_INSTRUMENT_ID,
    RESULTS,
    TEST_JSONL,
    VSI_BENCH,
    iter_jsonl,
    load_metadata,
    rec_frameset,
    render_path,
    source_path,
    src_frameset,
    write_json,
)
from export_pack import FORM, PLACEHOLDER, build_packs

MAX_WIDTH = 640


def transcode(ffmpeg: str, src: Path, dst: Path) -> None:
    """Keep every frame and the full duration; shrink resolution and bitrate."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-an",
        "-vf", f"scale='min({MAX_WIDTH},iw)':-2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(dst),
    ]
    done = subprocess.run(command, check=False, capture_output=True, text=True)
    if done.returncode != 0 or not dst.is_file() or dst.stat().st_size < 1000:
        raise RuntimeError(f"ffmpeg failed on {src}: {done.stderr[-400:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--scored", type=Path, required=True, help="Main scoring output directory.")
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--vsi-bench", type=Path, default=VSI_BENCH)
    parser.add_argument("--qa-metadata", type=Path, default=TEST_JSONL)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for the review round")
    design = json.loads((args.study / "design.json").read_text())
    seed = design["seed"]
    candidates = list(iter_jsonl(args.scored / "review_candidates.jsonl"))
    if not candidates:
        raise SystemExit("no review candidates; nothing to export")
    out_dir = args.study / "packs_review"
    if out_dir.exists() and not args.force:
        raise SystemExit(f"{out_dir} exists; pass --force to rebuild")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    cache = args.study / "_review_video_cache"

    metadata = load_metadata(args.qa_metadata)
    packs = build_packs(candidates, metadata, seed, kind="review")

    sources: dict[str, Path] = {}
    for unit in candidates:
        sources[rec_frameset(seed, unit["run"], unit["scene"])] = render_path(args.results_dir, unit["run"], unit["scene"])
        sources[src_frameset(seed, unit["scene"])] = source_path(args.vsi_bench, unit["dataset"], unit["scene"])
    for key, src in sorted(sources.items()):
        if not src.is_file():
            raise SystemExit(f"missing video for {key}: {src}")
        clip = cache / f"{key.split(':', 1)[1]}.mp4"
        if not clip.is_file():
            transcode(ffmpeg, src, clip)

    template = FORM.read_text(encoding="utf-8")
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sizes = {}
    for rater, pack in packs.items():
        folder = out_dir / f"survey-review-{rater}"
        used = sorted({i["frameset"] for b in pack["blocks"] for i in b["recon_items"] + b["source_items"]})
        videos = {}
        for key in used:
            name = f"videos/{key.split(':', 1)[1]}.mp4"
            (folder / "videos").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache / Path(name).name, folder / name)
            videos[key] = name
        pack = dict(pack, instrument_id=REVIEW_INSTRUMENT_ID, created_utc=created)
        public = json.loads(json.dumps(dict(pack, videos=videos, framesets={})))
        for block in public["blocks"]:
            block.pop("scene")
            block.pop("dataset")
            for item in block["recon_items"] + block["source_items"]:
                item.pop("unit_id", None)
                item.pop("qa_id", None)
        html = template.replace(PLACEHOLDER, json.dumps(public, ensure_ascii=False).replace("</", "<\\/"))
        (folder / "survey.html").write_text(html, encoding="utf-8")
        write_json(out_dir / f"pack-review-{rater}.json", pack)
        archive = shutil.make_archive(str(out_dir / f"survey-review-{rater}"), "zip", out_dir, folder.name)
        sizes[rater] = round(Path(archive).stat().st_size / 1e6, 1)
    write_json(out_dir / "review_sources.json", {k: str(v) for k, v in sorted(sources.items())})
    n_items = {r: sum(len(b["recon_items"]) + len(b["source_items"]) for b in p["blocks"]) for r, p in packs.items()}
    print(f"{len(candidates)} review units → {out_dir}; items per rater {n_items}; zip MB {sizes}")


if __name__ == "__main__":
    main()
