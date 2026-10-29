#!/bin/bash
# Build recipe for miniprot, as it builds on x86_64: the project's Makefile. It
# runs from the case directory in the environment envs/tools-power9, with
# $BENCH_JOBS parallel jobs.
set -euo pipefail
cd miniprot
make -j "$BENCH_JOBS"
