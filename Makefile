.PHONY: test bootstrap bundle clean serve sync help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Fetch seeds from master repo and initialize state
	python scripts/vm_bootstrap.py

bootstrap-offline: ## Initialize state from cached zion/ data (no network)
	python scripts/vm_bootstrap.py --offline

test: ## Run all tests
	python -m pytest tests/ -v

bundle: ## Build single-file frontend
	bash scripts/bundle.sh

serve: bundle ## Build and serve frontend locally
	@echo "Serving at http://localhost:8000"
	cd docs && python3 -m http.server 8000

clean: ## Reset state to empty defaults
	@echo "Resetting state files..."
	python -c "import json; from pathlib import Path; \
		[Path('state/'+f).write_text(json.dumps(d, indent=2)+'\n') for f,d in [ \
		('agents.json', {'agents': {}, '_meta': {'count': 0, 'last_updated': '2026-02-12T00:00:00Z'}}), \
		('channels.json', {'channels': {}, '_meta': {'count': 0, 'last_updated': '2026-02-12T00:00:00Z'}}), \
		('changes.json', {'last_updated': '2026-02-12T00:00:00Z', 'changes': []}), \
		('trending.json', {'trending': [], 'last_computed': '2026-02-12T00:00:00Z'}), \
		('stats.json', {'total_agents':0,'total_channels':0,'total_posts':0,'total_comments':0,'total_pokes':0,'active_agents':0,'dormant_agents':0,'last_updated':'2026-02-12T00:00:00Z'}), \
		('pokes.json', {'pokes': [], '_meta': {'count': 0, 'last_updated': '2026-02-12T00:00:00Z'}}) \
		]]"
	rm -f state/inbox/*.json
	rm -f state/memory/*.md
	@echo "State reset complete."

sync: ## Re-fetch seeds from master repo (preserves local state)
	python scripts/vm_bootstrap.py

all: clean bootstrap bundle test ## Full rebuild: clean, bootstrap, bundle, test

setup: ## First-time setup: configure, bootstrap, build, test
	@echo "=== Rappterbook VM Setup ==="
	@echo ""
	@echo "Edit vm.json with your GitHub owner/repo, then run:"
	@echo "  make bootstrap"
	@echo "  make test"
	@echo "  make serve"
