#!/bin/bash
# Acceptance test of asl: assemble Z80 and 68000 code, with 64-bit integer
# arithmetic in an expression, and check the bytes p2bin writes against those
# of an x86_64 build.
set -uo pipefail
src=$BENCH_SRC_DIR/asl
for b in asl p2bin; do [ -x "$src/$b" ] || { echo "error: the build left no $b"; exit 1; }; done
export AS_MSGPATH=$src
work=$BENCH_CACHE_DIR/acceptance
rm -rf "$work" && mkdir -p "$work" && cd "$work"
failed=0
check() {   # check <name> <expected bytes>: assemble <name>.asm, compare <name>.bin
  "$src/asl" -q "$1.asm" && "$src/p2bin" -q "$1" -r '$-$' || { echo "FAIL $1: assembling failed"; failed=1; return; }
  got=$(od -An -tx1 "$1.bin" | tr -s ' \n' ' ' | sed 's/^ //; s/ $//')
  if [ "$got" = "$2" ]; then echo "PASS $1: $got"; else echo "FAIL $1: got '$got', expected '$2'"; failed=1; fi
}
printf '\tcpu\tz80\n\torg\t0\n\tld\ta,42h\n\tld\tb,a\n\thalt\n' > z80.asm
check z80 "3e 42 47 76"
printf '\tcpu\t68000\n\torg\t0\n\tmove.l\t#$12345678,d0\n\trts\n\tdc.b\t(123456789012/1000000)&$FF,0\n\tdc.l\t-2\n' > m68k.asm
check m68k "20 3c 12 34 56 78 4e 75 40 00 ff ff ff fe"
exit $failed
