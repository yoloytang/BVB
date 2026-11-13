"""End-to-end check of the fact-audit pipeline on a synthetic results tree."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

FA = Path(__file__).resolve().parents[1] / "human" / "fact_audit"
sys.path.insert(0, str(FA))
import common  # noqa: E402

RUNS = ["mini-harness-strong-run01", "mini-harness-mid-run01", "mini-harness-weak-run01"]
DATASETS = ["arkitscenes", "scannet", "scannetpp"]
MC_OPTIONS = ["A. front-left", "B. front-right", "C. back-left", "D. back-right"]


def write_video(path: Path, frames: int = 20, seed: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    rng = np.random.default_rng(seed)
    for _ in range(frames):
        writer.write(rng.integers(0, 255, (48, 64, 3), dtype=np.uint8))
    writer.release()


def run(script: str, *args: str) -> str:
    out = subprocess.run([sys.executable, str(FA / script), *args], check=True, capture_output=True, text=True)
    return out.stdout


class FactAuditPipelineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.results, self.vsi, self.study = root / "results", root / "vsi", root / "study"
        self.meta_path = root / "test.jsonl"
        meta, originals = [], []
        qid = 0
        for d, ds in enumerate(DATASETS):
            for s in range(2):
                scene = f"{ds}_{s}"
                write_video(self.vsi / ds / f"{scene}.mp4", seed=d * 10 + s)
                for qtype, gt, opts in (("object_counting", "3", None),
                                        ("object_rel_direction_hard", "A", MC_OPTIONS),
                                        ("object_size_estimation", "120", None)):
                    meta.append({"id": qid, "dataset": ds, "scene_name": scene, "question_type": qtype,
                                 "question": f"Q{qid} about {scene}?", "ground_truth": gt, "options": opts})
                    originals.append({"qa_id": str(qid), "answer": gt, "correct": True})
                    qid += 1
        self.meta = {str(m["id"]): m for m in meta}
        self.meta_path.write_text("".join(json.dumps(m) + "\n" for m in meta))
        shared = self.results / "_dual_vqa_shared"
        shared.mkdir(parents=True)
        (shared / "original_answers.jsonl").write_text("".join(json.dumps(o) + "\n" for o in originals))
        for r, name in enumerate(RUNS):
            rows = []
            for m in meta:
                write_video(self.results / name / "camera_renders" / f"{m['scene_name']}.mp4", seed=100 + r)
                passed = (m["id"] + r) % 2 == 0
                rows.append({"qa_id": str(m["id"]), "status": "ok", "rendered_correct": passed,
                             "rendered_answer": m["ground_truth"] if passed else "7", "n_frames": 16})
            (self.results / name / "dual_vqa.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))

    def pipeline(self):
        common_args = ["--results-dir", str(self.results), "--qa-metadata", str(self.meta_path)]
        args = []
        for name in RUNS:
            args += ["--run", name]
        run("build_manifest.py", *args, *common_args, "--out", str(self.study))
        run("sample.py", "--study", str(self.study), "--seed", "7", "--scenes-per-source", "1",
            "--per-stratum", "5", "--raters", "3", "--pilot-scenes-per-source", "1")
        run("export_pack.py", "--study", str(self.study), *common_args, "--vsi-bench", str(self.vsi))

    def fake_responses(self, flip_one: bool = False, source_first_slot: str | None = None):
        resp_dir = self.study / "responses"
        resp_dir.mkdir()
        sample = {u["unit_id"]: u for u in common.iter_jsonl(self.study / "sample.jsonl")}
        flipped = False
        for pack_path in sorted((self.study / "packs").glob("pack-*.json")):
            pack = json.loads(pack_path.read_text())
            answers, t = [], 0
            for block in pack["blocks"]:
                items = block["recon_items"] + block["source_items"]
                if pack["rater_slot"] == source_first_slot:
                    items = block["source_items"] + block["recon_items"]
                for item in items:
                    t += 1
                    unit = sample.get(item.get("unit_id"))
                    qa_id = item["qa_id"] if item["stage"] == "source" else unit["qa_id"]
                    gt = self.meta[qa_id]["ground_truth"]
                    if item["stage"] == "source":
                        answer = gt
                    else:
                        answer = gt if unit["dv_pass"] else ("B" if item["answer_format"] == "mc" else "9")
                        if flip_one and not flipped and pack["rater_slot"] == unit["raters"][0]:
                            answer, flipped = ("B" if answer == gt else gt) if item["answer_format"] == "mc" else (
                                "9" if answer == gt else gt), True
                    answers.append({"item_id": item["item_id"], "stage": item["stage"],
                                    "answer": answer, "cannot_tell": False, "reasons": [], "note": "",
                                    "submitted_utc": f"2026-11-13T00:{t // 60:02d}:{t % 60:02d}Z"})
            (resp_dir / f"{pack['pack_id']}.json").write_text(json.dumps({
                "instrument_id": common.INSTRUMENT_ID, "pack_id": pack["pack_id"],
                "rater_slot": pack["rater_slot"], "rater_id": "x", "answers": answers,
                "exported_utc": "2026-11-13T01:00:00Z", "complete": True}))
        return resp_dir

    def score(self, resp_dir: Path) -> dict:
        out = self.study / "scored"
        run("score_fact_audit.py", "--study", str(self.study), "--responses", str(resp_dir),
            "--out", str(out), "--qa-metadata", str(self.meta_path), "--bootstrap", "50")
        return json.loads((out / "summary.json").read_text())

    def test_manifest_and_sampling(self):
        self.pipeline()
        manifest = list(common.iter_jsonl(self.study / "manifest.jsonl"))
        self.assertEqual(len(manifest), 6 * 2 * 3)  # 6 scenes x 2 human tasks x 3 runs
        self.assertNotIn("size", {u["task"] for u in manifest})
        sample = list(common.iter_jsonl(self.study / "sample.jsonl"))
        self.assertEqual(len({u["scene"] for u in sample}), 3)
        for unit in sample:
            self.assertAlmostEqual(unit["weight"], 1 / unit["pi"])
            self.assertEqual(len(unit["raters"]), 2)
        pilot = list(common.iter_jsonl(self.study / "pilot_sample.jsonl"))
        self.assertFalse({u["scene"] for u in pilot} & {u["scene"] for u in sample})

    def test_surveys_are_blind_and_use_judge_frames(self):
        self.pipeline()
        prov = json.loads((self.study / "packs" / "frames_provenance.json").read_text())
        self.assertTrue(all(v["n_frames_shown"] == 16 for v in prov.values()))
        for html in (self.study / "packs").glob("survey-*.html"):
            text = html.read_text()
            for secret in ["strong", "weak", "dv_pass", "ground_truth", "rendered_answer", "arkitscenes_0"]:
                self.assertNotIn(secret, text, f"{secret} leaked into {html.name}")

    def test_scoring_matches_dv_when_humans_agree(self):
        self.pipeline()
        summary = self.score(self.fake_responses())
        self.assertEqual(summary["n_pending"], 0)
        self.assertEqual(summary["order_violations"], 0)
        point = summary["point_estimates"]
        self.assertAlmostEqual(point["pooled|dv_human_agreement"], 1.0)
        self.assertAlmostEqual(point["pooled|fail|error"], 1.0)
        self.assertAlmostEqual(point["pooled|pass|retained"], 1.0)
        self.assertAlmostEqual(summary["agreement"]["raw_agreement_final_label"], 1.0)

    def test_disagreement_goes_to_adjudication(self):
        self.pipeline()
        summary = self.score(self.fake_responses(flip_one=True))
        self.assertEqual(summary["n_pending"], 1)
        with (self.study / "scored" / "adjudicate_labels.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertNotIn("run", rows[0])

    def test_source_before_recon_is_flagged(self):
        self.pipeline()
        summary = self.score(self.fake_responses(source_first_slot="r01"))
        self.assertGreater(summary["order_violations"], 0)


class JudgeFrameParityTest(unittest.TestCase):
    def test_constants_match_judge(self):
        import types

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        # The frame sampler never touches the API client; stub it if absent.
        sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))
        import dual_vqa_metric as dvm
        self.assertEqual(dvm.DEFAULT_N_FRAMES, common.JUDGE_N_FRAMES)
        self.assertEqual(dvm.MAX_SIDE, common.JUDGE_MAX_SIDE)
        self.assertEqual(dvm.JPEG_QUALITY, common.JUDGE_JPEG_QUALITY)
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "v.mp4"
            write_video(video, frames=37)
            ours = [common.b64(f) for f in common.judge_frames_jpeg(video)]
            self.assertEqual(ours, dvm.sample_frames_b64(video, common.JUDGE_N_FRAMES))


if __name__ == "__main__":
    unittest.main()
