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
  the whole log.
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
