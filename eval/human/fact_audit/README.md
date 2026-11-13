# BVB fact-retention audit

This study checks, question by question, whether a Dual VQA (DV) pass or fail
on a reconstruction matches what a person can read from **the same frames the
judge saw**. It answers reviewer zxyz's question of whether a DV fail means the
fact was omitted or that a preserved fact was misread in a primitive render. It
also records, for confirmed errors, whether the agent misperceived the fact or
perceived it and failed to build it.

The study reuses existing renders. It does not rerun any agent or the judge.

## Design in one paragraph

A unit is one (configuration, question) pair from the DV denominator: the judge
answered it correctly on the source, and the configuration rendered the scene.
Only question types a person can answer by eye are included: counting,
relative distance, relative direction, route planning and appearance order.
Metric tasks (object size, absolute distance, room size) go to the separate
`.blend` geometry check. Scenes are sampled at random within each dataset, then
units are stratified by configuration × task × DV pass/fail. Every unit carries
an inclusion probability, and all estimates are design-weighted. Two raters
answer each unit. For each scene, a rater first answers every reconstruction
item, one reconstruction at a time, and only then sees the source frames and
answers the same questions on the source. Answers lock on submit, and the
analysis checks the submission timestamps.

## Commands

Run from the repository root. Results must be under `sandbox/results/` (see
`scripts/download_results.py`) and source videos under `VSI-Bench/`.

```bash
python scripts/download_results.py \
  --run mini-harness-gpt-6-astra-reasoning-high-run01 \
  --run mini-harness-gpt-5.6-sol-reasoning-xhigh-run01 \
  --run mini-harness-qwen3.5-397b-a17b-run01 \
  --run _dual_vqa_shared
```

1. Freeze the eligible population. Running it again on the same directory is refused.

   ```bash
   python eval/human/fact_audit/build_manifest.py --out eval/human/fact_audit/study/wave1
   ```

2. Draw the sample, the pilot and the rater assignment.

   ```bash
   python eval/human/fact_audit/sample.py --study eval/human/fact_audit/study/wave1 \
     --seed 20261113 --scenes-per-source 10 --per-stratum 6 --raters 4
   ```

3. Export the surveys. The pilot uses scenes outside the main sample.

   ```bash
   python eval/human/fact_audit/export_pack.py --study eval/human/fact_audit/study/wave1 --pilot
   python eval/human/fact_audit/export_pack.py --study eval/human/fact_audit/study/wave1
   ```

   Send `packs/survey-rNN.html` to rater slot `rNN`. Keep `pack-rNN.json`,
   `frames_provenance.json` and everything else with the experimenter.

4. Put returned JSON files in `study/wave1/responses/` and score them.

   ```bash
   python eval/human/fact_audit/score_fact_audit.py --study eval/human/fact_audit/study/wave1 \
     --responses eval/human/fact_audit/study/wave1/responses \
     --out eval/human/fact_audit/study/wave1/scored
   ```

5. Have a third person fill `final_label` in `scored/adjudicate_labels.csv`.
   This file is blind: it shows no model and no DV result. Rerun step 4 with
   `--labels`. Then fill `locus_todo.csv` for every confirmed error, using the
   agent log and the `.blend`, and rerun with `--locus`.

## Labels

| Label | Meaning |
| --- | --- |
| `retained` | Human answers the source correctly, and the reconstruction frames support the same correct answer |
| `error` | Human answers the source correctly, and the reconstruction frames support a wrong answer |
| `undecidable` | Human answers the source correctly, but cannot answer from the reconstruction frames |
| `source_unverified` | Human cannot reach the benchmark answer on the source frames; reported separately, not in the main table |

The locus labels are `perception`, `implementation`, `both` and `unclear`.
`perception` means the agent's own log states the fact wrongly.
`implementation` means the log states it correctly, but the `.blend` does not
realize it. Record the evidence for each.

## Outputs

| File | Contents |
| --- | --- |
| `dv_by_human.csv` | For each configuration and pooled: within DV fail and DV pass, the weighted shares of retained, error and undecidable, with 95% scene-bootstrap CIs and raw counts |
| `ranking.csv` | For each configuration: DV rate and human retention on the same units, and their ranks |
| `by_task.csv` | Raw counts and weighted retained share by task and DV status |
| `summary.json` | Agreement (raw and Fleiss' κ, computed before adjudication), point estimates, reason tags, locus counts and order checks |
| `units_scored.csv` | One row per unit with its final label and how it was reached |

Do not report `1 − DV` as a fact-loss rate, and do not turn these numbers into
a corrected leaderboard. They estimate the sampled configurations on the
eligible question types only.

## Tests

```bash
python -m pytest eval/tests/test_fact_audit.py
```

The tests build a synthetic results tree and run the full pipeline. They check
that the surveys leak no model name, scene name, answer or DV result, that
disagreements reach adjudication, that a source-before-reconstruction order is
flagged, and that the exported frames are byte-identical to what
`dual_vqa_metric.sample_frames_b64` sends the judge.
