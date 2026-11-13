#!/bin/bash
# Build recipe for dealii, as it builds on x86_64: CMake as the distribution
# configures it (C++20, threads, no MPI, no examples or documentation), with
# the libraries deal.II bundles. It runs from the case directory in the
# environment envs/dealii-power9, with $BENCH_CACHE_DIR (this run's build
# state), $BENCH_SHARED_CACHE_DIR (caches kept across runs) and $BENCH_JOBS.
set -euo pipefail
cd dealii
jobs=$(( BENCH_JOBS < 48 ? BENCH_JOBS : 48 ))   # each of its compile units takes a few GB
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=20 \
  -DDEAL_II_WITH_THREADS=ON -DDEAL_II_WITH_MPI=OFF \
  -DDEAL_II_COMPILE_EXAMPLES=OFF -DDEAL_II_COMPONENT_DOCUMENTATION=OFF
cmake --build build --parallel "$jobs"
