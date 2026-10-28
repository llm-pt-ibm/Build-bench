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
every change and why. This repository,
[llm-pt-ibm/Build-bench](https://github.com/llm-pt-ibm/Build-bench), is a
GitHub fork of [zcyyc/Build-bench](https://github.com/zcyyc/Build-bench): the
original framework is its history up to `ccd324d`, the port to ppc64le is on
`main`, and the work since is on `improvements`. Run results are not part of
the repository.

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
git clone -b improvements https://github.com/llm-pt-ibm/Build-bench.git build-bench
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
(`obs-worker/`); the config can place them elsewhere
(`build.script.stage_root`, `build.local.worker_root`), with `~` and
`${VARIABLES}` in its paths. Settings of one machine for make (e.g.
`PY = /path/to/python`, `BENCH_HOME = /data/bench`) go to `local.mk`, which
git ignores.

Build-recipe cases name a build environment: what an x86_64 build host gets
from upstream binaries and a ppc64le one lacks. An environment is one file,
`envs/<name>/env.yaml`, for any package and build system; every key is
optional:

```yaml
conda: [cxx-compiler, cmake, ninja, python=3.12]  # the build environment (CMake, Rust, Go, Java...)
channels: [conda-forge]                       # conda channels (the default)
tools: [openjdk=21, zip, unzip, patch, git]   # a separate one, for tools whose dependencies conflict
system: [zlib-devel]                          # RHEL 8 packages (dnf) added to the image
env: {CC: clang, PREFIX: $BENCH_ENV_DIR/build}   # variables exported to builds, tests and commands
setup: ["make -C src install PREFIX=$BENCH_ENV_DIR"]  # commands run once, for what no key covers
bazel: 7.7.0                                  # compiled from its sources, once, shared by the environments
wheels: [numpy==2.1.3, ml-dtypes==0.5.1]      # Python wheels PyPI lacks, built with the environment's clang
build_pip: [ml-dtypes]                        # pip packages of the build environment
test_pip: [ml-dtypes, pytest==9.1.1]          # what the acceptance test imports (it has no network)
```

A name of `build_pip` or `test_pip` among `wheels` is installed from the
built wheel. `envs/env.example.yaml` has every key, explained, with the
conda packages of other build systems, and `make new-env ENV=<name>` copies
it to `envs/<name>/env.yaml`. `make setup-env` makes the environment once, in
`BENCH_HOME/envs/<name>` (`tools/auto_repair/build_env.py`); the first setup
writes `envs/<name>/build.lock` and `tools.lock`, the exact packages conda
chose, which later setups install: commit them with `env.yaml`.

```bash
make setup-env ENV=jax-power9   # conda (Miniforge) needed; BAZEL_BINARY=<file> uses a Bazel already compiled
make check-env ENV=jax-power9   # load it as a build does and show what it provides
```

Builds load the environment with `scripts/script_worker/env.sh`, which only
exports variables: PATH, the C++ runtime of its compilers (LD_LIBRARY_PATH),
`PYTHON`, `TEST_PYTHON`, `CLANG`, `BAZEL`, `JAVA_HOME`, `LOCAL_WHEELS`
(`envs/<name>.sh` replaces it for an environment that needs more).
`env.json` records its versions and checksums, and every result its id.

The builds, acceptance tests and `run_command_tool` commands of build-recipe
cases run in containers of the environment's image, which `make setup-env`
builds from `envs/Containerfile` (the system part of the build host: glibc,
headers, binutils; `envs/<name>/Containerfile` replaces it) as
`build-bench-<name>`. Only what is mounted is
there, at the same paths as on the host: the build copy, its caches and the
build environment. The default runtime, `auto`, is Podman when it is
installed (rootless, no daemon: `dnf install podman` or `apt install podman`
on the build host) and Docker otherwise; the config can name one
(`build.container`, or `BENCH_CONTAINER_RUNTIME`):

```yaml
build:
  container:
    runtime: auto          # auto (default), podman, docker, or none (on the host)
    build_network: log     # log (default): any host, every connection logged; host or none
    # cpus: 32, memory: 64g, pids_limit: 4096   (default -1: no limit beyond the host's)
```

With Docker the containers run as the user, but its group is
root-equivalent; with `none` build.sh runs on the host with everything the
user can read, and `run_command_tool` uses a sandbox of Linux namespaces that
needs root. The image's base is pinned by digest; `env.json` records the
image and its packages (`image-packages.txt`), and every result the id of
the image it ran with.

**The build's network.** A build container has no network of its own: with
`build_network: log` (the default) it reaches any host through a proxy of
the framework on a socket mounted into it (`tools/auto_repair/net_proxy.py`;
the build sees it as `http_proxy`/`https_proxy`, which Bazel, pip, git and
curl use). Nothing is blocked, so a case needs no list of hosts and any
package can run; the proxy logs every connection to
`<stage>/<package>/run/network.log`, and each result records the hosts its
builds reached (`network`). For HTTPS it sees the host, not the path.
`host` gives builds the host's network directly (nothing logged), `none` no
network.

Build backends of RPM packages (`build.backend` in `bench.yaml`):
- **OBS** (`obs`): the OBS account above; `dataset/setup_obs.py` creates the packages in your OBS project.
- **local** (`local`): `osc build` in a local openSUSE chroot, created by `scripts/local_worker/setup.sh`, against the openSUSE:Factory port of the target architecture (`build.local.project` names another).

Cases with a `build.sh` (build recipes) are built with either: in a container
of their environment's image, in their build environment.

---

## 🚀 Running the Framework

### With make
Everything a run uses is set in `bench.yaml`, the config (see Config
below); the settings of the run can be overridden on the command line. The
commands run on the build host.

| `bench.yaml` | make variable | |
|---|---|---|
| `label`, `repeats` | `LABEL`, `REPEATS` | runs are archived as `<label>_1` … `<label>_<repeats>` |
| `packages` | `PACKAGES` | cases to run (empty: all of `data/<source>_to_<target>/`) |
| `model`, `provider` | `MODEL`, `PROVIDER` | model and pinned OpenRouter provider |
| `llm.max_build_attempts` | `ATTEMPTS` | build attempts per package |
| `temperature` | `TEMPERATURE` | sampling temperature |
| `base_url`, `api_key_env`, `llm.max_context_chars` | `BASE_URL`, `API_KEY_ENV`, `CONTEXT_CHARS` | a model server of your own (see Local models) |
| | `CONFIG` | another config file, e.g. a copy of `bench.yaml` |

```bash
make                      # list the commands
make run                  # start the config's run in the background
make run LABEL=run31 ATTEMPTS=6 MODEL=deepseek/deepseek-v4.1-flash
make status               # the dashboard, once
make watch                # the live dashboard (Ctrl-C stops watching only)
make stop                 # stop the run, its builds and experiments; archive it as <run>_stopped
make resume FROM=run29_v41flash_scratch_12att_1 ATTEMPTS=3
make summary              # archived runs, results and total cost (KEY=1: API key usage)
make transcript RUN=run29_v41flash_scratch_12att_1 [ATTEMPT=6 REASONING=1 TOOL=... GREP=...]
make leaks                # look for the answer within the model's reach
make new-case CASE=<name> SOURCE=<url of an archive> [ENV=<environment>]
make fetch CASE=<name>    # the sources of a case again, e.g. after a clone
make baseline CASE=<name> # the original failure of a case: log_failed.txt
make check-case CASE=<name>
make new-env ENV=<name>   # a build environment from envs/env.example.yaml
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
`logs/<label>.log`. A run reads a copy of `bench.yaml` taken when it starts
(kept with its logs as `config.yaml`): the file can be edited for the next
run in the meantime.

### Local models
Any server with an OpenAI-compatible API works: Ollama, vLLM, llama.cpp's
`llama-server`. Start it with tool calling and a large context window, then
set `base_url`, `model` and `llm.max_context_chars` in `bench.yaml`, or run
with the variables:

```bash
OLLAMA_CONTEXT_LENGTH=65536 ollama serve &      # Ollama's default window is small and cuts prompts silently
ollama pull qwen3-coder:30b
make run BASE_URL=http://127.0.0.1:11434/v1 MODEL=qwen3-coder:30b PROVIDER=none CONTEXT_CHARS=180000 LABEL=local1
```

vLLM: `vllm serve <model> --max-model-len 65536 --enable-auto-tool-choice
--tool-call-parser <parser>`; llama.cpp: `llama-server -m <model.gguf> --jinja
-c 65536`. `base_url` points the run to the server; the API key of `.env` is
never sent there (`api_key_env` names a variable with the server's own key,
if it needs one). `llm.max_context_chars` (`CONTEXT_CHARS`) keeps the
conversation within the server's window, at about 3.5 characters per token
(65,536 tokens: about 180,000 characters, leaving room for the system prompt
and the reply); the oldest tool results are shortened beyond it. `make run` checks that the
server answers and serves the model before starting; `LLM_TIMEOUT` (or
`llm.request_timeout`) gives slow models more time per reply. Results record
the server in `run.api_base` and `run.local_model`; their cost is $0.

When the server's tool parser does not know the model's format, the tool
calls arrive as text; the client takes them from the text (Hermes/Qwen,
Qwen3-Coder, GLM, Mistral, Llama, DeepSeek and gpt-oss formats, or a reply
that is only JSON calls) and counts them in `usage.text_tool_calls`
(`llm.text_tool_calls: false` or `BENCH_TEXT_TOOL_CALLS=0` turns this off).

### Prompt caching
Claude models cache a conversation's prefix only up to the breakpoints a
request marks; the client marks them (the system prompt and the latest
inputs) for `anthropic/` and `claude` models, so each round reads the
conversation so far from the cache at a tenth of the price. DeepSeek, OpenAI
and Gemini models cache by themselves. `llm.prompt_cache` (or
`BENCH_PROMPT_CACHE`): `auto` (default), `on` (every model), `off`. Results
count `cached_tokens` and `cache_write_tokens`.

### Directly
```bash
BENCH_PACKAGES=jaxlib BENCH_MAX_ATTEMPTS=12 python client.py
scripts/run_repeats.sh <label> <n> [config]   # n runs, each archived in its own directory
```
`client.py` reads `bench.yaml` (`BENCH_CONFIG` names another file) and
these settings of the environment: `BENCH_PACKAGES` (comma-separated),
`BENCH_MAX_ATTEMPTS`, `LLM_MODEL`, `OPENROUTER_PROVIDER`, `LLM_TEMPERATURE`,
`BENCH_RESUME_FROM` and `BENCH_RESUME_WORKSPACE` (continue a run),
`BENCH_BUILD_BACKEND`, `BENCH_FINAL_NEWLINE`. The Patch Generation strategy
of the original (`client_patch.py`) takes its paths from `bench.yaml` but has
none of the other changes.

---

## 🗂️ Config

One file, `bench.yaml`, holds everything a run uses: the source and target
architectures, the cases to run, the model, the options of the repair loop
and the builds. Each setting has a comment there. What the file does not
choose follows from the two architectures:

| | |
|---|---|
| cases | `data/<source_arch>_to_<target_arch>/<package>/` (`cases_dir` moves them) |
| acceptance tests | `acceptance/<source_arch>_to_<target_arch>/<package>.sh` |
| results and logs | `result_text_res/<source_arch>_to_<target_arch>/<run>/`, `result_log_res/…/<run>/` |
| workspaces | `temp_workspace/<package>/` |
| OBS repository and architecture | the target architecture (`obs.repository`, `obs.project` and `obs.api_url` override them) |
| local builds | against the openSUSE:Factory port of the target architecture (`build.local.project`) |

The other direction is `source_arch: ppc64le` and `target_arch: x86_64`; the
original's case study is `target_arch: aarch64` with
`cases_dir: data/case_study/x86_succeed_pro` and `obs: {repository: arm}`.

**What the framework tells the model** during a repair, besides the build
results (none of it hints at a fix; 0 or `false` turns it off):

| `llm.` | |
|---|---|
| `carry_notes_chars` | the next attempt starts with what the model wrote in the previous one (its notes), up to this many characters: what it found out is not lost when it made no edit |
| `round_notice_at` | when these many rounds are left in an attempt, so it applies its fix in time |
| `build_drought_rounds` | after this many rounds without a change or a build, to build its hypothesis |
| `repeated_failure_note` | when a build failed the same way as the previous one: the change since then did not affect the failure |

The paper's setup is `max_build_attempts: 3`, `max_tool_rounds: 20`, no
`extra_tools`, and all four off; a run without the notes (an ablation) is
`carry_notes_chars: 0`.

---

## 📦 Cases

A case is a directory `data/<direction>/<package>/` that is copied into the
model's workspace at the start of a run:

- **RPM package** (a `.spec`): sources and patches from openSUSE, `log_failed.txt` from OBS and `manifest.json` with their origin. `python dataset/fetch_package.py <package> x86_64_to_ppc64le` fetches one; `dataset/find_candidates.py` lists packages that build on x86_64 and fail on ppc64le.
- **Build recipe** (a `build.sh`, no `.spec`): the sources, `build.sh`, `manifest.json` naming its build environment (`envs/<environment>/env.yaml`, which the model cannot change) and `log_failed.txt`, the original failure.

A build-recipe case takes four commands:

```bash
make new-case CASE=zlib SOURCE=https://www.zlib.net/zlib-1.3.1.tar.xz
make setup-env ENV=zlib        # once per environment
make baseline CASE=zlib        # builds it as it is: log_failed.txt
make check-case CASE=zlib
```

`make new-case` downloads and unpacks the sources (archives: `.tar.gz`,
`.tar.xz`, `.tar.bz2`, `.zip`; on GitHub `.../archive/refs/tags/<tag>.tar.gz`
or `.../archive/<commit>.tar.gz`), records them in `manifest.json` and in the
case's `.gitignore` (`make fetch` downloads them again), and writes for the
build system it finds (Bazel, Python, CMake, Meson, autotools, Cargo, Go,
make) a `build.sh`, an acceptance test and, unless `ENV=` names an environment
that exists, an `envs/<case>/env.yaml` with that build system's packages.
Adjust `build.sh` to the build as upstream runs it on the source architecture,
and the test to what the package must do. More than one source:
`SOURCE="<url> <dir>=<url>"`; the first is the one `build.sh` builds.

**Acceptance tests** (`acceptance/<direction>/<package>.sh`) run after every
successful build; a build only counts when its test passes. The model can
read them, not change them. jaxlib's installs the wheel in a clean Python and
runs numerical checks and 1528 tests of JAX's own suite.

A case needs no known fix: the framework tries any package. `make
check-case` checks a case before its first run, and the leak check refuses a
run when a built or installed copy of the package is within the model's
reach.

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

The framework also keeps attempts moving, with notes that do not hint at a
fix: after `llm.build_drought_rounds` rounds without a change or a build it
tells the model to build its hypothesis, and when a build fails the same way
as the previous one (`llm.repeated_failure_note`) it says that the changes
since then did not affect the failure.

---

## 📈 Results

For every run, `result_text_res/<source>_to_<target>/<run>/` holds
`<package>_result.json` (success, attempt, cost, tokens, timing, one summary
per attempt, the run's git commit and settings, leak check findings) and
`result_log_res/<source>_to_<target>/<run>/` the log, the conversation of
every attempt (`<package>_attempt<N>_messages.json`, with the model's
reasoning), the diff log of its edits and `config.yaml`, the copy of
`bench.yaml` the run used. `make summary` and
`make transcript` read them. They stay on the machine that ran the benchmark:
git ignores both directories.

---

## 🧪 Tests

`make test` runs `tests/test_helpers.py` (patch check, log excerpt, build
backends, resume, run settings, config, leak check, cases, sandbox, containers with
Podman or Docker when one is installed with the base image, the build's
network proxy, tool calls written as text) and
`tests/test_offline.py` (the tools through MCP with a scripted model). They
write only to temporary directories.

---

## 📂 Directory Structure

```
.
├── bench.yaml, Makefile          # the config and the commands
├── client.py, server.py          # MCP client (repair loop) and server (tools)
├── prompts/                      # system prompts (RPM cases, build recipes)
├── tools/auto_repair/            # build backends, acceptance tests, sandbox, leak check, log excerpt
├── data/<direction>/<package>/   # cases
├── acceptance/<direction>/       # acceptance tests
├── envs/                         # build environments of build-recipe cases
├── dataset/                      # fetching, baselines, case tools
├── scripts/                      # bench.py, run_repeats.sh, watch_run.py, transcript.py, workers
├── tests/
├── result_text_res/, result_log_res/   # runs, per direction (<source>_to_<target>/<run>/)
└── MODIFICATIONS.md              # every change relative to the original
```

## 📊 Data and Case Study

The folder data/case_study/ provides example build results (e.g., x86→ARM full repair) used in Section 5 of the paper for qualitative analysis.
