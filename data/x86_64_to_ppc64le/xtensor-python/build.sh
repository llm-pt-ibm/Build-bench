#!/bin/bash
# Build recipe for xtensor-python, as it builds on x86_64: CMake with the unit
# tests, as the distribution builds them. It runs from the case directory in
# the environment envs/py-power9, with $BENCH_CACHE_DIR (this run's build
# state), $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd xtensor-python
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON -DPYTHON_EXECUTABLE="$(command -v "${PYTHON:-python3}")"
cmake --build build --parallel "$BENCH_JOBS"
