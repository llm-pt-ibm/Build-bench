# Commands of the benchmark (`make` lists them), run on the build host. A run
# reads bench.yaml; variables override it, e.g.
#   make run LABEL=run31 ATTEMPTS=6 MODEL=deepseek/deepseek-v4.1-flash
# and none clears a setting (PROVIDER=none). CONFIG=<file> reads another config.

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
.PHONY: help run run-fg resume stop status watch summary leaks check-case new-case fetch baseline transcript new-env setup-env check-env archive test

help: ## list the commands
	@echo "usage: make <command> [LABEL=... PACKAGES=... MODEL=... PROVIDER=... ATTEMPTS=... REPEATS=... CONFIG=...]"
	@echo "settings come from $(CONFIG); variables override them"
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-11s %s\n", $$1, $$2}'

run: ## start a run in the background (one at a time; checks for leaks first, ALLOW_LEAKS=1 skips that)
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

leaks: ## look for the answer within the model's reach (built or installed copies of the package)
	@$(BENCH) leaks

check-case: ## check that case CASE=<name> is ready to run (files, environment, log, test, leaks)
	@test -n "$(CASE)" || { echo "usage: make check-case CASE=<name>"; exit 2; }
	@$(BENCH) check-case $(CASE)

new-case: ## start build-recipe case CASE=<name>: SOURCE="<url> ..." downloads its sources, ENV=<environment> (default: a new one)
	@test -n "$(CASE)" || { echo "usage: make new-case CASE=<name> [SOURCE=\"<url of an archive> ...\"] [ENV=<environment>]"; exit 2; }
	@$(BENCH) new-case $(CASE) --env "$(ENV)" $(foreach s,$(SOURCE),--source '$(s)')

fetch: ## download the sources of case CASE=<name> again (manifest.json), e.g. after a clone
	@test -n "$(CASE)" || { echo "usage: make fetch CASE=<name>"; exit 2; }
	@$(BENCH) fetch $(CASE)

baseline: ## build case CASE=<name> as it is, without the model, and save the failure as its log_failed.txt
	@test -n "$(CASE)" || { echo "usage: make baseline CASE=<name>"; exit 2; }
	@$(BENCH) baseline $(CASE)

transcript: ## what the model did in RUN=<run|current>: overview, or ATTEMPT=n (REASONING=1 FULL=1 TOOL=... GREP=...)
	@test -n "$(RUN)" || { echo "usage: make transcript RUN=<archived run|current> [PACKAGE=...] [ATTEMPT=n] [REASONING=1] [FULL=1] [TOOL=name] [GREP=regex]"; exit 2; }
	@$(BENCH) transcript $(RUN) $(if $(PACKAGE),--package $(PACKAGE)) $(if $(ATTEMPT),--attempt $(ATTEMPT)) \
	    $(if $(REASONING),--reasoning) $(if $(FULL),--full) $(if $(TOOL),--tool $(TOOL)) $(if $(GREP),--grep '$(GREP)')

new-env: ## start build environment ENV=<name> from the example (envs/env.example.yaml)
	@test -n "$(ENV)" || { echo "usage: make new-env ENV=<name>"; exit 2; }
	@$(BENCH) new-env $(ENV)

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
