# Latent Similarity: render and GPU workflow

LS is one of the two current BVB axes, alongside Dual VQA. It averages layout
and motion similarity from a frozen V-JEPA 2.1 ViT-G encoder. See the
[evaluation guide](README.md) for the score definition, coverage requirements,
and two-axis Overall.

Run all commands below from the repository root. Use a separate evaluation
environment for [the GPU dependencies](requirements-vjepa.txt); the Stage-1
agent environment does not need the encoder.

## 1. Render once on a Blender host

```bash
python eval/batch_render_camera.py \
  --run sandbox/results/run_001 \
  --num-frames 64 \
  --resume
```

Requires host Blender and FFmpeg. Set `BLENDER_BIN` if needed. The renderer
samples the full animated camera timeline and writes
`sandbox/results/run_001/camera_renders/<scene>.mp4`. Increase `--workers`
according to available host resources. The default resolution is 512 pixels.
No GPU encoder or judge API runs at this stage.

The GPU host needs those camera renders, the tracked evaluation metadata,
and the original videos under `VSI-Bench/<dataset>/<scene>.mp4`.
If using the existing Hugging Face results store, authenticated maintainers
can transfer the run with:

```bash
# Blender host: preview the upload, then upload camera renders.
python scripts/sync_eval_results.py --run run_001 --camera-renders-only --dry-run
python scripts/sync_eval_results.py --run run_001 --camera-renders-only

# GPU host: restore the run; source videos are obtained separately.
python scripts/download_results.py --run run_001
```

These transfer commands require `huggingface_hub` and access to
`yoloytang/BVB-results`. Local file transfer works as well. They are not needed
when rendering and scoring on the same machine.

## 2. Encode on one GPU

```bash
python -m pip install -r eval/requirements-vjepa.txt
python eval/vjepa_sim_metric.py \
  --run sandbox/results/run_001 \
  --vsi-bench VSI-Bench \
  --dry-run --limit 3

python eval/vjepa_sim_metric.py \
  --run sandbox/results/run_001 \
  --vsi-bench VSI-Bench \
  --model apiantonio/vjepa2.1-vit-gigantic-384 \
  --num-frames 64 \
  --device cuda --dtype bfloat16 \
  --resume
```

The dry run checks input paths without loading the encoder. Cached camera
MP4s avoid Blender work on the GPU host. Without a cache, the scorer can render
the saved `.blend` itself when Blender is available.

Keep the encoder and frame count fixed for paper-comparable results.
Changing either defines a different evaluation setting; do not mix its scores
with the released results. A small `--limit` run checks GPU memory needs before
starting a complete run, but its summary represents only that subset.

## 3. Optional: distribute scene shards

Launch one process per GPU. This example uses eight GPUs and eight disjoint
scene shards; adjust both together for the available machine.

```bash
BVB_RUN=sandbox/results/run_001
for i in $(seq 1 8); do
  CUDA_VISIBLE_DEVICES=$((i-1)) python eval/vjepa_sim_metric.py \
    --run "$BVB_RUN" \
    --vsi-bench VSI-Bench \
    --model apiantonio/vjepa2.1-vit-gigantic-384 \
    --device cuda --dtype bfloat16 --num-frames 64 \
    --shard "$i/8" --resume &
done
wait

python eval/merge_vision_sim_shards.py \
  --run "$BVB_RUN" --shard-count 8
```

Each process writes `vision_sim.shard-i-of-8.jsonl` and its own summary.
The merge helper checks shard completeness and writes `vision_sim.jsonl` plus
`vision_sim_summary.json`; it retains the shard files by default. Inspect
`num_scenes`, `num_ok`, and `num_error` in the merged summary before reporting
results. A full benchmark run covers all 288 scenes, including failure rows.

## Outputs and caching

- `vision_sim.jsonl` stores per-scene layout, motion, LS, status, and errors.
- `vision_sim_summary.json` averages all selected scenes with failures filled
  as zero. Its `scored_only` block is a diagnostic, not the benchmark score.
- Scores are stored on a 0–1 scale; tables display them multiplied by 100.
- Render caching is enabled by default under `<run>/camera_renders/`.
  `--no-keep-renders` uses temporary frames and disables reuse of that cache;
  it does not remove previously cached camera MP4s.
- Encoder features are not saved. Evaluation writes separate metric files and
  does not edit Stage-1 blends.

Resume only within the same encoder, sampling, and rendering protocol. See
[README.md](README.md#4-check-coverage-and-compute-overall) before combining LS
with Dual VQA.
