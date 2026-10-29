#!/bin/bash
# Build recipe for libzita-resampler, as it builds on x86_64: the library's
# Makefile in source/. It runs from the case directory in the environment
# envs/tools-power9, with $BENCH_JOBS parallel jobs.
set -euo pipefail
cd zita-resampler/source
make -j "$BENCH_JOBS"
