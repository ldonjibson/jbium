# ═══════════════════════════════════════════════════════════
# Jbium — Makefile
# ═══════════════════════════════════════════════════════════
# Usage: make <target>
# Run 'make help' to see all targets
# ═══════════════════════════════════════════════════════════

.DEFAULT_GOAL := help

# ─── Variables ────────────────────────────────────────────
PYTHON  := python3
PIP     := $(PYTHON) -m pip
PLATFORM := $(shell uname -s | tr A-Z a-z)
ifeq ($(PLATFORM),darwin)
	PLATFORM := macos
endif

CHROMIUM_DIR ?= $(HOME)/jbium/chromium
BUILD_DIR    := $(CHROMIUM_DIR)/src/out/Release

.PHONY: help setup fonts geoip patches build test clean dist

# ─── Help ─────────────────────────────────────────────────
help: ## Show this help
	@echo "Jbium"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─── Setup ─────────────────────────────────────────────────
setup: ## Full setup (deps + source + patches)
	@echo "Running full setup..."
	bash scripts/setup.sh

setup-deps: ## Install system dependencies only
	@echo "Installing dependencies..."
	sudo apt-get update && sudo apt-get install -y \
		build-essential cmake ninja-build \
		clang lld llvm \
		python3 python3-pip \
		git curl wget

setup-python: ## Install Python dependencies
	$(PIP) install -r requirements.txt

setup-source: ## Fetch Chromium source (30+ min)
	@echo "Fetching Chromium source..."
	mkdir -p $(CHROMIUM_DIR) && cd $(CHROMIUM_DIR)
	fetch --no-history --nohooks chromium
	cd src && gclient runhooks

# ─── Fonts ────────────────────────────────────────────────
fonts: ## Download all font bundles
	$(PYTHON) fonts/download_fonts.py --all

fonts-linux: ## Download Linux fonts only
	$(PYTHON) fonts/download_fonts.py --platform linux

fonts-verify: ## Verify downloaded fonts
	$(PYTHON) fonts/download_fonts.py --verify

# ─── GeoIP ────────────────────────────────────────────────
geoip: ## Download GeoIP database
	@echo "Downloading GeoLite2 database..."
	bash scripts/download_geoip.sh

# ─── Patches ───────────────────────────────────────────────
patches: ## Apply all stealth patches
	bash patches/apply_all.sh

patches-validate: ## Validate patches applied cleanly
	bash scripts/validate_patches.sh

# ─── Build ────────────────────────────────────────────────
build: ## Build Chromium (incremental)
	@echo "Building..."
	ninja -C $(BUILD_DIR) chrome -j$$(nproc)

build-clean: ## Clean build
	rm -rf $(BUILD_DIR)
	ninja -C $(BUILD_DIR) chrome -j$$(nproc)

build-full: setup patches build ## Full build from scratch

# ─── Test ─────────────────────────────────────────────────
test: ## Run all tests
	$(PYTHON) -m pytest tests/ -v

test-stealth: ## Run stealth detection tests
	$(PYTHON) scripts/test_stealth.py

test-consistency: ## Run fingerprint consistency tests
	$(PYTHON) tests/test_consistency.py

test-quick: ## Quick check against bot.sannysoft.com
	$(PYTHON) scripts/quick_check.py

# ─── Package ──────────────────────────────────────────────
dist: ## Create distributable packages
	$(PYTHON) scripts/package_all.py --output dist/

dist-upload: ## Package and upload to S3
	$(PYTHON) scripts/package_all.py --output dist/
	$(PYTHON) scripts/upload_s3.py

# ─── Clean ────────────────────────────────────────────────
clean: ## Clean build artifacts
	rm -rf $(BUILD_DIR)/obj
	rm -rf $(BUILD_DIR)/gen
	rm -rf dist/
	rm -rf build/
	rm -rf __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
	find . -type f -name "*.pyc" -delete 2>/dev/null

clean-all: clean ## Clean EVERYTHING (careful!)
	rm -rf $(CHROMIUM_DIR)
	rm -rf fonts/.downloads/
	rm -rf test_results/

# ─── Development ──────────────────────────────────────────
dev-install: ## Install in development mode
	$(PIP) install -e .

lint: ## Run linter
	$(PYTHON) -m ruff check driver/ scripts/ tests/

format: ## Format code
	$(PYTHON) -m black driver/ scripts/ tests/ launcher/

# ─── CI ────────────────────────────────────────────────────
ci-test: ## Run CI test suite
	$(PYTHON) -m pytest tests/ -v --cov=driver --cov-report=term

# ═══════════════════════════════════════════════════════════
