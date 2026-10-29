#!/bin/bash
# Acceptance test of fermi-lite: assemble the project's simulated reads of a
# mitochondrial genome (fml-asm); an x86_64 build assembles one contig of
# 16,507 bases.
set -uo pipefail
src=$BENCH_SRC_DIR/fermi-lite
[ -x "$src/fml-asm" ] || { echo "error: the build left no fml-asm"; exit 1; }
work=$BENCH_CACHE_DIR/acceptance
rm -rf "$work" && mkdir -p "$work" && cd "$work"
"$src/fml-asm" -t1 "$src/test/MT-simu.fq.gz" > out.fq 2> fml.log || { cat fml.log; echo "error: fml-asm failed"; exit 1; }
got=$(awk 'NR % 4 == 2 { n++; if (length($0) > m) m = length($0) } END { print n + 0, m + 0 }' out.fq)
echo "contigs, longest: $got"
read -r n longest <<< "$got"
[ "$n" -ge 1 ] && [ "$longest" -ge 16400 ] && [ "$longest" -le 16600 ] \
  || { echo "FAIL: expected a contig of about 16507 bases, as an x86_64 build gives"; exit 1; }
echo "PASS fermi-lite"
