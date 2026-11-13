#!/usr/bin/env python3
"""Score returned fact-audit surveys against Dual VQA.

Per (unit, rater):
  source answer wrong or "cannot tell"  -> source_unverified
  else recon "cannot tell"              -> undecidable
  else recon answer right / wrong       -> retained / error
Answers are matched with the benchmark's own ``semantic_correct`` rules.

Two raters per unit. Agreement gives the final label; disagreements go to
``adjudicate_labels.csv`` (blind: no model, no DV result). Units whose final
label is ``error`` go to ``locus_todo.csv``, where an adjudicator with access
to the agent log and .blend records whether the fact was misperceived or
perceived but not built. Fill those files and pass them back with
``--labels`` and ``--locus``.

All proportions are design-weighted (weight = 1 / inclusion probability) and
come with 95% scene-cluster bootstrap intervals that resample scenes within
each dataset.

Example::

  python eval/human/fact_audit/score_fact_audit.py --study eval/human/fact_audit/study/wave1 \\
      --responses eval/human/fact_audit/study/wave1/responses --out eval/human/fact_audit/study/wave1/scored
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from common import (
    H_ERROR,
    H_RETAINED,
    H_UNDECIDABLE,
    INSTRUMENT_ID,
    LABELS,
    LOCUS_TAGS,
    PENDING,
    SRC_UNVERIFIED,
    TEST_JSONL,
    answer_correct,
    iter_jsonl,
    load_metadata,
    rec_item_id,
    run_code,
    src_item_id,
    write_json,
)


# ----------------------------------------------------------------- loading
def load_responses(resp_dir: Path) -> dict[str, dict]:
    """rater_slot -> response; when a slot has several files keep the most complete."""
    out: dict[str, dict] = {}
    for path in sorted(resp_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("instrument_id") != INSTRUMENT_ID:
            continue
        slot = data.get("rater_slot") or data["pack_id"].rsplit("-", 1)[-1]
        data["_file"] = path.name
        old = out.get(slot)
        if old is None or (len(data["answers"]), data.get("exported_utc", "")) > (
            len(old["answers"]), old.get("exported_utc", "")
        ):
            out[slot] = data
    return out


def classify(ans: dict | None, qa: dict) -> str | None:
    """'correct' | 'wrong' | 'cannot_tell' | None (missing)."""
    if ans is None:
        return None
    if ans.get("cannot_tell"):
        return "cannot_tell"
    if ans.get("answer") in (None, ""):
        return None
    return "correct" if answer_correct(ans["answer"], qa) else "wrong"


def rater_label(src: str | None, rec: str | None) -> str | None:
    if src is None or rec is None:
        return None
    if src != "correct":
        return SRC_UNVERIFIED
    if rec == "cannot_tell":
        return H_UNDECIDABLE
    return H_RETAINED if rec == "correct" else H_ERROR


def read_csv_map(path: Path | None, key: str) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        return {row[key]: row for row in csv.DictReader(handle) if row.get(key)}


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------- statistics
def fleiss_kappa(pairs: list[tuple[str, str]], categories: list[str]) -> float | None:
    """Fleiss' kappa with two ratings per item (raters differ across items)."""
    if not pairs:
        return None
    n_items, n = len(pairs), 2
    p_items = []
    totals = Counter()
    for a, b in pairs:
        counts = Counter([a, b])
        totals.update(counts)
        p_items.append((sum(c * c for c in counts.values()) - n) / (n * (n - 1)))
    p_bar = sum(p_items) / n_items
    p_e = sum((totals[c] / (n_items * n)) ** 2 for c in categories)
    if p_e >= 1:
        return None
    return (p_bar - p_e) / (1 - p_e)


def weighted_share(units: list[dict], num: Callable[[dict], bool], den: Callable[[dict], bool]) -> float | None:
    d = sum(u["weight"] for u in units if den(u))
    if d <= 0:
        return None
    return sum(u["weight"] for u in units if den(u) and num(u)) / d


