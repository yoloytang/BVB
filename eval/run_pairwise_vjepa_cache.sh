#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv-vjepa/bin/python"
SYSTEMS="${ROOT}/eval/pairwise_vjepa_systems.json"
RESULTS="${ROOT}/sandbox/results"
CACHE="${ROOT}/pairwise/features"
OUTPUT="${ROOT}/pairwise/pairwise_vjepa_similarity.json"
LOG_DIR="${ROOT}/pairwise/log"
HF_REPO_ID="${HF_REPO_ID:-yoloytang/BVB-results}"
GPUS="${GPUS:-8}"

mkdir -p "$CACHE" "$LOG_DIR"

pids=()
for i in $(seq 1 "$GPUS"); do
  gpu=$((i - 1))
  echo "[launch] GPU ${gpu} model shard ${i}/${GPUS}"
  (
    cd "${ROOT}/eval"
    CUDA_VISIBLE_DEVICES="$gpu" "$PY" -u cache_vjepa_features.py \
      --systems "$SYSTEMS" \
      --results-dir "$RESULTS" \
      --qa-metadata "${ROOT}/eval/test.jsonl" \
      --output-dir "$CACHE" \
      --shard "${i}/${GPUS}" \
      --resume
  ) >"${LOG_DIR}/cache-${i}-of-${GPUS}.log" 2>&1 &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
if [[ "$failed" -ne 0 ]]; then
  echo "One or more feature-cache shards failed." >&2
  exit 1
fi

echo "[matrix] computing pairwise similarities"
CUDA_VISIBLE_DEVICES=0 "$PY" -u "${ROOT}/eval/pairwise_vjepa_from_cache.py" \
  --cache-dir "$CACHE" \
  --output "$OUTPUT"
cp "$OUTPUT" "${CACHE}/pairwise_vjepa_similarity.json"

echo "[hf] uploading exact feature cache"
"$PY" -u - <<PY
from huggingface_hub import HfApi

api = HfApi()
api.upload_folder(
    folder_path="${CACHE}",
    path_in_repo="_pairwise_vjepa_features/v1",
    repo_id="${HF_REPO_ID}",
    repo_type="dataset",
    commit_message="Add exact pairwise V-JEPA feature cache",
)
files = api.list_repo_files("${HF_REPO_ID}", repo_type="dataset")
prefix = "_pairwise_vjepa_features/v1/"
cached = [path for path in files if path.startswith(prefix)]
print(f"[done] HF feature files={len(cached)}")
PY

