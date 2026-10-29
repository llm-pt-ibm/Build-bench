#!/bin/bash
# Acceptance test of miniprot: align the mouse DPP3 protein to the human DPP3
# gene (the project's test data); the alignment must match an x86_64 build's
# (coordinates within 30 bases, matches within 1%).
set -uo pipefail
src=$BENCH_SRC_DIR/miniprot
[ -x "$src/miniprot" ] || { echo "error: the build left no miniprot"; exit 1; }
paf_check() {   # paf_check <expected line> <line>
  awk -F'\t' -v e="$1" 'BEGIN { split(e, x, "\t") } {
    ok = ($1 == x[1] && $2 == x[2] && $5 == x[5] && $6 == x[6] && $7 == x[7])
    for (i = 3; i <= 9; i++) if (i != 5 && i != 6 && i != 7 && (($i - x[i]) > 30 || (x[i] - $i) > 30)) ok = 0
    for (i = 10; i <= 11; i++) if ($i < x[i] * 0.99 || $i > x[i] * 1.01) ok = 0
    exit !ok }' <<< "$2"
}
got=$("$src/miniprot" -t1 "$src/test/DPP3-hs.gen.fa.gz" "$src/test/DPP3-mm.pep.fa.gz" 2> "$BENCH_CACHE_DIR/miniprot.log" | grep -v '^##' | cut -f1-12) \
  || { cat "$BENCH_CACHE_DIR/miniprot.log"; echo "error: miniprot failed"; exit 1; }
expected=$(printf 'ENSMUSP00000025851.4\t738\t0\t738\t+\tchr11:66478458-66505490\t27033\t0\t27030\t2055\t2214\t0')
echo "$got"
[ $(wc -l <<< "$got") -eq 1 ] && paf_check "$expected" "$got" \
  || { echo "FAIL: the alignment differs from an x86_64 build's:"; echo "$expected"; exit 1; }
echo "PASS miniprot"
