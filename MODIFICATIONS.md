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
- None yet.

### Planned
- Expose only the repair tools to the LLM; the bookkeeping tools
  (`check_repeat_tool_call`, `reset_package_cache_tool`,
  `track_file_modification_tool`, ...) are currently callable by the model.
- Feed real modification history into the next attempt's prompt.
- Count a repair as successful only if the package still builds on the source
  architecture.
- Do not end an attempt with an unverified fallback upload.
- Invalidate the cached `get_structure_of_files` result after extraction or
  modification.
- Make `extract_archive_tool`/`compress_to_archive_tool` act on the same
  archive when a package ships several.
- Restrict file tools to the package's temporary directory and extract
  archives with `filter="data"`.
- Port the Patch strategy (`client_patch.py`) to the per-direction configs.
- Answer unknown tool names with the list of valid tools.
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
