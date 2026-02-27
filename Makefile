.PHONY: dist-agent build-frontend dev-frontend clean help
# Local targets (sync-db, deploy, etc.) live in local.mk — see bottom of this file

help: ## Show available targets
	@grep -h '^[a-zA-Z_-]*:.*## ' Makefile local.mk 2>/dev/null | \
		sed 's/:.*## /\t/' | sort | \
		awk -F'\t' '{printf "  %-20s %s\n", $$1, $$2}'

build-frontend: ## Build the React UI (outputs to frontend/dist/)
	cd frontend && npm install && npm run build

dev-frontend: ## Start Vite dev server (proxies API to :8765)
	cd frontend && npm install && npm run dev

dist-agent: ## Build standalone sift binary for Linux x86_64 (Unraid)
	mkdir -p dist
	docker run --rm --platform linux/amd64 \
		-v "$(CURDIR):/src" \
		-w /src \
		python:3.11-bullseye \
		bash -c "apt-get update -qq && apt-get install -qq -y binutils > /dev/null && pip install --quiet pyinstaller requests && pip install --quiet --no-deps -e . && pyinstaller --onefile --clean --distpath /src/dist --specpath /tmp --name sift-linux-amd64 sift/__main__.py"
	@echo "Built: dist/sift-linux-amd64"

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.spec

# Host-specific / private targets go in local.mk (gitignored, never committed).
# Create your own local.mk to extend this Makefile without touching the public repo.
sinclude local.mk
