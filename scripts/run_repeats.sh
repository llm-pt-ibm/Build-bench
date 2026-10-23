#!/bin/bash
# Run the benchmark N times and archive every run in its own directory.
# Usage: scripts/run_repeats.sh <label> <n> [config]
#   label   name prefix of the run directories (runs are <label>_1 ... <label>_n)
#   n       number of runs
#   config  benchmark config (default: bench.yaml); each run keeps a copy with its logs
# The environment (OPENROUTER_PROVIDER, LLM_TEMPERATURE, LLM_MODEL, ...) is passed
# to client.py unchanged. PY chooses the Python interpreter (default: python3).
set -euo pipefail
cd "$(dirname "$0")/.."

label=${1:?label}
n=${2:?number of runs}
config=${3:-bench.yaml}
PY=${PY:-python3}

read -r data_dir result_dir log_dir < <("$PY" - "$config" <<'EOF'
import sys
from tools.auto_repair import bench_config
paths = bench_config.run_paths(bench_config.load(sys.argv[1]))
print(paths["base_dir"], paths["result_dir"], paths["log_dir"])
EOF
)

for i in $(seq 1 "$n"); do
  run="${label}_${i}"
  echo "=== $run ($(date '+%F %T'))"
  mkdir -p logs "$result_dir" "$log_dir"
  cp "$config" "$log_dir/config.yaml"
  BENCH_CONFIG=$config "$PY" client.py > "logs/pilot_${run}.log" 2>&1 || echo "client.py exited with an error, see logs/pilot_${run}.log"
  mkdir -p "$result_dir/$run" "$log_dir/$run"
  find "$result_dir" -maxdepth 1 -type f -exec mv {} "$result_dir/$run/" \;
  find "$log_dir" -maxdepth 1 -type f -exec mv {} "$log_dir/$run/" \;
  for pkg in $(ls "$data_dir"); do
    [ -f "data/case_study/${pkg}_diff.log" ] && mv "data/case_study/${pkg}_diff.log" "$log_dir/$run/"
  done
  mv "logs/pilot_${run}.log" "$log_dir/$run/"
done

"$PY" scripts/summarize_runs.py "$result_dir" "$label"
