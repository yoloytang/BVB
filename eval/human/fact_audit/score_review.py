#!/usr/bin/env python3
"""Score the full-video review round as a frame-sampling sensitivity analysis.

The main labels come from the same 16 frames the judge saw and stay the
primary result. This script asks how those labels move when the same raters
watch the full reconstruction and source videos:

* rater level: main label on 16 frames -> label with full video
  (e.g. how many "undecidable" become "retained" or "error");
* unit level: main final label -> review final label (two raters agree);
* a sensitivity version of the main table in which each reviewed unit with an
  agreed review label takes that label. Report it next to, never instead of,
  the main table.

Example::

  python eval/human/fact_audit/score_review.py --study eval/human/fact_audit/study/wave1 \\
      --scored eval/human/fact_audit/study/wave1/scored \\
      --responses eval/human/fact_audit/study/wave1/responses_review \\
      --out eval/human/fact_audit/study/wave1/scored_review
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from common import (
    LABELS,
    REVIEW_INSTRUMENT_ID,
    TEST_JSONL,
    iter_jsonl,
    load_metadata,
    rec_item_id,
    run_code,
    src_item_id,
    write_json,
)
from score_fact_audit import (
    classify,
    cluster_bootstrap,
    estimates,
    load_responses,
    rater_label,
    write_csv,
)

DISAGREE = "review_disagree"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--scored", type=Path, required=True, help="Main scoring output directory.")
    parser.add_argument("--responses", type=Path, required=True, help="Returned review-round JSON files.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--qa-metadata", type=Path, default=TEST_JSONL)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    seed = json.loads((args.study / "design.json").read_text())["seed"]
    metadata = load_metadata(args.qa_metadata)
    candidates = list(iter_jsonl(args.scored / "review_candidates.jsonl"))
    responses = load_responses(args.responses, REVIEW_INSTRUMENT_ID)

    rater_moves: Counter = Counter()
    unit_moves: Counter = Counter()
    rows = []
    review_final: dict[str, str] = {}
    for cand in candidates:
        qa = metadata[cand["qa_id"]]
        labels = {}
        for slot in cand["raters"]:
            resp = responses.get(slot)
            ans = {a["item_id"]: a for a in resp["answers"]} if resp else {}
            src = classify(ans.get(src_item_id(seed, cand["qa_id"])), qa)
            rec = classify(ans.get(rec_item_id(seed, cand["unit_id"])), qa)
            labels[slot] = rater_label(src, rec)
            if labels[slot]:
                rater_moves[(cand["main_rater_labels"][slot], labels[slot])] += 1
        vals = list(labels.values())
        if not all(vals):
            final = "missing"
        elif len(set(vals)) == 1:
            final = vals[0]
            review_final[cand["unit_id"]] = final
        else:
            final = DISAGREE
        unit_moves[(cand["main_final"], final)] += 1
        rows.append({"unit_id": cand["unit_id"], "run": run_code(cand["run"]), "scene": cand["scene"],
                     "qa_id": cand["qa_id"], "why": ";".join(cand["why"]), "main_final": cand["main_final"],
                     "main_rater_labels": ";".join(f"{k}={v}" for k, v in cand["main_rater_labels"].items()),
                     "review_rater_labels": ";".join(f"{k}={v}" for k, v in labels.items()),
                     "review_final": final})

    # Sensitivity table: main labels, with agreed review labels substituted.
    units = []
    with (args.scored / "units_scored.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["final"] not in LABELS:
                continue
            units.append({"run": row["run"], "scene": row["scene"], "dataset": row["dataset"],
                          "dv_pass": row["dv_pass"] == "True", "weight": float(row["weight"]),
                          "final": review_final.get(row["unit_id"], row["final"]),
                          "main_final": row["final"]})
    runs = list(dict.fromkeys(u["run"] for u in units))
    scopes = ["pooled"] + runs
    sens = estimates(units, scopes)
    main = estimates([dict(u, final=u["main_final"]) for u in units], scopes)
    ci = cluster_bootstrap(units, scopes, args.bootstrap, args.seed) if args.bootstrap and units else {}
    compare = []
    for key in sorted(sens):
        lo, hi, _ = ci.get(key, (None, None, 0))
        scope, *rest = key.split("|")
        compare.append({"scope": run_code(scope), "quantity": "|".join(rest), "main_16_frames": main.get(key),
                        "with_full_video_review": sens[key], "review_ci_low": lo, "review_ci_high": hi})

    from_undecidable = {k[1]: v for k, v in rater_moves.items() if k[0] == "undecidable"}
    from_src_unverified = {k[1]: v for k, v in rater_moves.items() if k[0] == "source_unverified"}
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "review_units.csv", rows, list(rows[0].keys()) if rows else ["unit_id"])
    write_csv(args.out / "rater_transitions.csv",
              [{"main_label_16_frames": a, "review_label_full_video": b, "n": n} for (a, b), n in sorted(rater_moves.items())],
              ["main_label_16_frames", "review_label_full_video", "n"])
    write_csv(args.out / "unit_transitions.csv",
              [{"main_final": a, "review_final": b, "n": n} for (a, b), n in sorted(unit_moves.items())],
              ["main_final", "review_final", "n"])
    write_csv(args.out / "main_vs_review.csv", compare, ["scope", "quantity", "main_16_frames",
                                                          "with_full_video_review", "review_ci_low", "review_ci_high"])
    write_json(args.out / "summary.json", {
        "n_candidates": len(candidates),
        "n_with_agreed_review_label": len(review_final),
        "responses": {s: {"file": r["_file"], "n_answers": len(r["answers"])} for s, r in responses.items()},
        "rater_level": {
            "from_undecidable": from_undecidable,
            "from_source_unverified": from_src_unverified,
        },
        "note": "Main labels use the judge's 16 frames and remain the primary result. "
                "Review labels use full videos and measure sensitivity to frame sampling.",
    })
    print(f"{len(candidates)} review units; {len(review_final)} with agreed review labels → {args.out}")


if __name__ == "__main__":
    main()