def estimates(units: list[dict], scopes: list[str]) -> dict[str, float | None]:
    """Flat dict of every weighted quantity reported, for point estimates and bootstrap."""
    out: dict[str, float | None] = {}
    for scope in scopes:
        su = [u for u in units if scope == "pooled" or u["run"] == scope]
        for dv_name, dv in (("fail", False), ("pass", True)):
            g = [u for u in su if u["dv_pass"] == dv]
            out[f"{scope}|{dv_name}|source_unverified"] = weighted_share(
                g, lambda u: u["final"] == SRC_UNVERIFIED, lambda u: True)
            for lab in (H_RETAINED, H_ERROR, H_UNDECIDABLE):
                out[f"{scope}|{dv_name}|{lab}"] = weighted_share(
                    g, lambda u, lab=lab: u["final"] == lab, lambda u: u["final"] != SRC_UNVERIFIED)
            out[f"{scope}|{dv_name}|retained_among_decidable"] = weighted_share(
                g, lambda u: u["final"] == H_RETAINED, lambda u: u["final"] in (H_RETAINED, H_ERROR))
        verified = [u for u in su if u["final"] != SRC_UNVERIFIED]
        out[f"{scope}|dv_rate_sampled"] = weighted_share(su, lambda u: u["dv_pass"], lambda u: True)
        out[f"{scope}|dv_rate_source_verified"] = weighted_share(verified, lambda u: u["dv_pass"], lambda u: True)
        out[f"{scope}|human_retention"] = weighted_share(verified, lambda u: u["final"] == H_RETAINED, lambda u: True)
        out[f"{scope}|human_retention_decidable"] = weighted_share(
            verified, lambda u: u["final"] == H_RETAINED, lambda u: u["final"] in (H_RETAINED, H_ERROR))
        out[f"{scope}|dv_human_agreement"] = weighted_share(
            verified, lambda u: u["dv_pass"] == (u["final"] == H_RETAINED),
            lambda u: u["final"] in (H_RETAINED, H_ERROR))
    return out


def cluster_bootstrap(units: list[dict], scopes: list[str], reps: int, seed: int) -> dict[str, tuple]:
    rng = random.Random(seed)
    by_scene: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        by_scene[u["scene"]].append(u)
    by_ds: dict[str, list[str]] = defaultdict(list)
    for scene, group in by_scene.items():
        by_ds[group[0]["dataset"]].append(scene)
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(reps):
        sample: list[dict] = []
        for ds in sorted(by_ds):
            scenes = by_ds[ds]
            for _ in scenes:
                sample.extend(by_scene[rng.choice(scenes)])
        for key, value in estimates(sample, scopes).items():
            if value is not None:
                draws[key].append(value)
    ci = {}
    for key, vals in draws.items():
        vals.sort()
        lo = vals[int(0.025 * (len(vals) - 1))]
        hi = vals[int(0.975 * (len(vals) - 1))]
        ci[key] = (lo, hi, len(vals))
    return ci


