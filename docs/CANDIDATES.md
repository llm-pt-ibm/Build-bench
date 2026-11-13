# Candidate cases (x86_64 to ppc64le)

Software that builds on x86_64 and fails on ppc64le for a reason of the
architecture, as candidates for build-recipe cases (`make new-case` from the
project's own sources; no OBS needed). Grouped by how hard the repair is likely
to be.

- **(C) confirmed**: a ppc64le build log shows the failure and its cause.
- **(P) probable**: indirect evidence only. Run `make new-case` and
  `make baseline` before adding it: a newer upstream release may build already
  (bwa 0.7.19 has a scalar fallback for its SSE code, and passed).
- **case**: already a case in `data/x86_64_to_ppc64le/`.

Sources, as of 2026-11-03:
- openSUSE Factory: the packages that succeed on x86_64 and fail on
  ppc64le (`dataset/find_candidates.py`), 190 of them, classified by the end
  of their ppc64le build log (`api.opensuse.org/public/build/openSUSE:Factory:PowerPC/standard/ppc64le/<package>/_log`);
- Debian sid: the 54 source packages that build-depend on `libsimde-dev`
  (x86 intrinsics that need SIMDe off x86), and the 283 whose Architecture
  field names amd64 or arm64 but not ppc64el
  (`deb.debian.org/debian/dists/sid/main/source/Sources.xz`).

## The evaluation sample (2026-11-13)

`dataset/sample_x86_64_to_ppc64le.json` holds the 33 cases of the evaluation
(suite `sample` of `bench.yaml`), all from OBS (Factory and its devel
projects, 293 candidates on 2026-11-12), chosen for the variety of the cause
among the failures of `%build` or `%check` whose last build takes at most 20
min (deal.II, 40). Each one's baseline (`log_failed.txt`) reproduces on
ppc64le the failure of its OBS log; for each one the json gives the group, the
evidence, the OBS revision, the sources (upstream at the version that failed,
vendored dependencies from OBS) and the environment. Report results per group:
the sample is not random. The 10 cases of the tables below are apart from it.

| Group | Cases |
|---|---|
| system and CPU behavior tests | 6 |
| x86 compiler flags | 5 |
| architecture detection and Linux headers | 5 |
| Go build tags and generated code | 5 |
| x86 SIMD (and PowerPC vector code) | 4 |
| types and ABI | 3 |
| Rust crates without ppc64le | 3 |
| assembly and low-level code | 2 |

Of the 51 candidates made into cases, 33 reproduced: 27 of the 30 whose build
fails on OBS, 6 of the 21 whose tests fail. A test failure on OBS depends on
the distribution's flags and library versions more than a recipe of the
upstream sources reproduces (`dropped` in the json says why for each);
`not_built` lists the 11 candidates left, nearly all failing tests. iprange's
failing test may come from the container (no user name for its uid): check it
on x86_64 before counting it.

Most of the failures left out at the start are of the packaging only: 99 Go
packages fail in `%install`, where their binary crashes in the Go 1.27 runtime
on the OBS ppc64le workers (`fatal error: fault`, SIGSEGV), not in their own
code; rustc dies the same way for five Rust packages.

## Simple: a few lines (a compiler flag, a macro, a list of architectures)

| Package | Status | Why it fails on ppc64le |
|---|---|---|
| cpufetch | case | an undeclared variable in the PowerPC code (`src/ppc/udev.c`) |
| asl | case | `-march=athlon64` in the x86_64 `Makefile.def`, then 64-bit types defined twice for PowerPC 64 |
| libzita-resampler | case | `-march=native` and `-DENABLE_SSE2` |
| lite-xl-plugin-manager | case | no `LPM_ARCH_PROCESSOR` for ppc64le |
| ksw2 | case | `-march=native`, and SSE kernels that are empty without SSE2 |
| fermi-lite | case | SSE2 intrinsics without a guard |
| ssw | case | SSE2 intrinsics without a guard |
| minimap2 | case | `-msse2`, `-msse4.1`, `-mno-sse4.1` |
| minigraph | case | `-msse4` (the sources use no intrinsics) |
| miniprot | case | `__m128i` with neither SSE nor NEON |
| rtlsdr-airband | C | CMake's `PLATFORM=native` gives `-march=native` |
| trigger-rally | C | `-march=native` (a game: SDL, OpenAL) |
| ttynvt | C | `struct termios2` does not exist on PowerPC (needs fuse) |
| syncterm | C | `#error "Need to describe target architecture"` (SDL2, X11) |
| steampipe | C | Go: `platform.Paths` defined only for amd64 and arm64 (build tags) |
| awww | C | Rust: an old `cpufeatures` crate refuses ppc64 |
| megahit | P | `-mpopcnt` and SSE (Debian: amd64, arm64 only) |
| metabat | P | Debian: not built on ppc64el |
| mecat2 | P | Debian: not built on ppc64el |
| soapdenovo2 | P | Debian: not built on ppc64el |
| pftools | P | Debian: not built on ppc64el |

## Medium: porting a piece of architecture-specific code

Build failures:

| Package | Status | Why it fails on ppc64le |
|---|---|---|
| clanlib | C | x86 inline assembly (`cpuid`, `pushl`) in its core |
| python-mitmproxy-wireguard | C | Rust: `ring` 0.16 has no ppc64le (0.17 has), so `Cargo.lock` needs updating |
| rustdesk-server | C | Rust: `ring` 0.16, as above |
| spotifyd | C | Rust: `aws-lc-sys` does not compile for ppc64le |
| inspektor-gadget | C | Go/eBPF: the generated eBPF code exists for amd64 and arm64 only |
| ptcpdump | C | Go/eBPF: as above |
| python-nanobind | C | Eigen's AltiVec code path does not compile |
| dealii | C | the VSX vectorization path does not compile |
| noise-suppression-for-voice | C | JUCE does not know ppc64le |
| giada | C | JUCE, as above |
| boxfort (and criterion) | P | trampolines in assembly for x86 and ARM only |
| massivethreads | P | context switching in assembly for x86 and ARM only |
| reprozip | P | system call tables per architecture |
| proot | P | Debian: not built on ppc64el |
| libx86 | P | Debian: not built on ppc64el |
| Vc | P | SIMD library for x86 and ARM |
| sptag | P | AVX code |
| cen64 | P | SSE intrinsics throughout |

Probable, x86 intrinsics without a fallback (Debian patches them to use
SIMDe): bowtie2, hisat2, kalign, spoa, abpoa, plink1.9, plink2, salmon, rapmap,
wtdbg2, last-align, fasta3, gmap, parasail, macs, metaeuk, mmseqs2, scrappie,
snap-aligner, hhsuite, examl, iqtree, iqtree3, cmaple, libgssw, libdozeu,
consensuscore, pbcopper, rna-star, plast, seqan-raptor, python-skbio, kitty,
wabt, z3, openmm, onednn. Most build with make or CMake and zlib, so
`envs/tools-power9` fits many of them.

Test failures (the acceptance test runs the project's tests):

| Package | Status | What fails on ppc64le |
|---|---|---|
| backward-cpp | C | division by zero raises no SIGFPE on PowerPC |
| json-schema-validator | C | an e-mail check with UTF-8 (probably `char` being unsigned on PowerPC) |
| geos | C | 1 of 535 tests (probably fused multiply-add rounding) |
| python-emcee | C | no `float128`: `long double` differs on ppc64le |
| lpcnet | C | the `SIMD_functions` test |
| sqlite3 | C | `waliter.test` (possibly the 64 KB pages) |
| blosc2 | C | 1 of 7 tests |
| ensmallen | C | `lrsdp_test` |
| libcdada | C | `str_test` aborts |

## Hard: very large builds, JIT or code generation, or a deep cause

| Package | Status | Why |
|---|---|---|
| tensorflow | case | Bazel; see the case |
| jaxlib | case | Bazel; see the case |
| python-torch | case | RPM case |
| samply | C | Rust: `framehop` has no unwinder for ppc64 |
| ffcall | C | its calling-convention assembly fails the `vacall` tests |
| godot3 | C | SSE in the bundled libvpx |
| mame, mariadb | C | test failures in very large projects |
| vectorscan, llvm23, nodejs26, nodejs-electron, openvino, ollama, bazel8 | C | fail on ppc64le, but the end of the log does not show why: investigate first |
| hyperscan | P | x86 only (vectorscan is its portable fork) |
| LuaJIT | P | no PowerPC 64 port upstream |
| iisignature, libxsmm | P | x86 JIT |
| wasmedge, dart-sdk, ldc, ghdl (mcode), ispc, tcc, chibicc | P | compilers or runtimes with no ppc64le code generation |
| uftrace, dtrace, seastar | P | low-level, architecture-specific runtime code |

## Not suitable

- Tools that only make sense on x86: cpuid, msr-tools, dmidecode, x86info,
  memtest86+, fasm, the `intel-*` packages.
- Emulators built around an x86 JIT: pcsx2, yuzu; firmware and boot loaders.
- 79 openSUSE packages, nearly all in Go, that fail only in RPM packaging
  (`%install`, rpmlint): their own build does not fail.

## Adding a candidate

```bash
make new-case CASE=<name> SOURCE=<url of a release archive> ENV=tools-power9
make baseline CASE=<name>      # must fail, for the reason above
make check-case CASE=<name>
```

Then write `build.sh` as the project builds on x86_64 and an acceptance test
that checks what it built against an x86_64 build (see the ten cases above),
and move the package's line here to "case".
