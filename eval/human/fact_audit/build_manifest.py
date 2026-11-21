#!/usr/bin/env python3
"""Freeze the eligible population for the fact-retention audit.

A unit is one (configuration, question) pair. It is eligible when

* the judge answered the question correctly on the source video
  (it is in the Dual VQA denominator),
* the configuration produced a scored render for that scene, and
* the question type is one a human can answer by eye (``HUMAN_TASKS``),
  unless ``--include-metric-tasks`` is given.

The manifest stores the judge's answers for back-end analysis only; they are
never written into rater packs.

Example::

  python eval/human/fact_audit/build_manifest.py --out eval/human/fact_audit/study/wave1
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from common import (
    DEFAULT_RUNS,
    HUMAN_TASKS,
    METRIC_TASKS,
    ORIGINAL_ANSWERS,
    RESULTS,
    SHARED_DIRNAME,
    TEST_JSONL,
    iter_jsonl,
    load_metadata,
    render_path,
    run_code,
    write_json,
    write_jsonl,
)


def build(
    *,
    runs: list[str],
    results: Path,
    qa_metadata: Path,
    include_metric_tasks: bool,
    require_render_file: bool,
) -> tuple[list[dict], dict]:
    metadata = load_metadata(qa_metadata)
    tasks = dict(HUMAN_TASKS)
    if include_metric_tasks:
        tasks.update(METRIC_TASKS)

    bank_path = results / SHARED_DIRNAME / ORIGINAL_ANSWERS
    if not bank_path.is_file():
        raise SystemExit(f"missing shared judge answers: {bank_path}")
    source_bank = {str(row["qa_id"]): row for row in iter_jsonl(bank_path)}

    units: list[dict] = []
    excluded: dict[str, Counter] = defaultdict(Counter)
    population_dv: dict[str, dict] = {}
    for run in runs:
        dv_path = results / run / "dual_vqa.jsonl"
        if not dv_path.is_file():
            raise SystemExit(f"missing {dv_path}")
        n_den = n_ret = 0
        for row in iter_jsonl(dv_path):
            qa_id = str(row["qa_id"])
            qa = metadata.get(qa_id)
            src = source_bank.get(qa_id)
            if qa is None:
                excluded[run]["not_in_metadata"] += 1
                continue
            if row.get("status", "ok") != "ok":
                excluded[run]["judge_error"] += 1
                continue
            if src is None or not src.get("correct"):
                excluded[run]["source_not_judge_correct"] += 1
                continue
            qtype = str(qa["question_type"])
            if qtype not in tasks:
                excluded[run]["task_not_human_answerable"] += 1
                continue
            scene = str(qa["scene_name"])
            if require_render_file and not render_path(results, run, scene).is_file():
                excluded[run]["render_file_missing"] += 1
                continue
            dv_pass = bool(row.get("rendered_correct"))
            n_den += 1
            n_ret += int(dv_pass)
            units.append(
                {
                    "unit_id": f"{run_code(run)}:{qa_id}",
                    "run": run,
                    "qa_id": qa_id,
                    "scene": scene,
                    "dataset": str(qa["dataset"]),
                    "question_type": qtype,
                    "task": tasks[qtype],
                    "answer_format": "count" if qtype == "object_counting" else (
                        "mc" if qa.get("options") else "number"
                    ),
                    "dv_pass": dv_pass,
                    "judge_source_answer": src.get("answer"),
                    "judge_recon_answer": row.get("rendered_answer"),
                    "ground_truth": str(qa["ground_truth"]),
                    "judge_n_frames": row.get("n_frames"),
                }
            )
        population_dv[run] = {
            "n_eligible": n_den,
            "n_dv_pass": n_ret,
            "dv_on_eligible": (n_ret / n_den) if n_den else None,
        }

    strata = Counter((u["run"], u["task"], u["dv_pass"]) for u in units)
    summary = {
        "runs": runs,
        "include_metric_tasks": include_metric_tasks,
        "tasks": sorted(set(tasks.values())),
        "n_units": len(units),
        "n_scenes": len({u["scene"] for u in units}),
        "scenes_by_dataset": {
            ds: len({u["scene"] for u in units if u["dataset"] == ds})
            for ds in sorted({u["dataset"] for u in units})
        },
        "population_dv": population_dv,
        "excluded": {run: dict(c) for run, c in excluded.items()},
        "strata": [
            {"run": r, "task": t, "dv_pass": d, "N": n}
            for (r, t, d), n in sorted(strata.items())
        ],
    }
    return units, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", dest="runs",
                        help="Run directory name; repeat. Defaults to Astra-high, Sol-xhigh, Qwen3.5-397B.")
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    parser.add_argument("--qa-metadata", type=Path, default=TEST_JSONL)
    parser.add_argument("--include-metric-tasks", action="store_true")
    parser.add_argument("--skip-render-check", action="store_true",
                        help="Do not require camera_renders/<scene>.mp4 on disk.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    units, summary = build(
        runs=args.runs or list(DEFAULT_RUNS),
        results=args.results_dir,
        qa_metadata=args.qa_metadata,
        include_metric_tasks=args.include_metric_tasks,
        require_render_file=not args.skip_render_check,
    )
    if (args.out / "manifest.jsonl").exists():
        raise SystemExit(f"{args.out}/manifest.jsonl exists; the manifest is frozen once written")
    write_jsonl(args.out / "manifest.jsonl", units)
    write_json(args.out / "manifest_summary.json", summary)
    print(f"{summary['n_units']} eligible units over {summary['n_scenes']} scenes → {args.out}")


if __name__ == "__main__":
    main()
