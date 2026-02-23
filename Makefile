.PHONY: dist-agent build-frontend dev-frontend clean help

help:
	@echo "Targets:"
	@echo "  build-frontend   Build the React UI (outputs to frontend/dist/)"
	@echo "  dev-frontend     Start Vite dev server (proxies API to :8765)"
	@echo "  dist-agent       Build standalone sift binary for Linux x86_64 (Unraid)"
	@echo "  clean            Remove build artifacts"

build-frontend:
	cd frontend && npm install && npm run build

dev-frontend:
	cd frontend && npm install && npm run dev

dist-agent:
	mkdir -p dist
	docker run --rm --platform linux/amd64 \
		-v "$(CURDIR):/src" \
		-w /src \
		python:3.11-bullseye \
		bash -c "apt-get update -qq && apt-get install -qq -y binutils > /dev/null && pip install --quiet pyinstaller requests && pip install --quiet --no-deps -e . && pyinstaller --onefile --clean --distpath /src/dist --specpath /tmp --name sift-linux-amd64 sift/__main__.py"
	@echo "Built: dist/sift-linux-amd64"

clean:
	rm -rf dist/ build/ *.spec
