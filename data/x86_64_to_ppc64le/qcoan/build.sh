#!/bin/bash
# Build recipe for qcoan, as it builds on x86_64: the console build of the
# project (makefile.console): the program and its test programs. It runs from
# the case directory in the environment envs/c-power9, with $BENCH_CACHE_DIR
# (this run's build state), $BENCH_SHARED_CACHE_DIR (caches kept across runs)
# and $BENCH_JOBS.
set -euo pipefail
cd coan
make -f makefile.console main test_aux test_charset test_symtab
