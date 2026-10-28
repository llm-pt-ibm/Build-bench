# Modifications relative to the original Build-bench

This repository is a GitHub fork of
[zcyyc/Build-bench](https://github.com/zcyyc/Build-bench): the original
framework (x86_64 → aarch64) is its history up to `ccd324d`, and the first
commit after it starts the port (it also removes the upstream OBS credentials
from `config/info.yaml`). The run results of this work are kept out of the
repository; the commits are those of the development repository, rewritten
onto `ccd324d` without them.

To list every changed file of a branch:

```bash
git diff --stat ccd324d <branch>
```

## improvements: changes on top of main

This branch starts from `main` and inherits every modification listed in the
next section. Its own changes are listed here; `git diff --stat main
improvements` shows them file by file.

### Done
- `LLM_TEMPERATURE` (optional, in `.env` or the environment) sets the sampling
  temperature sent with every model call; it is recorded as `temperature` in
  `<package>_result.json`. When unset, no temperature is sent and the
  provider's default applies (the behaviour of `main`).
- The LLM only sees the seven repair tools (`LLM_TOOLS` in `client.py`):
  structure, file content, archive extraction/compression, file modification,
  OBS upload and build check. The bookkeeping tools (`check_repeat_tool_call`,
  `check_tool_cache`, `cache_tool_result`, `record_tool_call_history`,
  `reset_package_cache_tool`, `update_prompt_with_history_tool`,
  `parse_build_result_tool`, `track_file_modification_tool`,
  `get_packages_to_process`, `init_package_environment_tool`) stay callable by
  the client only, matching the paper, where they are part of the framework
  rather than agent tools. A call to any other name, including a hallucinated
  one such as `get_file_content`, is refused with the list of valid tools.
- `modify_file_tool` records every effective change (path relative to the
  package and the unified diff) in the modification history, which
  `update_prompt_with_history_tool` shows as `diff` blocks (up to 3,000
  characters each) from the second attempt on. Before, the history was only
  filled when the LLM itself called `track_file_modification_tool`, so later
  attempts usually started without knowing what had been changed; the paper
  describes this history as part of every iteration's input. The history is
  cleared when a package is prepared.

- Prompt (`prompts/full_file_generation.txt`) aligned with the tool workflow:
  it lists the seven tools, ends every repair cycle with compress → upload →
  `check_build_result`, states the real build wait (`obs.max_wait_seconds`),
  explains `log_failed.txt` vs `log_failed_original.txt` and that patches are
  applied with `--fuzz=0`. Removed the "Output format" section (answer only
  with `===FILE: …===` blocks) and the request to save results to a file, which
  contradicted tool use: a reply without tool calls ends the attempt.
- Final verification instead of the fallback upload: when an attempt ends with
  edits that were never uploaded, files changed inside `extracted/`, or an
  upload whose build was never checked, the client compresses, uploads and
  checks the build itself. A success found this way is recorded with
  `success_verified_by: "framework"` (`"agent"` when the model checked it).
- The client no longer makes a 21st model call whose answer was discarded.
- `log_failed_original.txt` keeps the failure that motivated the task;
  `log_failed.txt` is still replaced by the latest failed build, as in the
  paper.
- `check_build_result` returns the key lines of a failed build log
  (`tools/auto_repair/log_excerpt.py`), so the model does not need to reread
  the whole log. For patch failures they include the message of `patch` (for
  example "patch unexpectedly ends in middle of line") and the `Patch #N`
  header of the failing patch; lines from installing the build environment are
  skipped, and so are `-Winline` "inlining failed" warnings.
- Local build backend (`build.backend: local` in the config, or
  `BENCH_BUILD_BACKEND=local`): `upload_file_to_obs_tool` copies the sources
  and starts `osc build` in a local worker, and `check_build_result` waits for
  it and returns the same messages as with OBS
  (`tools/auto_repair/local_build.py`). The worker is an openSUSE Tumbleweed
  chroot created by `scripts/local_worker/setup.sh`; `osc build` resolves the
  dependencies against `openSUSE:Factory:PowerPC/standard`, as OBS does, and
  the saved log keeps only the build output. It removes the OBS worker
  constraints (packages such as python-torch never start on OBS ppc64le
  workers: "no compliant workers") and the queue. The zita-resampler failure
  reproduces locally (`arm_neon.h`, 18 s). `config/x86_64_to_ppc64le_local.yaml`
  uses it, with separate result directories and a 6 h build timeout. The
  backend is recorded in `run.build_backend`.
- `dataset/fetch_package.py` accepts the package name of the failing log as a
  third argument (for multibuild flavors such as `python-torch:standard`).
- Build-recipe cases, for packages that are not RPM packages or are too large
  for OBS (any build system: Bazel, CMake, Cargo, pip...): a case directory
  with a `build.sh` and its sources (directories or archives), detected by
  `tools/auto_repair/case_type.py`. `upload_file_to_obs_tool` mirrors the
  package to a stable build directory (only changed files are copied) and runs
  `build.sh` there through `scripts/script_worker/run.sh`;
  `check_build_result` returns the same messages as with OBS
  (`tools/auto_repair/script_build.py`). Each package keeps a persistent cache
  (`BENCH_CACHE_DIR`), so builds are incremental across attempts and runs;
  paths of the build copy in the log are rewritten to the workspace. The case
  declares its build environment in `manifest.json` (`envs/<name>.sh`, set up
  before `build.sh` and not editable by the model, like an OBS build host).
  `prompts/build_recipe_generation.txt` is the prompt of these cases. It
  tells the model that the cause may be in a downloaded dependency (a
  library, a code generator, a compiler backend) and is fixed there with a
  patch, even when the log only names its functions: in the jaxlib runs the
  model patched highway, boringssl and rules_python, whose compile errors
  point into the build cache, but spent attempts 10 to 12 working around in
  XLA an LLVM PowerPC backend crash (`Cannot select: bf16_to_fp`) seen at run
  time, whose stack trace has no file paths. Runs up to run26c used the
  prompt without this paragraph. Until run26d the `run` metadata of a result
  was read when the package ended, so run26c records commit 218344b although
  it ran aa08d15; it is now read when the package starts. After run28 the
  paragraph also accepts a workaround (turning off the failing feature or
  code path) when the fix in the dependency does not work out: its first
  wording ("rather than only avoiding the failing code path") kept the model
  from turning off XLA's CPU fusion emitters, the manual port's workaround
  for the int8 failures below.
- `run_command_tool(package_name, command, timeout_seconds)` (build-recipe
  cases, enabled with `llm.extra_tools`): runs short shell commands on the
  build host, in the build environment, so the model can test a hypothesis
  in seconds instead of a full build (`tools/auto_repair/experiment.py`).
  Each command runs in a sandbox of Linux namespaces (a container now, see
  Containers below): /root, /tmp, /var/tmp
  and /dev/shm are hidden (other builds, earlier runs and the framework's
  files cannot be read), the workspace, the last build's copy and the build
  cache come back read-only, the scratch directory (cleared with the cache)
  is writable, and there is no network and no capability left. The paths the
  build environment needs are listed in `script.experiment_paths`, and
  directories inside them that stay hidden in `script.experiment_hide`: in
  run28c, its first run, all of /root/miniforge3 was visible and the model
  found the team's manual port there (jaxlib 0.10.2 installed in the
  jax_build and jax_user environments, the conda package cache and
  conda-bld) and ran the JAX tests with it, so the run was stopped and
  discarded; only the two environments the build uses are shown now,
  without their jax and jaxlib. In run28
  the model spent attempts 7-12 on two numeric JAX test failures it could
  only observe through full builds; reproducing them by hand took a few
  short commands: `jnp.array([-3, 5], int8).astype(float32)` gives
  `[253, 5]`, and a 10-line C program built with `-mcpu=pwr9` shows the
  cause, an LLVM PowerPC bug (the Power9 patterns for signed byte
  vector-extract to fp in `PPCInstrVSX.td` sign-extend from a halfword).
  `dataset/reference/jaxlib/ppc_vextsb2d.patch` fixes it; with it and the
  model's own bf16 patch (`ppc_bf16_by_model_run28.patch`), the run28
  workspace passes the acceptance test (1528/1528 JAX tests). The files in
  `dataset/reference/` are outside the cases and never reach the model.
  `dataset/recipe_baseline.py` builds a case without the model and saves the
  original failure; `dataset/recipe_reference_fix.py` builds a copy of a case
  with known patches applied, through the same upload/check as the model, to
  show that the case can be solved with changes inside the package. First case: jaxlib 0.10.2 (`data/x86_64_to_ppc64le/jaxlib`,
  sources fetched by `dataset/fetch_jaxlib.sh`, environment
  `envs/jax-power9.sh`); it fails in 2 minutes as on any ppc64le host
  (rules_python finds no host Python for ppc64le).