# -------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--labels", type=Path, help="Filled adjudicate_labels.csv")
    parser.add_argument("--locus", type=Path, help="Filled locus_todo.csv")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--qa-metadata", type=Path, default=TEST_JSONL)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    design = json.loads((args.study / "design.json").read_text())
    units = list(iter_jsonl(args.study / ("pilot_sample.jsonl" if args.pilot else "sample.jsonl")))
    metadata = load_metadata(args.qa_metadata)
    responses = load_responses(args.responses)
    pack_dir = args.study / ("packs_pilot" if args.pilot else "packs")
    adjudicated = read_csv_map(args.labels, "case_id")
    locus_in = read_csv_map(args.locus, "case_id")

    def case_id(unit_id: str) -> str:
        return hashlib.sha1(f"{design['seed']}:{unit_id}".encode()).hexdigest()[:10]

    # Order check: every recon answer of a scene precedes every source answer of that scene.
    violations = []
    for slot, resp in responses.items():
        pack = json.loads((pack_dir / f"pack-{slot}.json").read_text())
        ans = {a["item_id"]: a for a in resp["answers"]}
        for block in pack["blocks"]:
            rec_t = [ans[i["item_id"]]["submitted_utc"] for i in block["recon_items"] if i["item_id"] in ans]
            src_t = [ans[i["item_id"]]["submitted_utc"] for i in block["source_items"] if i["item_id"] in ans]
            if rec_t and src_t and max(rec_t) > min(src_t):
                violations.append({"rater_slot": slot, "scene": block["scene"],
                                   "last_recon": max(rec_t), "first_source": min(src_t)})

    rows, adjudicate, pair_labels, pair_src, pair_rec = [], [], [], [], []
    reason_counts: dict[str, Counter] = defaultdict(Counter)
    for unit in units:
        qa = metadata[unit["qa_id"]]
        per_rater = []
        for slot in unit["raters"]:
            resp = responses.get(slot)
            ans = {a["item_id"]: a for a in resp["answers"]} if resp else {}
            rec_a = ans.get(rec_item_id(design["seed"], unit["unit_id"]))
            src_a = ans.get(src_item_id(design["seed"], unit["qa_id"]))
            src, rec = classify(src_a, qa), classify(rec_a, qa)
            per_rater.append({"slot": slot, "src": src, "rec": rec, "label": rater_label(src, rec),
                              "rec_answer": None if rec_a is None else ("?" if rec_a.get("cannot_tell") else rec_a.get("answer")),
                              "src_answer": None if src_a is None else ("?" if src_a.get("cannot_tell") else src_a.get("answer")),
                              "reasons": [] if rec_a is None else rec_a.get("reasons", []),
                              "note": "" if rec_a is None else rec_a.get("note", "")})
        labels = [r["label"] for r in per_rater]
        cid = case_id(unit["unit_id"])
        if all(labels) and len(set(labels)) == 1:
            final, how = labels[0], "agreement"
        elif cid in adjudicated and adjudicated[cid].get("final_label") in LABELS:
            final, how = adjudicated[cid]["final_label"], "adjudicated"
        else:
            final, how = PENDING, ("missing_response" if not all(labels) else "disagreement")
        if len(per_rater) == 2 and all(labels):
            pair_labels.append((labels[0], labels[1]))
            pair_src.append(tuple("ok" if r["src"] == "correct" else "no" for r in per_rater))
            if all(r["src"] == "correct" for r in per_rater):
                pair_rec.append(tuple(r["rec"] for r in per_rater))
        if how == "disagreement" or how == "missing_response":
            entry = {"case_id": cid, "question": qa["question"], "options": " | ".join(qa.get("options") or []),
                     "ground_truth": qa["ground_truth"], "issue": how, "final_label": "", "notes": ""}
            for i, r in enumerate(per_rater):
                tag = "ab"[i] if i < 2 else str(i)
                entry.update({f"rater_{tag}": r["slot"], f"label_{tag}": r["label"] or "missing",
                              f"recon_answer_{tag}": r["rec_answer"], f"source_answer_{tag}": r["src_answer"],
                              f"reasons_{tag}": ";".join(r["reasons"]), f"note_{tag}": r["note"]})
            adjudicate.append(entry)
        for r in per_rater:
            for tag in r["reasons"]:
                reason_counts[final][tag] += 1
        rows.append(dict(unit, case_id=cid, final=final, final_how=how,
                         rater_labels=";".join(f"{r['slot']}={r['label']}" for r in per_rater)))

    resolved = [u for u in rows if u["final"] != PENDING]
    runs = list(dict.fromkeys(u["run"] for u in units))
    scopes = ["pooled"] + runs
    point = estimates(resolved, scopes)
    ci = cluster_bootstrap(resolved, scopes, args.bootstrap, args.seed) if args.bootstrap else {}

    def est_row(key: str, **extra) -> dict:
        lo, hi, n_ok = ci.get(key, (None, None, 0))
        return dict(extra, estimate=point.get(key), ci_low=lo, ci_high=hi, bootstrap_defined=n_ok)

    table = []
    for scope in scopes:
        su = [u for u in resolved if scope == "pooled" or u["run"] == scope]
        for dv_name, dv in (("fail", False), ("pass", True)):
            g = [u for u in su if u["dv_pass"] == dv]
            raw = Counter(u["final"] for u in g)
            for lab in (H_RETAINED, H_ERROR, H_UNDECIDABLE, "retained_among_decidable", SRC_UNVERIFIED):
                denom = "all resolved" if lab == SRC_UNVERIFIED else (
                    "retained+error" if lab == "retained_among_decidable" else "source verified")
                table.append(est_row(f"{scope}|{dv_name}|{lab}", scope=run_code(scope), dv=dv_name, quantity=lab,
                                     denominator=denom, n_raw=raw.get(lab, "") if lab in LABELS else "",
                                     n_group=len(g)))
    ranking = []
    for scope in runs:
        r = {"run": run_code(scope)}
        for q in ("dv_rate_sampled", "dv_rate_source_verified", "human_retention",
                  "human_retention_decidable", "dv_human_agreement"):
            e = est_row(f"{scope}|{q}")
            r[q], r[f"{q}_ci"] = e["estimate"], (e["ci_low"], e["ci_high"])
        ranking.append(r)
    for key in ("dv_rate_source_verified", "human_retention"):
        order = sorted((x for x in ranking if x[key] is not None), key=lambda x: -x[key])
        for i, x in enumerate(order, 1):
            x[f"rank_by_{key}"] = i

    by_task = []
    task_groups: dict[tuple, list[dict]] = defaultdict(list)
    for u in resolved:
        task_groups[(u["task"], u["answer_format"])].append(u)
    for (task, fmt), group in sorted(task_groups.items()):
        for dv_name, dv in (("fail", False), ("pass", True)):
            g = [u for u in group if u["dv_pass"] == dv]
            raw = Counter(u["final"] for u in g)
            by_task.append({"task": task, "answer_format": fmt, "dv": dv_name, "n": len(g),
                            **{f"n_{lab}": raw.get(lab, 0) for lab in LABELS},
                            "w_retained_given_verified": weighted_share(
                                g, lambda u: u["final"] == H_RETAINED, lambda u: u["final"] != SRC_UNVERIFIED)})

    locus_rows, locus_counts = [], defaultdict(Counter)
    for u in resolved:
        if u["final"] != H_ERROR:
            continue
        filled = locus_in.get(u["case_id"], {})
        tag = filled.get("locus", "")
        if tag in LOCUS_TAGS:
            locus_counts[run_code(u["run"])][tag] += 1
        qa = metadata[u["qa_id"]]
        locus_rows.append({"case_id": u["case_id"], "run": u["run"], "scene": u["scene"], "qa_id": u["qa_id"],
                           "task": u["task"], "question": qa["question"], "ground_truth": qa["ground_truth"],
                           "agent_meta": f"{u['run']}/agent_meta/{u['scene']}.json",
                           "blend": f"{u['run']}/blends/{u['scene']}.blend",
                           "object_in_blend": filled.get("object_in_blend", ""),
                           "agent_stated_fact": filled.get("agent_stated_fact", ""),
                           "locus": tag, "evidence": filled.get("evidence", "")})

    agreement = {
        "n_pairs": len(pair_labels),
        "raw_agreement_final_label": (sum(a == b for a, b in pair_labels) / len(pair_labels)) if pair_labels else None,
        "fleiss_kappa_final_label": fleiss_kappa(pair_labels, LABELS),
        "fleiss_kappa_source_verified": fleiss_kappa(pair_src, ["ok", "no"]),
        "fleiss_kappa_recon_given_source_ok": fleiss_kappa(pair_rec, ["correct", "wrong", "cannot_tell"]),
        "note": "Computed before adjudication; two ratings per unit, raters vary across units.",
    }

    args.out.mkdir(parents=True, exist_ok=True)
    unit_fields = ["unit_id", "case_id", "run", "scene", "dataset", "qa_id", "task", "answer_format",
                   "dv_pass", "final", "final_how", "rater_labels", "weight", "pi"]
    write_csv(args.out / "units_scored.csv", rows, unit_fields)
    write_csv(args.out / "dv_by_human.csv", table, ["scope", "dv", "quantity", "denominator", "n_raw", "n_group",
                                                     "estimate", "ci_low", "ci_high", "bootstrap_defined"])
    write_csv(args.out / "ranking.csv", ranking, list(ranking[0].keys()) if ranking else ["run"])
    write_csv(args.out / "by_task.csv", by_task, list(by_task[0].keys()) if by_task else ["task"])
    adj_fields = ["case_id", "issue", "question", "options", "ground_truth"] + [
        f"{p}_{t}" for t in "ab" for p in ("rater", "label", "recon_answer", "source_answer", "reasons", "note")
    ] + ["final_label", "notes"]
    write_csv(args.out / "adjudicate_labels.csv", adjudicate, adj_fields)
    write_csv(args.out / "locus_todo.csv", locus_rows, list(locus_rows[0].keys()) if locus_rows else ["case_id"])
    write_csv(args.out / "order_violations.csv", violations, ["rater_slot", "scene", "last_recon", "first_source"])
    write_json(args.out / "summary.json", {
        "n_units": len(rows),
        "n_resolved": len(resolved),
        "n_pending": len(rows) - len(resolved),
        "final_label_counts": Counter(u["final"] for u in rows),
        "responses": {slot: {"file": r["_file"], "n_answers": len(r["answers"]), "complete": r.get("complete")}
                      for slot, r in responses.items()},
        "missing_raters": sorted(set(design["raters"]) - set(responses)),
        "order_violations": len(violations),
        "agreement": agreement,
        "point_estimates": point,
        "bootstrap": {"reps": args.bootstrap, "unit": "scene within dataset", "seed": args.seed},
        "reason_tags_by_final_label": {k: dict(v) for k, v in reason_counts.items()},
        "locus_by_run": {k: dict(v) for k, v in locus_counts.items()},
        "locus_unfilled": sum(1 for r in locus_rows if r["locus"] not in LOCUS_TAGS),
        "label_definitions": {
            H_RETAINED: "source verified by the human; recon frames support the correct answer",
            H_ERROR: "source verified; recon frames support a wrong answer",
            H_UNDECIDABLE: "source verified; recon frames insufficient to answer",
            SRC_UNVERIFIED: "human could not reach the benchmark target on the source frames",
        },
    })
    print(f"{len(resolved)}/{len(rows)} units resolved; {len(adjudicate)} need adjudication; "
          f"{len(violations)} order violations → {args.out}")


if __name__ == "__main__":
    main()
