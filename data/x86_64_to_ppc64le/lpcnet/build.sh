#!/bin/bash
# Build recipe for lpcnet, as it builds on x86_64: CMake, with the neural
# network model the build would download next to it (../model). It runs from
# the case directory in the environment envs/c-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd LPCNet
mkdir -p build
tar -czf build/lpcnet_191005_v1.0.tgz -C ../model .
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_SHARED_LINKER_FLAGS=-lm
cmake --build build --parallel "$BENCH_JOBS"
