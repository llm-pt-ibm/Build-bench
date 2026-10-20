# Commands of the benchmark. What to run is set in bench.yaml (the run
# profile); each setting can be overridden here, e.g.
#   make run LABEL=run31 ATTEMPTS=6 MODEL=deepseek/deepseek-v4.1-flash
# ALLOW_LEAKS=1 starts a run even if the leak check finds something.
# `make` alone lists the commands. They run on the build host (the Power9).

PY ?= $(shell [ -x /root/miniforge3/envs/build_bench/bin/python ] && echo /root/miniforge3/envs/build_bench/bin/python || echo python3)
PROFILE ?= bench.yaml

# profile overrides, passed only when set
OPTS = $(if $(CONFIG),--config $(CONFIG)) $(if $(LABEL),--label $(LABEL)) \
       $(if $(PACKAGES),--packages "$(PACKAGES)") $(if $(MODEL),--model $(MODEL)) \
       $(if $(PROVIDER),--provider $(PROVIDER)) $(if $(ATTEMPTS),--attempts $(ATTEMPTS)) \
       $(if $(REPEATS),--repeats $(REPEATS)) $(if $(TEMPERATURE),--temperature $(TEMPERATURE))
BENCH = $(PY) scripts/bench.py --profile $(PROFILE) $(OPTS)
LEAKS = $(if $(ALLOW_LEAKS),--allow-leaks)

.DEFAULT_GOAL := help
.PHONY: help run run-fg resume stop status watch summary leaks archive test

help: ## list the commands
	@echo "usage: make <command> [LABEL=... PACKAGES=... MODEL=... PROVIDER=... ATTEMPTS=... REPEATS=... CONFIG=...]"
	@echo "settings come from $(PROFILE); variables override them"
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-9s %s\n", $$1, $$2}'

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

archive: ## move the files an interrupted run left into NAME=<run>_stopped
	@test -n "$(NAME)" || { echo "usage: make archive NAME=<run>_stopped"; exit 2; }
	@$(BENCH) archive $(NAME)

test: ## run the tests
	$(PY) tests/test_helpers.py
	$(PY) tests/test_offline.py
