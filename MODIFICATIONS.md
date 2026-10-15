# Modifications relative to the original Build-bench

The original framework (x86_64 → aarch64) is kept in the `original` branch, a
snapshot of [zcyyc/Build-bench](https://github.com/zcyyc/Build-bench) at
`ccd324d` with the upstream OBS credentials in `config/info.yaml` replaced by
placeholders.

To list every changed file of a branch:

```bash
git diff --stat original <branch>
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
  `prompts/build_recipe_generation.txt` is the prompt of these cases.
  `dataset/recipe_baseline.py` builds a case without the model and saves the
  original failure. First case: jaxlib 0.10.2 (`data/x86_64_to_ppc64le/jaxlib`,
  sources fetched by `dataset/fetch_jaxlib.sh`, environment
  `envs/jax-power9.sh`); it fails in 2 minutes as on any ppc64le host
  (rules_python finds no host Python for ppc64le).
- Extensions for large code bases, enabled per config (`llm.extra_tools`,
  `llm.max_context_chars`): `search_files_tool` (grep -rnE),
  `replace_in_file_tool` (edit an exact piece of a file, with the same history
  and checks as `modify_file_tool`), `get_structure_of_files(max_depth)`, read
  access to the build cache (`BENCH_READONLY_DIRS`), where builds keep the
  dependency sources they download, and shortening of the oldest tool results
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
  by the client from `paths.temp_work_dir`).
- No tool result is cached any more: the only cached tool,
  `get_structure_of_files`, returned stale listings after an extraction.
- OBS requests are retried on timeouts and transient errors (408, 429, 5xx)
  (`tools/auto_repair/obs_http.py`), and uploads only send files whose md5
  differs from the committed revision.
- `<package>_result.json` adds `timing` (model, upload, build check and other
  tools), one summary per attempt (rounds, how it ended, build results, final
  check) and `run` metadata (git commit and branch, config, limits). The full
  conversation of every attempt is saved as
  `<package>_attempt<N>_messages.json` in the log directory.
- `scripts/run_repeats.sh <label> <n> [config]` runs the benchmark N times and
  archives each run in its own directory; `scripts/summarize_runs.py` prints a
  table and the success rate per label.
- `tests/test_helpers.py` (no dependencies) covers the patch check and the log
  excerpt; `tests/test_offline.py` covers the new file and archive behaviour.

### Planned
- Count a repair as successful only if the package still builds on the source
  architecture.
- Use one OBS project per migration direction, so that a package name present
  in both directions cannot clash.
- Classify candidate failures during dataset triage (skip infrastructure
  failures such as "no compliant workers") and filter by source size and
  build time.
- Port the Patch strategy (`client_patch.py`) to the per-direction configs.
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
- `run_pilot.sh`, `smoke_test.py`, `tests/test_offline.py`,
  `requirements-ppc64le.txt`.
- `.gitignore` ignores `*.orig`; the committed `__pycache__/*.pyc` files were
  removed.

### Not ported
- Patch strategy: `client_patch.py` still reads `config/info.yaml` and does
  not pass `source_arch`/`target_arch` to the prompt, so it fails with a
  `KeyError`.
- `README.md` still describes the original setup.
