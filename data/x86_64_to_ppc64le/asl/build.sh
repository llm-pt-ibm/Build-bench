#!/bin/bash
# Build recipe for asl, as it builds on x86_64: the Makefile.def of x86_64
# Linux from Makefile.def-samples, as the INSTALL file says, then the binaries
# (the documentation needs TeX). It runs from the case directory in the
# environment envs/tools-power9, with $BENCH_JOBS parallel jobs.
set -euo pipefail
cd asl
cp Makefile.def-samples/Makefile.def-x86_64-unknown-linux Makefile.def
make -j "$BENCH_JOBS" binaries
