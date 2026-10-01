#!/bin/bash
# Piloto: 1 pacote em cada sentido (zita-resampler x86_64->ppc64le, llamacpp ppc64le->x86_64).
# Pré-requisitos: .env preenchido e `python dataset/setup_obs.py` já executado uma vez.
set -euo pipefail
cd "$(dirname "$0")"
PY=/root/miniforge3/envs/build_bench/bin/python
for d in x86_64_to_ppc64le ppc64le_to_x86_64; do
  echo "===== $d ($(grep LLM_MODEL .env | cut -d= -f2))"
  BENCH_CONFIG=config/$d.yaml $PY client.py
  cat result_text_res/$d/*.json
done
