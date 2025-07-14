# Floodmap Testing Makefile
.PHONY: help test-setup test-unit test-integration test-e2e test-visual test-all test-cleanup dev-loop

# Default target
help:
	@echo "Floodmap Testing Commands:"
	@echo "  make dev-loop      - Fast development testing loop (unit + integration)"
	@echo "  make test-unit     - Run unit tests only (~30s)"
	@echo "  make test-integration - Run integration tests (~2min)"
	@echo "  make test-e2e      - Run E2E tests (~3min)"
	@echo "  make test-visual   - Run visual regression tests"
	@echo "  make test-all      - Run complete test suite (~10min)"
	@echo "  make test-setup    - Start services for testing"
	@echo "  make test-cleanup  - Stop all test services"
	@echo "  make test-docker   - Run tests using Docker Compose"
	@echo "  make fix-maplibre  - Debug and fix MapLibre tile loading"

# Fast development loop - what you run most often
dev-loop:
	@echo "🚀 Running fast development test loop..."
	uv run pytest tests/unit/ tests/integration/ -v --tb=short -x --maxfail=3

# Unit tests - fastest feedback
test-unit:
	@echo "🧪 Running unit tests..."
	uv run pytest tests/unit/ -v --tb=short

# Integration tests - API endpoints, tile serving
test-integration: test-setup-check
	@echo "🔗 Running integration tests..."
	uv run pytest tests/integration/ -v --tb=short

# E2E tests - full browser automation
test-e2e: test-setup-check
	@echo "🌐 Running E2E tests..."
	uv run pytest tests/e2e/ -v --tb=short --html=test_report.html

# Visual regression tests
test-visual: test-setup-check
	@echo "👁️  Running visual regression tests..."
	uv run pytest tests/visual/ -v --tb=short

# Performance tests
test-performance: test-setup-check
	@echo "⚡ Running performance tests..."
	uv run pytest tests/performance/ -v --tb=short

# Complete test suite
test-all: test-setup
	@echo "🎯 Running complete test suite..."
	uv run pytest tests/ -v --html=test_report.html --self-contained-html
	@echo "📊 Test report available at: test_report.html"

# Docker-based testing (most reliable)
test-docker:
	@echo "🐳 Running tests with Docker Compose..."
	docker-compose -f docker-compose.test.yml up --build --abort-on-container-exit
	docker-compose -f docker-compose.test.yml down

# Service management for local testing
test-setup:
	@echo "🛠️  Starting test services..."
	# Kill any existing services
	-pkill -f "tileserver"
	-pkill -f "main.py"
	# Start tileserver
	./start_tileserver.sh &
	echo $$! > .tileserver.pid
	@echo "⏳ Waiting for tileserver to be ready..."
	@timeout=30; while [ $$timeout -gt 0 ] && ! curl -s http://localhost:8080 > /dev/null; do sleep 1; timeout=$$((timeout-1)); done
	# Start Flask app in test mode
	DEBUG_MODE=true uv run python main.py &
	echo $$! > .app.pid
	@echo "⏳ Waiting for Flask app to be ready..."
	@timeout=30; while [ $$timeout -gt 0 ] && ! curl -s http://localhost:5001/healthz > /dev/null; do sleep 1; timeout=$$((timeout-1)); done
	@echo "✅ Services ready for testing!"

test-setup-check:
	@if ! curl -s http://localhost:5001/healthz > /dev/null || ! curl -s http://localhost:8080 > /dev/null; then \
		echo "❌ Services not running. Run 'make test-setup' first."; \
		exit 1; \
	fi

test-cleanup:
	@echo "🧹 Cleaning up test services..."
	-kill `cat .tileserver.pid 2>/dev/null` 2>/dev/null || true
	-kill `cat .app.pid 2>/dev/null` 2>/dev/null || true
	-rm -f .tileserver.pid .app.pid
	-pkill -f "tileserver"
	-pkill -f "main.py"
	@echo "✅ Cleanup complete"

# Debug MapLibre tile loading issue
fix-maplibre:
	@echo "🔍 Debugging MapLibre tile loading..."
	@echo "1. Checking tileserver status..."
	@curl -s http://localhost:8080/ | head -5 || echo "❌ Tileserver not responding"
	@echo "\n2. Testing vector tile endpoint..."
	@curl -s -I http://localhost:8080/data/tampa/10/275/427.pbf || echo "❌ Vector tiles not accessible"
	@echo "\n3. Testing app vector tile proxy..."
	@curl -s -I http://localhost:5001/vector_tiles/10/275/427.pbf || echo "❌ App proxy not working"
	@echo "\n4. Running automated browser debugging..."
	@uv run python tests/e2e/test_maplibre_debugging.py

# Automated browser debugging
debug-browser:
	@echo "🌐 Running automated browser debugging tests..."
	uv run python tests/e2e/test_maplibre_debugging.py

# Network request debugging  
debug-network:
	@echo "🕸️ Running network interception debugging..."
	uv run python tests/e2e/test_network_interception.py

# Complete debugging suite
debug-all: test-setup-check
	@echo "🔬 Running complete debugging suite..."
	@echo "\n1️⃣ Basic MapLibre URL test..."
	@uv run pytest tests/debug/test_maplibre_urls.py -v -s
	@echo "\n2️⃣ Browser automation debugging..."
	@uv run python tests/e2e/test_maplibre_debugging.py
	@echo "\n3️⃣ Network interception debugging..."  
	@uv run python tests/e2e/test_network_interception.py
	@echo "\n✅ Complete debugging suite finished!"

# Watch mode for development
watch:
	@echo "👀 Watching for changes... (Ctrl+C to stop)"
	@while true; do \
		inotifywait -r -e modify,create,delete --include='.*\.py$$' . 2>/dev/null || (echo "Install inotify-tools for watch mode" && exit 1); \
		clear; \
		echo "🔄 Running tests after file change..."; \
		make dev-loop; \
		echo "\n⏳ Waiting for next change..."; \
	done

# Install development dependencies
install-dev:
	@echo "📦 Installing development dependencies..."
	uv add --dev pytest-html pytest-xdist pytest-benchmark locust Pillow imagehash
	uv sync

# Generate test coverage report
coverage:
	@echo "📊 Running tests with coverage..."
	uv run pytest tests/ --cov=. --cov-report=html --cov-report=term
	@echo "📈 Coverage report available at: htmlcov/index.html"