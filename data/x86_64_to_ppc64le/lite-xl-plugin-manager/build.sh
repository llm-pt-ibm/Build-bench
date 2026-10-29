#!/bin/bash
# Build recipe for lite-xl-plugin-manager, as it builds on x86_64: Meson
# against the system's libraries, with lpm.lua built into the executable
# (-Dstatic=true), as distributions package it. It runs from the case directory
# in the environment envs/lpm-power9, with $BENCH_JOBS parallel jobs.
set -euo pipefail
cd lite-xl-plugin-manager
meson setup build -Dstatic=true
meson compile -C build -j "$BENCH_JOBS"
