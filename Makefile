# Flood Map - Clean Architecture Makefile
.PHONY: help run start stop test process-data process-miami process-regions list-regions

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
	@echo "🚀 Starting tileserver..."
	@# Stop existing container
	@if docker ps -a --format '{{.Names}}' | grep -q "^tileserver-local$$"; then \
		echo "🛑 Stopping existing tileserver..."; \
		docker stop tileserver-local 2>/dev/null || true; \
		docker rm tileserver-local 2>/dev/null || true; \
	fi
	@# Check if data exists
	@if [ ! -f "map_data/tampa.mbtiles" ]; then \
		echo "❌ Tampa MBTiles not found in map_data/"; \
		exit 1; \
	fi
	@# Start container
	docker run --rm --name tileserver-local \
		-p 8080:8080 \
		-v $(PWD)/map_data:/data \
		maptiler/tileserver-gl tampa.mbtiles &

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