- Extensions for large code bases, enabled per config (`llm.extra_tools`,
  `llm.max_context_chars`): `search_files_tool` (grep -rnE),
  `replace_in_file_tool` (edit an exact piece of a file, with the same history
  and checks as `modify_file_tool`), `get_structure_of_files(max_depth)`, read
  access to the build cache (`BENCH_READONLY_DIRS`), where builds keep the
  dependency sources they download (only the caches of the run's packages:
  until run28 the whole stage root was readable, and in run28's attempt 5 the
  model found and read the build of a reference fix stored there; that
  attempt was discarded), and shortening of the oldest tool results
  when the conversation grows past `max_context_chars`.
  `config/x86_64_to_ppc64le_power9.yaml` enables them and builds everything on
  the Power9 (RPM packages with osc, recipes on the host).
- Continuing a run: with `BENCH_RESUME_FROM=<earlier run label>` (and
  `BENCH_MAX_ATTEMPTS` more attempts) the client keeps the package workspace
  (or copies `BENCH_RESUME_WORKSPACE`) and the build cache, numbers the
  attempts after the earlier ones, and starts with the earlier changes
  against the original package (`tools/auto_repair/resume.py`) and the
  model's notes of the last attempt. The result records `resumed_from`.
- `llm.max_build_attempts` (3 by default, as in the paper) sets the attempts
  per package; `BENCH_MAX_ATTEMPTS` overrides it for a single run.
