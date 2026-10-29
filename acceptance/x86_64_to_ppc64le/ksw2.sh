#!/bin/bash
# Acceptance test of ksw2: align the orangutan mitochondrial genome to the
# human one (the project's test data) with each SIMD kernel (gg2_sse,
# extz2_sse, extd2_sse) and its scalar counterpart (gg, extz, extd); each pair
# must give the same scores and CIGARs, and those of an x86_64 build.
set -uo pipefail
src=$BENCH_SRC_DIR/ksw2
[ -x "$src/ksw2-test" ] || { echo "error: the build left no ksw2-test"; exit 1; }
failed=0
for pair in "gg gg2_sse b3146373030ddba96733d01d2b7b38ee" \
            "extz extz2_sse 6e820e4b46875605a263b44134b3c9e7" \
            "extd extd2_sse a141aea08e8de4c51d94d7136080fa2d"; do
  read -r scalar simd expected <<< "$pair"
  a=$("$src/ksw2-test" -t "$scalar" "$src/test/MT-human.fa" "$src/test/MT-orang.fa" 2>&1)
  b=$("$src/ksw2-test" -t "$simd" "$src/test/MT-human.fa" "$src/test/MT-orang.fa" 2>&1)
  sum=$(md5sum <<< "$b" | cut -d' ' -f1)
  echo "$simd: $(cut -f1-6 <<< "$b")"
  if [ "$a" != "$b" ]; then echo "FAIL $simd: differs from the scalar $scalar ($(cut -f1-6 <<< "$a"))"; failed=1
  elif [ "$sum" != "$expected" ]; then echo "FAIL $simd: differs from an x86_64 build's (md5 $sum, expected $expected)"; failed=1
  else echo "PASS $simd"; fi
done
exit $failed
