# 🧩 Build-bench: LLM-driven Cross-ISA Build Repair Framework

This repository implements the **Build-bench** framework — an end-to-end evaluation pipeline for large language models (LLMs) to repair software build failures across instruction set architectures (ISA), such as **x86_64 → aarch64** and **aarch64 → x86_64**.

The system enables **autonomous reasoning**, **tool-augmented repair**, and **executable verification** through iterative interactions based on the Model Context Protocol (MCP).
An interactive visualization of all model results (success/failure cases, tool calls, repair iterations) is available at:
👉 **[https://aiops-lab-nku.github.io/Build-bench/](https://aiops-lab-nku.github.io/Build-bench/)**

**This fork** ports the framework to **x86_64 ↔ ppc64le** and runs it on an IBM
Power9 build host. On top of the original it adds a local build backend,
build-recipe cases for packages that are not RPM packages or are too large
for OBS (e.g. jaxlib with Bazel), acceptance tests that check that the built
software works, a sandboxed experiment tool for the model, a leak check, and
`make` commands to run and inspect the benchmark. `MODIFICATIONS.md` lists
every change and why; the original framework is kept in the `original`
branch.

---

## 🌐 Overview

<p align="center">
  <img src="images/framework.png" alt="Build-bench Framework" width="85%">
</p>

For every case, Build-bench:
1. Copies the failed package (sources, spec or build recipe, failure log) into a workspace;
2. Lets the LLM diagnose the failure and change the package with its tools;
3. Builds the package on the target architecture: on OBS, locally with `osc build`, or with the case's `build.sh`;
4. Runs the case's acceptance test on a successful build (did the built software work?);
5. Repeats with the new log until it succeeds or the attempts run out.

---

## ⚙️ Installation

```bash
git clone https://github.com/yallerocha/build-bench.git
cd build-bench
uv sync                                   # x86_64/aarch64
# ppc64le (no uv wheels): a Python 3.11 environment, then
pip install -r requirements-ppc64le.txt   # on the Power9: conda env build_bench
```

`.env` (never committed) holds the credentials and defaults:

| Variable | Meaning |
|---|---|
| `API_KEY`, `API_BASE_URL` | LLM API (e.g. OpenRouter: `https://openrouter.ai/api/v1`) |
| `LLM_MODEL` | default model, e.g. `deepseek/deepseek-v4.1-flash` |
| `OPENROUTER_PROVIDER` | provider to pin on OpenRouter (optional) |
| `LLM_TEMPERATURE` | sampling temperature (optional; provider default otherwise) |
| `OBS_USER`, `OBS_PASSWORD` | OBS account (OBS backend and local worker) |

The framework runs as a normal user and changes nothing on the host. What it
keeps outside the repository goes to `BENCH_HOME` (default
`~/.local/share/build-bench`): the build environments (`envs/`), the build
directories of build-recipe cases (`stage/`) and the local osc worker
(`obs-worker/`); a config can place them elsewhere, with `~` and
`${VARIABLES}` in its paths. Settings of one machine for make (e.g.
`PY = /path/to/python`, `BENCH_HOME = /data/bench`) go to `local.mk`, which
git ignores.

Build-recipe cases name a build environment (`envs/<name>.sh`), made once
from the recipe in `envs/<name>/` (conda environments from lock files, tools
compiled from their sources, wheels PyPI lacks), in `BENCH_HOME/envs/<name>`:

```bash
make setup-env ENV=jax-power9   # conda (Miniforge) needed; compiles Bazel 7.7.0 (BAZEL_BINARY=<file> reuses one)
make check-env ENV=jax-power9   # load it as a build does and show what it provides
```

The environment script only exports variables (PATH, the C++ runtime of its
compilers through LD_LIBRARY_PATH, the tools' paths); `env.json` records its
versions and checksums, and every result records its id.

The builds, acceptance tests and `run_command_tool` commands of build-recipe
cases run in containers of the environment's image, which `make setup-env`
builds from `envs/<name>/Containerfile` (the system part of the build host:
glibc, headers, binutils) as `build-bench-<name>`. Only what is mounted is
there, at the same paths as on the host: the build copy, its caches and the
build environment. Podman is the default (rootless, no daemon: `dnf install
podman` or `apt install podman` on the build host); the config chooses
another runtime (`build.container`, or `BENCH_CONTAINER_RUNTIME`):

```yaml
build:
  container:
    runtime: podman        # podman (default), docker, or none (on the host)
    build_network: host    # builds download their dependencies; tests and commands get none
    # cpus: 32, memory: 64g, pids_limit: 4096   (default -1: no limit beyond the host's)
```

With Docker the containers run as the user, but its group is
root-equivalent; with `none` build.sh runs on the host with everything the
user can read, and `run_command_tool` uses a sandbox of Linux namespaces that
needs root.

Build backends, per config (`build.backend`):
- **OBS** (`config/x86_64_to_ppc64le.yaml`): the OBS account above; `dataset/setup_obs.py` creates the packages in your OBS project.
- **local** (`config/x86_64_to_ppc64le_local.yaml`, `_power9.yaml`): RPM packages with `osc build` in a local openSUSE chroot, created by `scripts/local_worker/setup.sh`.
- **build recipes** (`_power9.yaml`): cases with a `build.sh`, built in a container of their environment's image, in the environment of `envs/<name>.sh`.

---

## 🚀 Running the Framework

### With make
What to run is set in `bench.yaml`, the run profile; each setting can be
overridden on the command line. The commands run on the build host.

| `bench.yaml` | make variable | |
|---|---|---|
| `config` | `CONFIG` | benchmark config (direction, paths, backend, model options) |
| `label`, `repeats` | `LABEL`, `REPEATS` | runs are archived as `<label>_1` … `<label>_<repeats>` |
| `packages` | `PACKAGES` | cases to run (empty: all of the config's data directory) |
| `model`, `provider` | `MODEL`, `PROVIDER` | model and pinned OpenRouter provider |
| `attempts` | `ATTEMPTS` | build attempts per package |
| `temperature` | `TEMPERATURE` | sampling temperature |

```bash
make                      # list the commands
make run                  # start the profile's run in the background
make run LABEL=run31 ATTEMPTS=6 MODEL=deepseek/deepseek-v4.1-flash
make status               # the dashboard, once
make watch                # the live dashboard (Ctrl-C stops watching only)
make stop                 # stop the run, its builds and experiments; archive it as <run>_stopped
make resume FROM=run29_v41flash_scratch_12att_1 ATTEMPTS=3
make summary              # archived runs, results and total cost (KEY=1: API key usage)
make transcript RUN=run29_v41flash_scratch_12att_1 [ATTEMPT=6 REASONING=1 TOOL=... GREP=...]
make leaks                # look for the answer within the model's reach
make new-case CASE=<name> [ENV=<environment>]
make check-case CASE=<name>
make test
```

`make watch` is a live dashboard of the run in the terminal: the packages
done and to do, the current package's attempt and round, how each attempt
ended, the build (with Bazel's progress) and the acceptance test in progress,
what the model is doing and its latest reasoning, the recent tool calls and
the cost so far. Watch it from another machine with
`ssh -t <build host> 'cd <repository> && make watch'`, or through a
mount of the repository (it only reads files; commands that act on a run
refuse to work away from its host).

Only one run can be active (`.bench/active.json`). A run does not start over
the files an interrupted one left (`make archive NAME=<run>_stopped`), nor
when the leak check finds the answer within the model's reach (ALLOW_LEAKS=1
overrides). Results are written after every attempt, so a stopped run can be
continued from its last finished attempt. Background runs log to
`logs/<label>.log`.

### Local models
Any server with an OpenAI-compatible API works: Ollama, vLLM, llama.cpp's
`llama-server`. Start it with tool calling and a large context window, then
run with `bench.local.yaml` or the variables:

```bash
OLLAMA_CONTEXT_LENGTH=65536 ollama serve &      # Ollama's default window is small and cuts prompts silently
ollama pull qwen3-coder:30b
make run PROFILE=bench.local.yaml
make run BASE_URL=http://127.0.0.1:11434/v1 MODEL=qwen3-coder:30b CONTEXT_CHARS=180000 LABEL=local2
```

`base_url` points the run to the server; the API key of `.env` is never sent
there (`api_key_env` names a variable with the server's own key, if it needs
one). `context_chars` keeps the conversation within the server's window (the
oldest tool results are shortened beyond it). `make run` checks that the
server answers and serves the model before starting; `LLM_TIMEOUT` (or
`llm.request_timeout`) gives slow models more time per reply. Results record
the server in `run.api_base` and `run.local_model`; their cost is $0.

### Directly
```bash
BENCH_CONFIG=config/x86_64_to_ppc64le_power9.yaml BENCH_PACKAGES=jaxlib BENCH_MAX_ATTEMPTS=12 python client.py
scripts/run_repeats.sh <label> <n> [config]   # n runs, each archived in its own directory
```
`client.py` reads its settings from the environment: `BENCH_CONFIG`,
`BENCH_PACKAGES` (comma-separated), `BENCH_MAX_ATTEMPTS`, `LLM_MODEL`,
`OPENROUTER_PROVIDER`, `LLM_TEMPERATURE`, `BENCH_RESUME_FROM` and
`BENCH_RESUME_WORKSPACE` (continue a run), `BENCH_BUILD_BACKEND`,
`BENCH_FINAL_NEWLINE`. The Patch Generation strategy of the original
(`client_patch.py`) has not been ported to the new configs.

---

## 🗂️ Configs

| File | Direction | Build |
|---|---|---|
| `config/x86_64_to_ppc64le.yaml` | x86_64 → ppc64le | OBS |
| `config/ppc64le_to_x86_64.yaml` | ppc64le → x86_64 | OBS |
| `config/x86_64_to_ppc64le_local.yaml` | x86_64 → ppc64le | local `osc build` |
| `config/x86_64_to_ppc64le_power9.yaml` | x86_64 → ppc64le | local `osc build` and build recipes on the Power9, with the large-package options (60 rounds per attempt, extra tools, notes between attempts, acceptance tests) |
| `config/x86_64_to_ppc64le_power9_nonotes.yaml` | x86_64 → ppc64le | the same without notes between attempts (an ablation) |
| `config/info.yaml` | x86_64 → aarch64 | the original's config |

---

## 📦 Cases

A case is a directory `data/<direction>/<package>/` that is copied into the
model's workspace at the start of a run:

- **RPM package** (a `.spec`): sources and patches from openSUSE, `log_failed.txt` from OBS and `manifest.json` with their origin. `python dataset/fetch_package.py <package> x86_64_to_ppc64le` fetches one; `dataset/find_candidates.py` lists packages that build on x86_64 and fail on ppc64le.
- **Build recipe** (a `build.sh`, no `.spec`): the sources (large trees are fetched by a `dataset/fetch_<package>.sh` and ignored by git), `build.sh`, `manifest.json` naming its build environment (`envs/<environment>.sh`, which the model cannot change) and `log_failed.txt`, saved by `dataset/recipe_baseline.py`. `make new-case` starts one from a template.

**Acceptance tests** (`acceptance/<direction>/<package>.sh`) run after every
successful build; a build only counts when its test passes. The model can
read them, not change them. jaxlib's installs the wheel in a clean Python and
runs numerical checks and 1528 tests of JAX's own suite.

**Reference fixes** go to `dataset/reference/<package>/`, outside the case:
the leak check refuses a run when a file with their content is within the
model's reach. `make check-case` checks a case before its first run.

---

## 🧰 Model tools

File structure and content, `search_files_tool`, `replace_in_file_tool` and
`modify_file_tool` (patch files are checked, and the history of every edit is
kept for the next attempts), archive extraction and compression, upload and
build check. With build recipes the model can also read the dependency
sources the build downloaded (its build cache), and run short commands with
`run_command_tool` (e.g. a single failing test, or a small C program that
reproduces a compiler bug). Each command runs in a container of the build
environment's image (with `runtime: none`, a sandbox of namespaces): only the
package and the build cache (read-only), the build environment and a scratch
directory are there, with no network and no capability left.

---

## 📈 Results

For every run, `result_text_res/<config>/<run>/` holds `<package>_result.json`
(success, attempt, cost, tokens, timing, one summary per attempt, the run's
git commit and settings, leak check findings) and `result_log_res/<config>/<run>/`
the log, the conversation of every attempt (`<package>_attempt<N>_messages.json`,
with the model's reasoning) and the diff log of its edits. `make summary` and
`make transcript` read them.

---

## 🧪 Tests

`make test` runs `tests/test_helpers.py` (patch check, log excerpt, build
backends, resume, run profile, leak check, cases, sandbox, containers with
Podman or Docker when one is installed with the base image) and
`tests/test_offline.py` (the tools through MCP with a scripted model). They
write only to temporary directories.

---

## 📂 Directory Structure

```
.
├── bench.yaml, Makefile          # run profile and commands
├── client.py, server.py          # MCP client (repair loop) and server (tools)
├── config/                       # benchmark configs
├── prompts/                      # system prompts (RPM cases, build recipes)
├── tools/auto_repair/            # build backends, acceptance tests, sandbox, leak check, log excerpt
├── data/<direction>/<package>/   # cases
├── acceptance/<direction>/       # acceptance tests
├── envs/                         # build environments of build-recipe cases
├── dataset/                      # fetching, baselines, case tools, reference fixes
├── scripts/                      # bench.py, run_repeats.sh, watch_run.py, transcript.py, workers
├── tests/
├── result_text_res/, result_log_res/   # archived runs
└── MODIFICATIONS.md              # every change relative to the original
```

## 📊 Data and Case Study

The folder data/case_study/ provides example build results (e.g., x86→ARM full repair) used in Section 5 of the paper for qualitative analysis.
