# Commands of the benchmark. Everything a run uses is set in bench.yaml (the
# config); the settings of the run can be overridden here, e.g.
#   make run LABEL=run31 ATTEMPTS=6 MODEL=deepseek/deepseek-v4.1-flash
# A variable set to none clears that setting of the config, e.g. PROVIDER=none.
# ALLOW_LEAKS=1 starts a run even if the leak check finds something.
# A local model: make run BASE_URL=http://127.0.0.1:11434/v1 MODEL=... (or set them in the config)
# CONFIG=<file> uses another config file (e.g. a copy of bench.yaml).
# `make` alone lists the commands. They run on the build host (the Power9).

# settings of this machine (e.g. PY=/path/to/python, BENCH_HOME=...), not in git
-include local.mk
PY ?= python3
export BENCH_HOME
CONFIG ?= bench.yaml

# overrides of the config, passed only when set
OPTS = $(if $(LABEL),--label $(LABEL)) \
       $(if $(PACKAGES),--packages "$(PACKAGES)") $(if $(MODEL),--model $(MODEL)) \
       $(if $(PROVIDER),--provider $(PROVIDER)) $(if $(ATTEMPTS),--attempts $(ATTEMPTS)) \
       $(if $(REPEATS),--repeats $(REPEATS)) $(if $(TEMPERATURE),--temperature $(TEMPERATURE)) \
       $(if $(BASE_URL),--base_url $(BASE_URL)) $(if $(API_KEY_ENV),--api_key_env $(API_KEY_ENV)) \
       $(if $(CONTEXT_CHARS),--context_chars $(CONTEXT_CHARS))
BENCH = $(PY) scripts/bench.py --config $(CONFIG) $(OPTS)
LEAKS = $(if $(ALLOW_LEAKS),--allow-leaks)

.DEFAULT_GOAL := help
.PHONY: help run run-fg resume stop status watch summary leaks check-case new-case transcript setup-env check-env archive test

help: ## list the commands
	@echo "usage: make <command> [LABEL=... PACKAGES=... MODEL=... PROVIDER=... ATTEMPTS=... REPEATS=... CONFIG=...]"
	@echo "settings come from $(CONFIG); variables override them"
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-11s %s\n", $$1, $$2}'

run: ## start a run in the background (one at a time; checks for leaks first)
	@$(BENCH) run --bg $(LEAKS)

run-fg: ## run in the foreground (Ctrl-C stops it)
	@$(BENCH) run $(LEAKS)

resume: ## continue run FROM=<run> with ATTEMPTS more attempts (WORKSPACE=<copy> optional)
	@test -n "$(FROM)" -a -n "$(ATTEMPTS)" || { echo "usage: make resume FROM=<archived run> ATTEMPTS=<n> [LABEL=...] [WORKSPACE=...]"; exit 2; }
	@$(BENCH) resume $(FROM) --bg $(if $(WORKSPACE),--workspace $(WORKSPACE)) $(LEAKS)

stop: ## stop the active run and its builds, archive what it left as <run>_stopped
	@$(BENCH) stop

status: ## the active run and its current package
	@$(BENCH) status

watch: ## the same view, refreshed (Ctrl-C stops watching, not the run)
	@$(BENCH) watch

summary: ## archived runs with results and total cost (PREFIX=run29 filters, KEY=1 adds the API key's usage)
	@$(BENCH) summary $(PREFIX) $(if $(KEY),--key)

leaks: ## look for the answer within the model's reach (built copies, reference fixes)
	@$(BENCH) leaks

check-case: ## check that case CASE=<name> is ready to run (files, environment, log, test, leaks)
	@test -n "$(CASE)" || { echo "usage: make check-case CASE=<name>"; exit 2; }
	@$(BENCH) check-case $(CASE)

new-case: ## start build-recipe case CASE=<name> from a template (ENV=<environment> optional)
	@test -n "$(CASE)" || { echo "usage: make new-case CASE=<name> [ENV=<environment>]"; exit 2; }
	@$(BENCH) new-case $(CASE) --env "$(ENV)"

transcript: ## what the model did in RUN=<run|current>: overview, or ATTEMPT=n (REASONING=1 FULL=1 TOOL=... GREP=...)
	@test -n "$(RUN)" || { echo "usage: make transcript RUN=<archived run|current> [PACKAGE=...] [ATTEMPT=n] [REASONING=1] [FULL=1] [TOOL=name] [GREP=regex]"; exit 2; }
	@$(BENCH) transcript $(RUN) $(if $(PACKAGE),--package $(PACKAGE)) $(if $(ATTEMPT),--attempt $(ATTEMPT)) \
	    $(if $(REASONING),--reasoning) $(if $(FULL),--full) $(if $(TOOL),--tool $(TOOL)) $(if $(GREP),--grep '$(GREP)')

setup-env: ## make build environment ENV=<name> once, in BENCH_HOME/envs (BAZEL_BINARY=, WHEELS_FROM= reuse builds)
	@test -n "$(ENV)" || { echo "usage: make setup-env ENV=<name> [BAZEL_BINARY=<file>] [WHEELS_FROM=<dir>]"; exit 2; }
	@BAZEL_BINARY="$(BAZEL_BINARY)" WHEELS_FROM="$(WHEELS_FROM)" $(BENCH) setup-env $(ENV)

check-env: ## load build environment ENV=<name> as a build does and show what it provides
	@test -n "$(ENV)" || { echo "usage: make check-env ENV=<name>"; exit 2; }
	@$(BENCH) check-env $(ENV)

archive: ## move the files an interrupted run left into NAME=<run>_stopped
	@test -n "$(NAME)" || { echo "usage: make archive NAME=<run>_stopped"; exit 2; }
	@$(BENCH) archive $(NAME)

test: ## run the tests
	$(PY) tests/test_helpers.py
	$(PY) tests/test_offline.py
