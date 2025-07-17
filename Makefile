# Flood Map - Clean Architecture Makefile
.PHONY: help run start stop test process-data process-miami process-regions list-regions status monitor download-region process-region

# Default target
help:
	@echo "🌊 Flood Map Commands:"
	@echo ""
	@echo "🚀 Main Commands:"
	@echo "  make run           - Start website with elevation overlays (localhost:5002)"
	@echo "  make start         - Start tileserver + website"
	@echo "  make stop          - Stop all services"
	@echo "  make test          - Test website functionality"
	@echo ""
	@echo "🔧 Individual Services:"
	@echo "  make tileserver    - Start tileserver only"
	@echo "  make website       - Start website only (requires tileserver)"
	@echo ""
	@echo "📊 Data Processing:"
	@echo "  make process-test  - Test pipeline with one tile"
	@echo "  make process-all   - Process all USA elevation data"
	@echo ""
	@echo "🗺️ Regional Maps:"
	@echo "  make download-region - Download specific region"
	@echo "  make process-regions - Process priority regions"
	@echo "  make status         - Show system status"
	@echo "  make monitor        - Monitor system progress"

# Main development commands
run: start

start:
	@echo "🚀 Starting flood map services..."
	$(MAKE) tileserver
	@echo "⏳ Waiting for tileserver..."
	@timeout=30; while [ $$timeout -gt 0 ] && ! curl -s http://localhost:8080 > /dev/null; do sleep 1; timeout=$$((timeout-1)); done
	@echo "🌐 Starting website with elevation overlays..."
	cd flood-map-v2/api && uv run uvicorn main:app --host 0.0.0.0 --port 5002 --reload

website:
	@echo "🌐 Starting website at http://localhost:5002"
	@echo "💡 Make sure tileserver is running: make tileserver"
	cd flood-map-v2/api && uv run uvicorn main:app --host 0.0.0.0 --port 5002 --reload

stop:
	@echo "🛑 Stopping all services..."
	$(MAKE) stop-tileserver
	-pkill -f "uvicorn main:app"
	@echo "✅ All services stopped"

test:
	@echo "🧪 Testing flood map..."
	@echo "💡 Make sure services are running: make start"
	@echo "🌐 Testing website..."
	curl -s http://localhost:5002 > /dev/null && echo "✅ Website responds" || echo "❌ Website not responding"
	@echo "🏔️ Testing elevation tiles..."
	curl -s http://localhost:5002/tiles/elevation/12/1103/1709.png > /dev/null && echo "✅ Elevation tiles work" || echo "❌ Elevation tiles failing"

# Service management
tileserver:
	@echo "🚀 Starting multi-region tileserver..."
	@# Stop existing container
	@if docker ps -a --format '{{.Names}}' | grep -q "^tileserver-local$$"; then \
		echo "🛑 Stopping existing tileserver..."; \
		docker stop tileserver-local 2>/dev/null || true; \
		docker rm tileserver-local 2>/dev/null || true; \
	fi
	@# Check if config exists
	@if [ ! -f "map_data/config.json" ]; then \
		echo "❌ TileServer config not found in map_data/"; \
		exit 1; \
	fi
	@# Update config with available regions
	uv run python scripts/update_tileserver_config.py
	@# Start container with config
	docker run --rm --name tileserver-local \
		-p 8080:8080 \
		-v $(PWD)/map_data:/data \
		maptiler/tileserver-gl --config /data/config.json &

stop-tileserver:
	@echo "🛑 Stopping tileserver..."
	@if docker ps --format '{{.Names}}' | grep -q "^tileserver-local$$"; then \
		docker stop tileserver-local; \
	fi
	@if docker ps -a --format '{{.Names}}' | grep -q "^tileserver-local$$"; then \
		docker rm tileserver-local; \
	fi

# Data processing commands
process-test:
	@echo "🧪 Testing pipeline with one tile..."
	uv run python scripts/process_elevation.py --test

process-all:
	@echo "🇺🇸 Processing all USA elevation data..."
	@echo "⚠️  This will take several hours and use significant disk space"
	@read -p "Continue? (y/N) " confirm && [ "$$confirm" = "y" ]
	uv run python scripts/process_elevation.py --all

# Regional map processing
download-region:
	@echo "📍 Available regions: california, texas, new-york, florida, illinois"
	@read -p "Enter region name: " region && \
	export PATH="/opt/homebrew/opt/openjdk@21/bin:$$PATH" && \
	uv run python scripts/download_regional_maps.py --region $$region

process-regions:
	@echo "🗺️ Processing priority regions..."
	export PATH="/opt/homebrew/opt/openjdk@21/bin:$$PATH" && \
	uv run python scripts/download_regional_maps.py --max-regions 3

status:
	@echo "📊 Flood Map System Status..."
	uv run python system_status.py

monitor:
	@echo "🔄 Monitoring system (Press Ctrl+C to stop)..."
	uv run python system_status.py --watch 5