- More options for large packages (all off by default, on in
  `config/x86_64_to_ppc64le_power9.yaml`): `llm.max_tool_rounds` (rounds per
  attempt, 20 in the paper; the 3 attempts are kept), `llm.round_notice_at`
  (tell the model when few rounds are left), `llm.carry_notes_chars` (the next
  attempt gets the model's own notes, so findings are not lost when it made no
  edit) and `llm.repeat_guard_per_build` (identical calls counted per build,
  so upload/check are not capped at 3 per attempt). Patch files of
  build-recipe cases are checked strictly (Bazel's `ctx.patch` and
  `git apply` reject short hunks that GNU patch accepts).
- Acceptance tests: a build only counts as successful when the built
  software works. A case can have `acceptance/<source>_to_<target>/<package>.sh`,
  outside the package, which the framework runs after every successful build
  with the local backends (`tools/auto_repair/acceptance.py`); the model can
  read it but not change it, and a failing test is reported as a failed build
  with the test output as the log. `manifest.json` and
  `log_failed_original.txt` can no longer be changed by the model.
  - `jaxlib.sh`: installs the wheel in a clean Python and runs a numerical
    battery against NumPy (float32/64, float16, bfloat16, int8 inside jit,
    linear algebra, FFT, gradients, PRNG bit-identical to x86_64, a small
    training run) and JAX's own `random`, `linalg` and `nn` tests. The wheel
    of the manual port passes (1528 tests); the wheel built in run 19, which
    only had a smoke test in `build.sh`, fails 20 tests: attention kernels
    abort (bfloat16 in LLVM's PowerPC backend) and two int8 results are wrong
    (fusion emitters). The check was removed from the jaxlib `build.sh`.
  - When JAX's tests crash a pytest worker, the error output is lost, so
    the test runs two of the crashed tests alone without output capture and
    shows why they abort (e.g. `LLVM ERROR: Cannot select: ... bf16_to_fp`
    in LLVM's PowerPC instruction selection).
  - `zita-resampler.sh`: installs the built RPMs in the build root and
    resamples a 1 kHz sine from 44.1 to 48 kHz with Resampler and VResampler.
- Infrastructure failures are not blamed on the package: when a local build
  fails because the network is unreachable or a name does not resolve
  (`tools/auto_repair/infra.py`), the backend retries it after 1, 3 and 5
  minutes; if it still fails, the check returns "Build infrastructure error!",
  which ends the package's run with `infrastructure_error: true` instead of
  using up the model's attempts (in run 20, a 50-minute DNS outage of the
  container made all 56 zita builds fail). `scripts/summarize_runs.py` shows
  these runs as INFRA and leaves them out of the success rate.
- Runs of build-recipe cases are isolated from each other: the per-run build
  cache (`BENCH_CACHE_DIR`, e.g. Bazel's output root) is cleared when a run
  starts, after stopping the processes that use it (`reset_cache`), and only
  content-addressed caches are shared between runs (`BENCH_SHARED_CACHE_DIR`,
  used by the jaxlib recipe for Bazel's `--disk_cache` and
  `--repository_cache`). In run 22 the model made `build.sh` delete parts of
  the Bazel cache, which would have broken the following runs in a way the
  original build cannot show (it fails before reaching the damage). The
  framework also warns when the original package no longer fails as the
  case's original failure (`same_failure`), and the recipe prompt asks not to
  delete the cache.
- The local worker's resolver lists public DNS servers after the host's
  (`scripts/local_worker/enter.sh`, `WORKER_FALLBACK_DNS`): the container's
  embedded DNS fails at times, which is what made the osc builds of zita fail
  in runs 20 and 21 while the host could still resolve names.
- Model calls that fail for a passing reason (rate limits, which StreamLake
  reports as 413, unavailable servers, timeouts, dropped connections) are
  retried after 20 s, 1, 2, 5 and 10 min (`llm.retry_waits`); if the provider
  still fails, the package's run stops with `infrastructure_error: "model
  provider"` instead of using up the remaining attempts (in run 23 a rate
  limit ended attempts 2 and 3 in their first second).
- `llm.empty_reply_retries`: a model reply with neither text nor tool calls
  is a glitch, not a decision to stop; the framework asks the model to go on
  (in run 20 such a reply ended jaxlib's first attempt at round 20).
- `build.script.build_original_on_init`: before the first attempt the
  framework builds the original package once, so the build cache and the
  dependency sources the model reads there reflect the original package (in
  the fourth jaxlib run they still had a patch from an earlier run).
- Live progress: `client.py` writes `<log_dir>/<package>_status.json` after
  every model call (attempt, round, builds, context size, tokens and cost);
  `scripts/watch_run.py [config] [package]` shows it with the latest tool
  calls, refreshed every 10 s. Transcripts are saved after every round.
- `check_patch_format` no longer flags valid patches: extra context lines after
  a hunk (ignored by patch), empty patches and git rename-only patches. The
  log excerpt also keeps Bazel/Starlark failures (`Error in fail:`, `FAIL:`).
- `BENCH_PACKAGES` (optional, comma-separated) limits a run to those packages
  of the data directory.
- `BENCH_FINAL_NEWLINE` (default `add`, or `off`): `modify_file_tool` adds the
  final newline to the content of a new file or of a file that had one.
  DeepSeek V4 (StreamLake, Alibaba and Relace) and Qwen3-Coder cannot end a
  tool-call string argument with a newline (asked for `"abc\n\n"`, DeepSeek
  sends `"abc"` and Qwen3-Coder `"abc\n"`; GLM 5.1 and Claude Sonnet 4.5 send it
  intact), so every patch they wrote was rejected by `patch` regardless of its
  content. The value is recorded in `run.final_newline`.
- `modify_file_tool` can create new files (for example a new patch) and warns
  when a `.patch`/`.diff` file is malformed, using the same hunk-count rule as
  `patch --fuzz=0` (`tools/auto_repair/patch_check.py`).
- `get_file_content_tool` accepts `start_line`/`max_lines` and shortens files
  larger than 60,000 characters in the middle.
- `extract_archive_tool` no longer silently discards edits made inside
  `extracted/` (it needs `force=true`), extracts tar archives with
  `filter="data"` and rejects zip members outside the target directory.
  `compress_to_archive_tool` repacks the archive that was extracted, and keeps
  it untouched when nothing inside `extracted/` changed.
- File tools refuse paths outside the working directory (`BENCH_TEMP_DIR`, set
  by the client to the workspace directory, `temp_workspace/`).
- No tool result is cached any more: the only cached tool,
  `get_structure_of_files`, returned stale listings after an extraction.
- OBS requests are retried on timeouts and transient errors (408, 429, 5xx)
  (`tools/auto_repair/obs_http.py`), and uploads only send files whose md5
  differs from the committed revision.
- `<package>_result.json` adds `timing` (model, upload, build check and other
  tools), one summary per attempt (rounds, how it ended, build results, final
  check) and `run` metadata (git commit and branch, config, limits). The full
  conversation of every attempt is saved as
  `<package>_attempt<N>_messages.json` in the log directory, with the model's
  reasoning (`reasoning`, when the provider returns it) next to each reply;
  the reasoning is not sent back to the model.
- `scripts/run_repeats.sh <label> <n> [config]` runs the benchmark N times and
  archives each run in its own directory; `scripts/summarize_runs.py` prints a
  table and the success rate per label.
- `make` and `bench.yaml`: the commands of the benchmark in one place
  (`scripts/bench.py`). `bench.yaml` says what to run (packages, model,
  provider, attempts, label, repeats; since the single config, everything
  else too), and make variables override it (`make run LABEL=... ATTEMPTS=...`). `make run`
  starts run_repeats.sh in the background and records it in
  `.bench/active.json`: one run at a time, and no start over the files an
  interrupted run left, which run_repeats.sh would archive with the new run.
  `make stop` stops the run, its builds (they run in sessions of their own)
  and archives what it left as `<run>_stopped`; `make resume FROM=<run>
  ATTEMPTS=<n>` continues an archived run; `make status`/`watch` show the
  active run; `make summary` lists the archived runs with the total cost,
  stopped ones included.
- Installation on a normal host, as a normal user: nothing in the code
  assumes /root or changes the system any more.
  - `BENCH_HOME` (default `~/.local/share/build-bench`,
    `tools/auto_repair/paths.py`) holds the build environments, the build
    directories of build-recipe cases and the local osc worker when a config
    does not place them; config paths take `~` and `${VARIABLES}`. The
    Python of make comes from `local.mk` (ignored by git) or `python3`.
  - Build environments live in the user's directory and are made once:
    `make setup-env ENV=<name>` runs the recipe `envs/<name>/setup.sh`
    into `BENCH_HOME/envs/<name>`, and `envs/<name>.sh` only exports from it
    (`BENCH_ENV_DIR`, set by the framework for builds, acceptance tests and
    run_command_tool). jax-power9's recipe makes three conda environments
    from lock files (exact packages and checksums, no solving): build
    (Python 3.12, clang/lld 17, numpy, scipy: the conda packages of the
    environment the case was set up with; solved from the package list
    alone, conda chose GCC 16's libstdc++ headers, which clang 17 cannot
    compile), tools (Java 21, zip, patch, git, in an environment of their own
    because current openjdk builds and LLVM 17 need conflicting icu versions)
    and test (no jax). It compiles Bazel 7.7.0 from its sources (conda-forge
    stops at 6.x for ppc64le) in two steps, as the team's manual port did:
    7.7.0's own bootstrap fails (bazelbuild/bazel#27349), so Bazel 7.1.0 is
    bootstrapped and builds 7.7.0. It also builds the numpy, ml-dtypes and
    zstandard wheels. The C++ runtime of the conda
    compilers comes through LD_LIBRARY_PATH from a directory with only
    libstdc++ and libgcc_s. Before, the environment script installed
    packages with dnf, linked compilers into /usr/bin and /usr/local/bin and
    added the conda libraries to /etc/ld.so.conf.d, which on a shared host
    needs root and changes every user's C++ runtime and "gcc"; and it used
    the conda environments of the team's manual port, one of which had its
    jaxlib installed (the leak of run28c). `env.json` records the
    environment's versions and checksums, and each result its id
    (`environment`). `make check-env` loads an environment as a build does.
  - run_command_tool's sandbox and the leak check include the case's build
    environment by themselves; `make run` refuses to start when it is not
    set up.
- Containers (`tools/auto_repair/container.py`, `build.container`): the
  build.sh, acceptance test and run_command_tool commands of build-recipe
  cases run in a container of the case's environment image. Podman is the
  default (rootless, no daemon; what a build writes in its mounts belongs to
  the user), Docker the alternative (`runtime: docker` or
  `BENCH_CONTAINER_RUNTIME=docker`; the container runs as the user, but
  membership in Docker's group is root-equivalent), and `none` runs them on
  the host as before. Only what is mounted is there, at the same paths as on
  the host: the build copy and its caches (writable for the build), the
  environment scripts, the runner and the build environment (read-only), and
  the acceptance tests for the test. build.sh therefore no longer runs with
  everything the user can read (other users' files, earlier runs, the
  framework, the team's manual port), which the leak check could not cover.
  The build has the host's network (`build_network`; build.sh downloads its
  dependencies), the test and the commands none; the commands also run with
  no capability, and `experiment_hide` puts empty directories over hidden
  paths (Podman copies a directory's contents into a tmpfs mounted over it
  unless told `notmpcopyup`; the test found this). `cpus` and `memory` limit
  a container; `pids_limit` is -1 (none beyond the host's, as with Docker)
  because Podman's default of 2048 processes and threads stopped jaxlib's
  test suite (48 pytest workers, each starting OpenBLAS's threads). The image (`envs/<env>/Containerfile`, `build-bench-<env>`)
  is the system part of the build host: jax-power9's is UBI 8.9 with
  glibc-devel, kernel headers, binutils and basic tools (the first build in
  a container failed because numpy, built from source by rules_python, needs
  `ar`). `make setup-env` builds it and records its id in env.json, `make
  check-env` loads the environment in it, `make run` refuses to start
  without the runtime or the image, and stopping a build, a cache reset and
  `make stop` remove the package's containers. The runtime is called with
  `GODEBUG=netdns=cgo` (Go's own resolver fails with Docker's embedded DNS,
  as in the Power9 container). The namespace sandbox stays for `runtime:
  none` (it needs root). On the Power9, itself a Docker container, Podman
  4.9 was installed from the UBI repositories and runs nested containers as
  root. run29's jaxlib built in a container (37 minutes after a cache
  reset) and passed its acceptance test in another, with no network (11
  checks, 1528 tests of JAX's suite).
- The build's network (`build.container.build_network`, default `proxy`):
  the network was the last way an answer could reach a build, since
  build.sh, which the model writes, ran with the host's network and could
  download anything, say a ready-made fix or a jaxlib wheel built by
  someone else. A build container now has no network of its own; it reaches
  only the hosts its environment may download from
  (`envs/<env>/allowed_hosts.txt`, plus `allowed_hosts` in the config)
  through a proxy of the framework (`tools/auto_repair/net_proxy.py`),
  which runs for the length of the build on a Unix socket mounted into the
  container. Inside it, `scripts/script_worker/proxy_forward.py` (system
  Python of the image) makes the socket a proxy on 127.0.0.1, which run.sh
  exports as `http_proxy`/`https_proxy`. Every connection is logged to the
  run directory's `network.log`, and a failed build's message names the
  hosts the proxy refused and those it allows. HTTPS is tunnelled, so the
  proxy sees hosts, not paths: an allowed github.com serves everything on
  it. `audit` allows and logs every host, to make an environment's list;
  `host` and `none` remain. jax-power9's list comes from two audit builds
  with an empty Bazel repository cache: Bazel's mirrors
  (storage.googleapis.com, mirror.bazel.build), JAX's PyPI mirror and PyPI's
  files, the Go SDK (go.dev, golang.org, dl.google.com), and github.com with
  release-assets.githubusercontent.com, which only one of the audits needed
  (dependencies a mirror lacked). The first audit build failed in
  rules_python's pip: its hermetic Python looks for CA certificates in
  /etc/ssl/cert.pem, which RHEL does not have, and that pip found them only
  without a proxy; the image now links /etc/ssl/cert.pem to RHEL's bundle.
  With only these hosts and an empty repository cache, run29's jaxlib built
  and passed its acceptance test (1528 tests; 9 minutes, Bazel's disk cache
  warm); nothing was refused. Results record the hosts a package's builds
  reached and were refused (`network`), and the recipe prompt tells the model
  in one sentence that builds download only from the allowed hosts.
- jaxlib's acceptance test removes setuptools' `jax/build/lib` and
  `jax/build/bdist.*` before building the jax wheel in the source tree: the
  case's sources came with both (left by a pip install when the case was
  set up; pure Python, no jaxlib), and a second test of the same build copy
  on the same day failed with "File exists" for the wheel's dist-info.
- Images are reproducible and recorded: the base image is pinned by the
  digest of its multi-architecture index, `make setup-env` writes the
  packages of the image to `BENCH_HOME/envs/<env>/image-packages.txt` and
  records the image (id, base, number and checksum of its packages) in
  env.json, and each result records under `environment.container` the
  runtime, the id of the image the builds ran in, its base and package
  checksum, the build network and the allowed hosts. The client warns when
  the image is not the one make setup-env built.
- Prompt caching for Claude models (`llm.prompt_cache`, `BENCH_PROMPT_CACHE`:
  auto, on, off): Anthropic models read a cached prefix only up to the
  breakpoints a request marks with `cache_control`, so without them every
  round paid the whole conversation at the full input price. The client
  marks the system prompt, the last user or tool message, and the last one
  before the latest reply (the previous request's end, which it reads back),
  for `anthropic/` and `claude` models by default; the other providers
  cache by themselves. With caching on, context compaction shortens down to
  80% of `max_context_chars` at once, since every shortening changes the
  cached prefix. Results count `cache_write_tokens` beside `cached_tokens`.
  Checked through OpenRouter with Claude Haiku 5.5: from the second call on
  the conversation came from the cache, and a call cost $0.0003 instead of
  $0.0020.
- Tool calls written as text (`tools/auto_repair/text_tool_calls.py`,
  `llm.text_tool_calls`, `BENCH_TEXT_TOOL_CALLS`, on by default): a model
  server turns a model's calls into tool_calls only when its parser knows the
  model's format; otherwise they arrive as text and the attempt ended with
  "no tool calls". A reply without tool calls is now searched for calls of
  the model's tools in the formats of Hermes/Qwen 2.5–3, Qwen3-Coder, GLM
  4.5, Mistral, Llama 3, DeepSeek V3/R1/V3.1 and gpt-oss, or a reply that is
  only JSON calls; XML-style values get the types of the tool's schema, and
  JSON in prose or calls of unknown tools are left alone. They become real
  tool calls in the conversation, and results count them
  (`usage.text_tool_calls`).
- Attempts that do not move (run30, DeepSeek V4.1 Flash as in run29, which
  succeeded in attempt 6): attempts 6, 8 and 9 ended without a single change
  or build, their 60 rounds spent reading LLVM and running experiments, and
  attempt 7's build failed with the same 20 tests as attempt 5's, without the
  model noticing; the round notices (30, 10, 5 left) did not change this.
  Two generic notes, which do not hint at a fix:
  - `llm.build_drought_rounds` (15 in the Power9 config, 0 by default): after
    that many rounds in a row without a change to the package or a build,
    the last tool result says to apply the change the findings point to and
    build it; an attempt that follows one without any change starts with the
    same advice. Results count the notes (`drought_notes` per attempt).
  - `llm.repeated_failure_note` (on in the Power9 config): when a build fails
    the same way as the previous one (or as the original package), its result
    says that the changes since then did not affect the failure. The
    comparison (`log_excerpt.failure_signature`) takes the error lines, or
    for a failed acceptance test the lines that name failing checks and
    tests, without times, hashes, addresses and paths; unlike the
    root-cause comparison it keeps counts, so 20 and 18 failing tests differ.
- Local models: `base_url` in `bench.yaml` (or `BASE_URL`) points a run to a
  model server of its own with an OpenAI-compatible API (Ollama, vLLM,
  llama.cpp). The API key of `.env` is never sent to
  that server: `api_key_env` names a variable with its own key, and a server
  on this machine or the local network needs none (`client.py` then sends
  "none"). `CONTEXT_CHARS` (`BENCH_MAX_CONTEXT_CHARS`) overrides
  `llm.max_context_chars` to fit the server's context window, `LLM_TIMEOUT`
  or `llm.request_timeout` the time allowed per reply (600 s). `make run`
  first checks that the server answers and serves the model. Results record
  `run.api_base` (scheme, host and port) and `run.local_model`. The
  OpenRouter-only parts (provider pinning, cost) stay off for other servers,
  and the reasoning is read from `reasoning` or `reasoning_content` (vLLM).
- `make watch`/`make status` show a dashboard of the benchmark
  (`scripts/dashboard.py`): the run, its packages (done, running, waiting),
  the current package's attempt and round as progress bars, how each attempt
  ended, the build with Bazel's progress and the acceptance test (running,
  or its checks and test suite result), whether the model is thinking or
  waiting for a build, its latest reasoning, the recent tool calls, elapsed
  time, tokens and cost; with no run, the latest archived one. It only reads
  files, so it also works from another machine through a mount of the
  repository. The active run records its host: away from it the dashboard
  shows "running on <host>", and `make stop`/`archive`/`run` refuse to act,
  as `make run` does on a host that is not the config's build host.
- More commands: `make transcript` (`scripts/transcript.py`) shows the
  attempts of a run or one attempt round by round, with the reasoning, tool
  calls and results, filtered by tool or text; `make new-case`
  (`dataset/new_case.py`) starts a build-recipe case: with `SOURCE=<url>` it
  downloads and unpacks the sources (recorded in manifest.json and the case's
  .gitignore; `make fetch` downloads them again) and writes the build.sh, the
  acceptance test and the build environment of the build system it finds;
  `make baseline` (`dataset/recipe_baseline.py`) saves the original failure
  and `make check-case` (`dataset/check_case.py`) checks a case before a run.
  `make stop` also stops the commands of run_command_tool still running.
  Run logs go to `logs/` (also the client output of run_repeats.sh until the
  run is archived), and `run_pilot.sh` and `smoke_test.py` moved to
  `scripts/`. The tests write only to temporary directories (a copy of the
  config with temporary paths, `BENCH_DIFF_LOG_DIR` for the diff logs).
- `<package>_result.json` is written after every attempt, with `complete`
  false until the package ends, so a stopped run can be continued from its
  last finished attempt (`make resume FROM=<run>_stopped ATTEMPTS=<n>`; the
  workspace keeps the edits of the interrupted attempt, which the continued
  run lists among the earlier changes). Until now only finished runs had a
  result, and continuing run28 needed one written by hand.
- Leak check (`tools/auto_repair/leak_check.py`, `make leaks`): before a
  package runs, what the model can read is searched for the answer: a built
  copy of the package (installed Python package, wheel, conda package, RPM)
  and any file with the content of its reference fix
  (`dataset/reference/<package>/`). Checked are the case, the acceptance
  tests, the build environments and the paths of run_command_tool's sandbox
  (without `script.experiment_hide`). `make run` and `make resume` refuse to
  start when something is found (ALLOW_LEAKS=1 overrides), and client.py logs
  the findings and records them as `leak_check` in the result. It finds the
  two leaks of run28 and run28c when the protections are taken out. Without
  containers (`runtime: none`) it cannot cover build.sh, which then runs on
  the host with everything the user can read.
- `tests/test_helpers.py` (no dependencies) covers the patch check and the log
  excerpt; `tests/test_offline.py` covers the new file and archive behaviour.
- One config, `bench.yaml`, in place of the six files of `config/` and the
  run profile: the source and target architectures, the cases to run, the
  model, the options of the repair loop and the builds, each with a comment.
  What it does not choose follows from `source_arch` and `target_arch`
  (`tools/auto_repair/bench_config.py`): the cases (`data/<direction>/`,
  moved by `cases_dir`), the results and logs
  (`result_text_res/<direction>/<run>/`, `result_log_res/<direction>/<run>/`;
  no config sets them any more), the workspaces (`temp_workspace/`), the OBS
  repository and architecture, and the openSUSE:Factory port local builds
  resolve against (`obs.repository`, `obs.project`, `obs.api_url` and
  `build.local.project` override them). The copies had drifted: the ablation
  without notes also lacked the container, `run_command_tool` and the two
  notes for stuck attempts, and wrote into the Power9 config's result
  directories. `make run` freezes a copy of the file for the run
  (`.bench/run.yaml`), which each run keeps with its logs as `config.yaml`;
  `CONFIG=<file>` runs another config file, and `BENCH_OUTPUT_ROOT` moves the
  workspaces, results and logs (the tests use it). `config/info.yaml`,
  `bench.local.yaml` and `scripts/run_pilot.sh` were removed; the archived
  runs of the Power9 and local configs belong in
  `result_*_res/x86_64_to_ppc64le/`.
- `build.container.runtime: auto`, the default: Podman when it is installed,
  Docker otherwise (the Power9 host has only Docker).
- The framework tries any package, with no known fix:
  - The allow-list of the build's network was removed. Builds reach any host
    through the proxy, which logs every connection (`build_network: log`,
    the default; `proxy` and `audit` of older configs mean it). A list could
    only be made from a build that gets to the end, that is from a case
    whose fix is known, and a host missing from it failed the model's builds
    for a reason it could not change. `envs/jax-power9/allowed_hosts.txt`,
    `build.container.allowed_hosts` and the note on refused hosts are gone;
    results record the hosts the builds reached and those they could not
    reach (`network.reached`, `network.failed`), and the recipe prompt no
    longer mentions a list.
  - Reference fixes were removed: `dataset/reference/` (jaxlib's two
    patches, which stay in the history), `dataset/recipe_reference_fix.py`
    and the leak check's comparison of files with them. The leak check looks
    for built and installed copies of the package, which needs no fix.
- A build environment is one file, `envs/<name>/env.yaml`, for any package and
  build system, every key optional: conda packages of the build and tools
  environments (compilers, CMake, Rust, Go, Java, Python...) and their
  channels, RHEL packages added to the image (`system`), variables exported
  to builds, tests and commands (`env`), commands run once for what no key
  covers (`setup`), a Bazel version, and for Python wheels PyPI lacks and pip
  packages of the build and test environments. `make setup-env` makes it
  with one recipe for every environment (`tools/auto_repair/build_env.py`). Before, each environment had a
  `setup.sh` of its own (about 125 lines), a script exporting it, a
  Containerfile and four lists, most of it the same from one environment to
  the next. Now the framework does that part: the first setup writes the
  lock files (build.lock, tools.lock) the later ones install; Bazel is
  compiled once per version in `BENCH_HOME/bazel/` and copied into each
  environment; the C++ runtime of the conda compilers and the compiler names
  of rules_python's hermetic Python are linked by themselves;
  `scripts/script_worker/env.sh` exports every environment the same way
  (`envs/<name>.sh` replaces it for one that needs more), and
  `envs/Containerfile` is the image of every environment without one of its
  own. jax-power9 is an `env.yaml` with its earlier lists and lock files; its
  `setup.sh`, lists, Containerfile and `envs/jax-power9.sh` are gone.
  `envs/env.example.yaml` shows every key, and `make new-env ENV=<name>`
  starts an environment from it. `make help` listed every command as
  "Makefile" when `local.mk` existed (grep printed the file names).

### Planned
- Count a repair as successful only if the package still builds on the source
  architecture.
- Use one OBS project per migration direction, so that a package name present
  in both directions cannot clash.
- Classify candidate failures during dataset triage (skip infrastructure
  failures such as "no compliant workers") and filter by source size and
  build time.
- Port the Patch strategy (`client_patch.py`): it takes its paths from
  `bench.yaml`, but has none of the other changes.
- Update `README.md`.

## main: port to x86_64 ↔ ppc64le

### Configuration
- `config/x86_64_to_ppc64le.yaml`, `config/ppc64le_to_x86_64.yaml` (new): one
  config per migration direction, selected with `BENCH_CONFIG`. They define
  `source_arch`/`target_arch`, the OBS repository and architecture, per-direction
  result and log directories, and `obs.max_wait_seconds`/`obs.check_interval`.
- `config/info.yaml`: OBS credentials removed.
- `tools/auto_repair/obs_config.py` (new): OBS credentials come from `.env`
  (`OBS_USER`, `OBS_PASSWORD`); the target project is templated as
  `home:{user}:build-bench`.
- `LLM_MODEL` in `.env` selects the model (`client.py`, `client_patch.py`).
- `OPENROUTER_PROVIDER` pins a single OpenRouter provider with fallbacks
  disabled (e.g. `streamlake/fp8`).

### Prompts
- `prompts/full_file_generation.txt`, `prompts/patch_generation.txt`: the
  hard-coded x86_64 → aarch64 wording became `{source_arch}`/`{target_arch}`.

### Agent loop (`client.py`, Full-File strategy)
- Valid conversation format: one assistant message per round, followed by one
  tool message per tool call. The original appended the assistant message once
  per tool call and sent no tool response for blocked repeated calls, which
  breaks the API contract when the model makes parallel calls.
- Blocked repeated calls now receive a tool response explaining the block.
- Only `get_structure_of_files` is cached (the original cached
  `modify_file_tool`).
- An upload counts as successful only when the tool returns
  `Upload successful` (the original matched the substring `success`).
- Tool timeout is `obs.max_wait_seconds + 300` (the original used a fixed
  600 s, shorter than a real OBS build).
- The MCP server is started with the current interpreter instead of `uv run`
  (also in `client_patch.py`).
- Per-package metrics are written to `<package>_result.json`: success,
  successful attempt, minutes, LLM calls, tool calls, prompt/completion/cached
  tokens, cost reported by OpenRouter and the providers that served the calls.

### MCP server (`server.py`)
- `parse_build_result_tool`: success only when the result starts with
  `Build succeeded!`. The original matched substrings such as `ok`, so
  `Build broken` was counted as a success.
- `get_structure_of_files` returns JSON text truncated at 40,000 characters.

### OBS integration (`tools/auto_repair/`)
- `upload_files.py` (rewritten): uploads every source file, commits them with
  `commitfilelist`, fails if OBS reports missing files and records the
  resulting `srcmd5`/revision in `.last_upload.json`.
- `check_build_res.py` (rewritten): requires a previous upload, waits until the
  result is final and not dirty, checks that the build log's `srcmd5` matches
  the upload (so a stale result is never reported), handles
  `unresolvable`/`broken`/`excluded`/`disabled`, and uses the configurable
  timeout (the original waited a fixed 180 s).

### Dataset (new)
- `dataset/find_candidates.py`: packages that build on one architecture and
  fail on the other in openSUSE:Factory / openSUSE:Factory:PowerPC.
- `dataset/fetch_package.py`: downloads a package's sources and the failing
  build log into `data/<direction>/<package>`.
- `dataset/setup_obs.py`: creates the OBS project and checks that each case
  reproduces (succeeds on the source architecture, fails on the target).
- `dataset/peek.sh`, `dataset/candidates.json`, `dataset/logs/`: triage aids.
- Cases: `data/x86_64_to_ppc64le/zita-resampler` (valid) and
  `data/ppc64le_to_x86_64/llamacpp` (does not reproduce: OBS reports
  `disabled`).

### Tooling (new)
- `scripts/run_pilot.sh`, `scripts/smoke_test.py`, `tests/test_offline.py`,
  `requirements-ppc64le.txt`.
- `.gitignore` ignores `*.orig`; the committed `__pycache__/*.pyc` files were
  removed.

### Not ported
- Patch strategy: `client_patch.py` still reads `config/info.yaml` and does
  not pass `source_arch`/`target_arch` to the prompt, so it fails with a
  `KeyError`.
- `README.md` still describes the original setup.
