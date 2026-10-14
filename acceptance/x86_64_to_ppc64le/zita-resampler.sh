#!/bin/bash
# Acceptance test of zita-resampler (RPM): install the built packages in the
# build root and run a program that resamples a 1 kHz sine from 44.1 to 48 kHz
# with Resampler and VResampler; the output must be the same sine at the new
# rate (frequency and amplitude), which also checks the code path that
# replaces the x86 SIMD one.
set -euo pipefail
R=$BENCH_BUILD_ROOT
rpms=$(ls "$R"/home/abuild/rpmbuild/RPMS/*/*.rpm | grep -v -e debuginfo -e debugsource)
echo "installing: $(for p in $rpms; do basename "$p"; done | tr '\n' ' ')"
work=$R/tmp/acceptance
rm -rf "$work" && mkdir -p "$work"
cp $rpms "$work/"
mounted=""
for d in proc dev; do
  if ! mountpoint -q "$R/$d"; then
    mkdir -p "$R/$d"
    if [ $d = proc ]; then mount -t proc proc "$R/proc"; else mount --bind /dev "$R/dev"; fi
    mounted="$mounted $R/$d"
  fi
done
trap 'for m in $mounted; do umount -l "$m"; done' EXIT
chroot "$R" rpm -U --force --nodeps --quiet /tmp/acceptance/*.rpm

cat > "$work/test.cc" <<'CC'
#include <cmath>
#include <cstdio>
#include <vector>
#include <zita-resampler/resampler.h>
#include <zita-resampler/vresampler.h>

template <class R> static int check(const char *name, R &r) {
    const double fin = 44100, fout = 48000, f = 1000;
    const int nin = 44100;
    std::vector<float> in(nin), out(48000 + 1000);
    for (int i = 0; i < nin; i++) in[i] = 0.5f * std::sin(2 * M_PI * f * i / fin);
    r.inp_count = nin; r.inp_data = in.data();
    r.out_count = out.size(); r.out_data = out.data();
    r.process();
    const int n = out.size() - r.out_count, skip = 200;   // skip the filter delay
    int crossings = 0; double sum2 = 0;
    for (int i = skip + 1; i < n - skip; i++) {
        if ((out[i - 1] < 0) != (out[i] < 0)) crossings++;
        sum2 += out[i] * out[i];
    }
    const double seconds = (n - 2 * skip) / fout, freq = crossings / 2.0 / seconds;
    const double amplitude = std::sqrt(2 * sum2 / (n - 2 * skip - 1));
    std::printf("%s: %d output samples, %.1f Hz, amplitude %.4f\n", name, n, freq, amplitude);
    if (n < 47000 || n > 48100) { std::printf("  wrong number of output samples\n"); return 1; }
    if (std::fabs(freq - f) > 5) { std::printf("  wrong frequency (expected %.0f Hz)\n", f); return 1; }
    if (std::fabs(amplitude - 0.5) > 0.01) { std::printf("  wrong amplitude (expected 0.5)\n"); return 1; }
    return 0;
}

int main() {
    Resampler r;
    VResampler v;
    if (r.setup(44100, 48000, 1, 32) || v.setup(48000.0 / 44100.0, 1, 32)) { std::printf("setup failed\n"); return 1; }
    return check("Resampler", r) | check("VResampler", v);
}
CC
chroot "$R" g++ -O2 -o /tmp/acceptance/test /tmp/acceptance/test.cc -lzita-resampler
chroot "$R" /tmp/acceptance/test
echo "acceptance: passed"
