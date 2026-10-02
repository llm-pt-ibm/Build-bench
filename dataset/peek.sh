#!/bin/bash
pkg=$1; prj=$2; arch=$3; okprj=$4
A=https://api.opensuse.org/public
src_bad=$(curl -s "$A/source/$prj/$pkg" | grep -o "srcmd5=\"[^\"]*\"" | head -1)
src_ok=$(curl -s "$A/source/$okprj/$pkg" | grep -o "srcmd5=\"[^\"]*\"" | head -1)
size=$(curl -s "$A/source/$okprj/$pkg" | grep -o "size=\"[0-9]*\"" | grep -o "[0-9]*" | sort -n | tail -1)
echo "=== $pkg  (largest file: $((size/1024)) KiB)  srcmd5 failing:$src_bad ok:$src_ok"
curl -s "$A/build/$prj/standard/$arch/$pkg/_log" > logs/$pkg.$arch.log
grep -inE "error|undefined reference|unrecognized|not supported|FAILED" logs/$pkg.$arch.log | grep -viE "^\S+ *\[ *[0-9]+s\] *(\+|checking)|-Werror|error\.[ch]|errors?\.(o|c|go)" | head -6 | cut -c1-220
echo "--- end of log:"; tail -4 logs/$pkg.$arch.log | cut -c1-200
