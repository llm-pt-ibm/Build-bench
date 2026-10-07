# Modifications relative to the original Build-bench

The original framework (x86_64 → aarch64) is kept in the `original` branch, a
snapshot of [zcyyc/Build-bench](https://github.com/zcyyc/Build-bench) at
`ccd324d` with the upstream OBS credentials in `config/info.yaml` replaced by
placeholders.

To list every changed file of a branch:

```bash
git diff --stat original <branch>
```

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
The agent loop keeps the original logic (conversation format, repeat guard,
cache, upload detection, fallback upload). Only these changes were made:
- The MCP server is started with the current interpreter instead of `uv run`
  (also in `client_patch.py`), since `uv` is not available on the Power9
  environment.
- The prompt template is filled with `source_arch`/`target_arch` from the
  selected config.
- Model calls go through `_chat`, which pins the OpenRouter provider when
  `OPENROUTER_PROVIDER` is set and accumulates token usage and cost.
- Per-package metrics are written to `<package>_result.json`: success,
  successful attempt, minutes, LLM calls, tool calls, prompt/completion/cached
  tokens, cost reported by OpenRouter and the providers that served the calls.
- Tool timeout is `obs.max_wait_seconds + 300` instead of a fixed 600 s, so
  that `check_build_result` can wait for a real ppc64le build (see below).

### OBS integration (`tools/auto_repair/`)
Kept because the original check returned the first status other than
`building` within a fixed 180 s, which reports stale or `scheduled` results
for ppc64le builds that take several minutes.
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
- `run_pilot.sh`, `smoke_test.py`, `requirements-ppc64le.txt`.
- `.gitignore` ignores `*.orig`; the committed `__pycache__/*.pyc` files were
  removed.

### Documentation (new)
- `images/build-bench-atividade-uml.{pdf,png}`: UML 2.5 activity diagram of the
  benchmark loop (partitions Cliente, LLM, Servidor MCP and OBS), with the MCP
  tools used by each action. `images/build-bench-atividade-uml.html` is its
  source; regenerate the PDF with headless Chrome (`--print-to-pdf`).

### Logic fixes not in main
Fixes to the agent loop and to `server.py` (valid conversation format for
parallel tool calls, stricter `parse_build_result_tool`, upload detection,
per-attempt upload status, cache target, structure truncation) and the
offline test that covers them live in the `improvements` branch.

### Not ported
- Patch strategy: `client_patch.py` still reads `config/info.yaml` and does
  not pass `source_arch`/`target_arch` to the prompt, so it fails with a
  `KeyError`.
- `README.md` still describes the original setup.
