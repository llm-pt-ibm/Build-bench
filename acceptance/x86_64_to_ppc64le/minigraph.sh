#!/bin/bash
# Acceptance test of minigraph: add the chimpanzee and orangutan mitochondrial
# genomes to the project's test graph (-cxggs); the graph must have the
# segments and links of an x86_64 build (8 segments of 17,572 bases, 11 links).
set -uo pipefail
src=$BENCH_SRC_DIR/minigraph
[ -x "$src/minigraph" ] || { echo "error: the build left no minigraph"; exit 1; }
work=$BENCH_CACHE_DIR/acceptance
rm -rf "$work" && mkdir -p "$work" && cd "$work"
"$src/minigraph" -cxggs -t1 "$src/test/MT.gfa" "$src/test/MT-chimp.fa" "$src/test/MT-orangA.fa" > out.gfa 2> minigraph.log \
  || { cat minigraph.log; echo "error: minigraph failed"; exit 1; }
got=$(awk '/^S/ { n++; t += length($3) } /^L/ { l++ } END { print n + 0, t + 0, l + 0 }' out.gfa)
echo "segments, bases, links: $got"
[ "$got" = "8 17572 11" ] || { echo "FAIL: expected 8 segments of 17572 bases and 11 links, as an x86_64 build gives"; exit 1; }
echo "PASS minigraph"
