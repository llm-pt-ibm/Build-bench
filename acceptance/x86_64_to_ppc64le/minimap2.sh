#!/bin/bash
# Acceptance test of minimap2: align the orangutan mitochondrial genome to the
# human one (the project's test data) with base-level alignment (-c); the
# alignment must match an x86_64 build's (coordinates within 30 bases, matches
# within 1%).
set -uo pipefail
src=$BENCH_SRC_DIR/minimap2
[ -x "$src/minimap2" ] || { echo "error: the build left no minimap2"; exit 1; }
paf_check() {   # paf_check <expected line> <line>
  awk -F'\t' -v e="$1" 'BEGIN { split(e, x, "\t") } {
    ok = ($1 == x[1] && $2 == x[2] && $5 == x[5] && $6 == x[6] && $7 == x[7])
    for (i = 3; i <= 9; i++) if (i != 5 && i != 6 && i != 7 && (($i - x[i]) > 30 || (x[i] - $i) > 30)) ok = 0
    for (i = 10; i <= 11; i++) if ($i < x[i] * 0.99 || $i > x[i] * 1.01) ok = 0
    exit !ok }' <<< "$2"
}
got=$("$src/minimap2" -c -t1 "$src/test/MT-human.fa" "$src/test/MT-orang.fa" 2> "$BENCH_CACHE_DIR/minimap2.log" | cut -f1-12) \
  || { cat "$BENCH_CACHE_DIR/minimap2.log"; echo "error: minimap2 failed"; exit 1; }
expected=$(printf 'MT_orang\t16499\t0\t16025\t+\tMT_human\t16569\t576\t16569\t13773\t16095\t60')
echo "$got"
[ $(wc -l <<< "$got") -eq 1 ] && paf_check "$expected" "$got" \
  || { echo "FAIL: the alignment differs from an x86_64 build's:"; echo "$expected"; exit 1; }
echo "PASS minimap2"
