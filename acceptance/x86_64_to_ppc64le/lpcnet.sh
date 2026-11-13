#!/bin/bash
# Acceptance test of lpcnet: the project's tests (CTest), but for
# lpcnet_enc_dec, which needs sox. It runs without network on what build.sh
# left in $BENCH_SRC_DIR ($BENCH_CACHE_DIR: scratch space) and passes with exit
# status 0.
set -euo pipefail
src=$BENCH_SRC_DIR/LPCNet
# lpcnet_enc_dec converts a wav file with sox, which the environment lacks
ctest --test-dir "$src/build" --output-on-failure --no-tests=error -j "$BENCH_JOBS" -E lpcnet_enc_dec
