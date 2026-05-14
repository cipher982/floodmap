# Flood Map - Clean Pipeline + Services
.PHONY: help start stop test test-integration test-visual test-references test-all tileserver website clean process-maps process-elevation cube-review run

# Default target
help: ## Show this help
	@echo "🌊 Flood Map - Clean Pipeline + Services:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "💡 Examples:"
	@echo "  make process-maps ZOOM=4   # Quick test"
	@echo "  make process-maps ZOOM=12  # Production"

# Main command - start everything
start: ## 🚀 Start tileserver + API server
	@echo "🚀 Starting flood map services..."
	@$(MAKE) tileserver
	@echo "⏳ Waiting for tileserver..."
	@timeout=30; while [ $$timeout -gt 0 ] && ! curl -s http://localhost:8080 > /dev/null; do sleep 1; timeout=$$((timeout-1)); done
	@echo "🌐 Starting API server..."
	@if [ -f .env ]; then \
		API_PORT=$$(grep "^API_PORT=" .env | cut -d'=' -f2 | cut -d'#' -f1 | tr -d ' '); \
		echo "📡 Using port $$API_PORT from .env file"; \
		cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port $$API_PORT --reload; \
	else \
		echo "⚠️  No .env file found, using default port 8000"; \
		cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload; \
	fi

# Start tileserver with static config (no dynamic generation)
tileserver: ## 🔧 Start tileserver only
	@echo "🚀 Starting tileserver on port 8080..."
	@# Stop existing container if running
	@docker stop tileserver-local 2>/dev/null || true
	@docker rm tileserver-local 2>/dev/null || true
	@# Use output directory with generated tiles
	@if [ ! -f "output/usa-complete.mbtiles" ]; then \
		echo "❌ No map tiles found. Run: make process-maps ZOOM=4"; \
		exit 1; \
	fi
	@# Create simple config for tileserver
	@echo '{"options":{"paths":{"root":"/data","mbtiles":"/data"}},"data":{"usa-complete":{"mbtiles":"usa-complete.mbtiles"}}}' > output/config.json
	@# Start tileserver container
	@docker run -d --name tileserver-local \
		-p 8080:8080 \
		-v $(PWD)/output:/data \
		maptiler/tileserver-gl

cube-review: ## Start the Cube Tailscale review stack
	@ssh cube 'cd /mnt/storage/floodmap/repo && scripts/cube-review-up.sh'

# Start API server only
website: ## 🔧 Start API server only
	@if [ -f .env ]; then \
		API_PORT=$$(grep "^API_PORT=" .env | cut -d'=' -f2 | cut -d'#' -f1 | tr -d ' '); \
		echo "🌐 Starting API server at http://localhost:$$API_PORT"; \
		echo "💡 Make sure tileserver is running: make tileserver"; \
		cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port $$API_PORT --reload; \
	else \
		echo "🌐 Starting API server at http://localhost:8000"; \
		echo "💡 Make sure tileserver is running: make tileserver"; \
		cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload; \
	fi

# Stop all services
stop: ## 🛑 Stop all services
	@echo "🛑 Stopping all services..."
	@docker stop tileserver-local 2>/dev/null || true
	@docker rm tileserver-local 2>/dev/null || true
	@pkill -f "uvicorn main:app" 2>/dev/null || true
	@echo "✅ All services stopped"

# Testing
test: ## 🧪 Run basic endpoint tests
	@echo "🧪 Running unit tests..."
	@uv run pytest tests/unit/ -v

test-integration: ## 🔗 Run integration, performance, and E2E tests
	@echo "🔗 Running integration tests..."
	@uv run pytest tests/integration/ tests/performance/ tests/e2e/ -v

# Clean up everything
clean: ## 🧹 Clean up containers and processes
	@echo "🧹 Cleaning up containers and processes..."
	@docker stop tileserver-local 2>/dev/null || true
	@docker rm tileserver-local 2>/dev/null || true
	@pkill -f "uvicorn main:app" 2>/dev/null || true
	@docker system prune -f
	@echo "✅ Cleanup complete"

# Data processing pipelines
process-maps: ## 🗺️ Generate map tiles (use ZOOM=4 for test)
	@echo "🗺️ Processing USA map tiles..."
	@cd src && uv run python process_maps_usa.py --maxzoom=$(or $(ZOOM),8)

process-elevation: ## 🏔️ Process elevation data
	@echo "🏔️ Processing elevation data..."
	@cd src && uv run python process_elevation_usa.py --input /Volumes/Storage/floodmap-archive/elevation-raw --output ../output/elevation --workers 12

# Legacy compatibility
run: start ## 🚀 Legacy alias for start
