.PHONY: dist-agent build-frontend dev-frontend clean help \
	test-fast test-unit test-server test-integration-live smoke-local verify-local soak-local test-e2e
# Local targets (sync-db, deploy, etc.) live in local.mk — see bottom of this file

help: ## Show available targets
	@grep -h '^[a-zA-Z_-]*:.*## ' Makefile local.mk 2>/dev/null | \
		sed 's/:.*## /\t/' | sort | \
		awk -F'\t' '{printf "  %-20s %s\n", $$1, $$2}'

build-frontend: ## Build the React UI (outputs to frontend/dist/)
	cd frontend && npm install && npm run build

dev-frontend: ## Start Vite dev server (proxies API to :8765)
	cd frontend && npm install && npm run dev

test-fast: ## Run fast local tests (unit + server, excludes integration/e2e/perf/soak)
	pytest tests/unit tests/server -q

test-unit: ## Run unit tests only
	pytest tests/unit -q

test-server: ## Run server API tests only
	pytest tests/server -q

test-integration-live: ## Run live integration tests (requires SIFT_TEST_SERVER)
	@if [ -z "$$SIFT_TEST_SERVER" ]; then \
		echo "SIFT_TEST_SERVER is required, e.g. SIFT_TEST_SERVER=http://host:8765"; \
		exit 1; \
	fi
	pytest -o addopts='' -m integration tests/integration -q

smoke-local: ## Run quick smoke checks (server-side)
	pytest -m smoke tests/server/test_smoke.py -q

verify-local: ## Fast local verification before deploy (tests + frontend build)
	pytest tests/unit tests/server -q
	cd frontend && npm run build

soak-local: ## Run long soak/perf tests (manual usage only)
	pytest -o addopts='' -m "soak or perf" -q

test-e2e: ## Run Playwright e2e tests (requires sift server + make dev-frontend)
	cd frontend && npx playwright test

dist-agent: ## Build standalone sift binary for Linux x86_64 (Unraid)
	mkdir -p dist
	docker run --rm --platform linux/amd64 \
		-v "$(CURDIR):/src" \
		-w /src \
		python:3.11-bullseye \
		bash -c "apt-get update -qq && apt-get install -qq -y binutils > /dev/null && pip install --quiet pyinstaller requests charset-normalizer chardet && pip install --quiet --no-deps -e . && pyinstaller --onefile --clean --distpath /src/dist --specpath /tmp --name sift-linux-amd64 --collect-all charset_normalizer --collect-all chardet sift/__main__.py"
	@echo "Built: dist/sift-linux-amd64"

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.spec

# Host-specific / private targets go in local.mk (gitignored, never committed).
# Create your own local.mk to extend this Makefile without touching the public repo.
sinclude local.mk
