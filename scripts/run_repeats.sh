#!/bin/bash
# Run the benchmark N times and archive every run in its own directory.
# Usage: scripts/run_repeats.sh <label> <n> [config]
#   label   name prefix of the run directories (runs are <label>_1 ... <label>_n)
#   n       number of runs
#   config  benchmark config (default: config/x86_64_to_ppc64le.yaml)
# The environment (OPENROUTER_PROVIDER, LLM_TEMPERATURE, LLM_MODEL, ...) is passed
# to client.py unchanged. Set PY to choose the Python interpreter.
set -euo pipefail
cd "$(dirname "$0")/.."

label=${1:?label}
n=${2:?number of runs}
config=${3:-config/x86_64_to_ppc64le.yaml}
PY=${PY:-/root/miniforge3/envs/build_bench/bin/python}

read -r data_dir result_dir log_dir < <("$PY" - "$config" <<'EOF'
import sys, yaml
paths = yaml.safe_load(open(sys.argv[1]))["paths"]
print(paths["base_dir"], paths["result_dir"], paths["log_dir"])
EOF
)

for i in $(seq 1 "$n"); do
  run="${label}_${i}"
  echo "=== $run ($(date '+%F %T'))"
  BENCH_CONFIG=$config "$PY" client.py > "pilot_${run}.log" 2>&1 || echo "client.py exited with an error, see pilot_${run}.log"
  mkdir -p "$result_dir/$run" "$log_dir/$run"
  find "$result_dir" -maxdepth 1 -type f -exec mv {} "$result_dir/$run/" \;
  find "$log_dir" -maxdepth 1 -type f -exec mv {} "$log_dir/$run/" \;
  for pkg in $(ls "$data_dir"); do
    [ -f "data/case_study/${pkg}_diff.log" ] && mv "data/case_study/${pkg}_diff.log" "$log_dir/$run/"
  done
  mv "pilot_${run}.log" "$log_dir/$run/"
done

"$PY" scripts/summarize_runs.py "$result_dir" "$label"
