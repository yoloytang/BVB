#!/usr/bin/env python3
"""Draw the audit sample and assign scenes to raters.

Two-stage design, fixed by ``--seed`` and recorded in ``design.json``:

1. Scenes: simple random sample of ``--scenes-per-source`` scenes within each
   dataset, from scenes that have at least one eligible unit.
2. Units: inside the sampled scenes, stratify by (configuration, task,
   Dual VQA pass/fail) and draw ``min(N_h, --per-stratum)`` units per stratum.

Each unit's inclusion probability is ``pi = (m_s / M_s) * (n_h / N_h)`` and
its design weight is ``1 / pi``. Analyses must use these weights; a plain mean
over the balanced sample is not a population estimate.

Every scene goes to exactly ``--raters-per-unit`` raters, so one rater
answers all reconstruction questions of a scene before seeing its source
video. Scenes are dealt to the currently least-loaded raters.

A pilot set, if requested, comes from scenes outside the main sample, so pilot
raters never preview main-study scenes.

Example::

  python eval/human/fact_audit/sample.py --study eval/human/fact_audit/study/wave1 \\
      --seed 20261113 --raters 4
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict
from pathlib import Path

from common import iter_jsonl, write_json, write_jsonl


def sample_scenes(units: list[dict], per_source: int, rng: random.Random,
                  exclude: set[str] = frozenset()) -> tuple[list[str], dict[str, dict]]:
    by_ds: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        by_ds[unit["dataset"]].add(unit["scene"])
    chosen: list[str] = []
    scene_prob: dict[str, dict] = {}
    for ds in sorted(by_ds):
        pool = sorted(by_ds[ds] - set(exclude))
        m = min(per_source, len(pool))
        picked = rng.sample(pool, m)
        for scene in picked:
            scene_prob[scene] = {"dataset": ds, "m": m, "M": len(pool), "p": m / len(pool)}
        chosen.extend(sorted(picked))
    return chosen, scene_prob


def stratified_units(units: list[dict], scenes: set[str], per_stratum: int,
                     scene_prob: dict[str, dict], rng: random.Random) -> tuple[list[dict], list[dict]]:
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for unit in units:
        if unit["scene"] in scenes:
            strata[(unit["run"], unit["task"], unit["dv_pass"])].append(unit)
    picked: list[dict] = []
    table: list[dict] = []
    for key in sorted(strata):
        pool = sorted(strata[key], key=lambda u: u["unit_id"])
        n = min(per_stratum, len(pool))
        draw = rng.sample(pool, n)
        table.append({"run": key[0], "task": key[1], "dv_pass": key[2], "N_in_scenes": len(pool), "n": n})
        for unit in draw:
            p_scene = scene_prob[unit["scene"]]["p"]
            pi = p_scene * n / len(pool)
            picked.append(dict(unit, stratum="|".join(map(str, key)), pi=pi, weight=1.0 / pi))
    picked.sort(key=lambda u: (u["scene"], u["unit_id"]))
    return picked, table


def assign_raters(units: list[dict], raters: list[str], per_unit: int,
                  rng: random.Random) -> dict[str, list[str]]:
    if per_unit > len(raters):
        raise SystemExit("--raters-per-unit exceeds the number of raters")
    load = {r: 0 for r in raters}
    scene_rater: dict[str, list[str]] = {}
    size: dict[str, int] = defaultdict(int)
    for unit in units:
        size[unit["scene"]] += 1
    order = sorted(size, key=lambda s: (-size[s], s))
    for scene in order:
        ranked = sorted(raters, key=lambda r: (load[r], rng.random()))
        scene_rater[scene] = sorted(ranked[:per_unit])
        for rater in scene_rater[scene]:
            load[rater] += size[scene]
    return scene_rater


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True,
                        help="Study directory holding manifest.jsonl.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--scenes-per-source", type=int, default=10)
    parser.add_argument("--per-stratum", type=int, default=6)
    parser.add_argument("--raters", type=int, default=4)
    parser.add_argument("--raters-per-unit", type=int, default=2)
    parser.add_argument("--pilot-scenes-per-source", type=int, default=1)
    parser.add_argument("--pilot-per-stratum", type=int, default=1)
    args = parser.parse_args()

    if (args.study / "sample.jsonl").exists():
        raise SystemExit(f"{args.study}/sample.jsonl exists; draw a new wave instead of resampling")
    units = list(iter_jsonl(args.study / "manifest.jsonl"))
    rng = random.Random(args.seed)
    raters = [f"r{i:02d}" for i in range(1, args.raters + 1)]

    scenes, scene_prob = sample_scenes(units, args.scenes_per_source, rng)
    sample, table = stratified_units(units, set(scenes), args.per_stratum, scene_prob, rng)
    scene_rater = assign_raters(sample, raters, args.raters_per_unit, rng)
    for unit in sample:
        unit["raters"] = scene_rater[unit["scene"]]

    pilot: list[dict] = []
    if args.pilot_scenes_per_source > 0:
        pilot_rng = random.Random(args.seed + 1)
        p_scenes, p_prob = sample_scenes(units, args.pilot_scenes_per_source, pilot_rng, exclude=set(scenes))
        pilot, _ = stratified_units(units, set(p_scenes), args.pilot_per_stratum, p_prob, pilot_rng)
        for unit in pilot:
            unit["raters"] = list(raters)
            unit["pilot"] = True

    write_jsonl(args.study / "sample.jsonl", sample)
    if pilot:
        write_jsonl(args.study / "pilot_sample.jsonl", pilot)
    loads = {r: sum(1 for u in sample if r in u["raters"]) for r in raters}
    write_json(args.study / "design.json", {
        "seed": args.seed,
        "sampling_policy": "scene_srs_by_source_then_stratified_units_v1",
        "scenes_per_source": args.scenes_per_source,
        "per_stratum": args.per_stratum,
        "raters": raters,
        "raters_per_unit": args.raters_per_unit,
        "scenes": scene_prob,
        "scene_raters": scene_rater,
        "strata": table,
        "n_units": len(sample),
        "n_unit_ratings": len(sample) * args.raters_per_unit,
        "units_per_rater": loads,
        "pilot_units": len(pilot),
        "pilot_scenes": sorted({u["scene"] for u in pilot}),
    })
    short = [row for row in table if row["n"] < args.per_stratum]
    print(f"{len(sample)} units over {len(scenes)} scenes; load per rater {loads}")
    if short:
        print(f"{len(short)} strata had fewer than {args.per_stratum} eligible units; see design.json")
    if pilot:
        print(f"pilot: {len(pilot)} units over {len({u['scene'] for u in pilot})} scenes")


if __name__ == "__main__":
    main()
