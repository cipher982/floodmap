# Flood Map - Simplified Makefile (No Dynamic Config Generation)
.PHONY: help start stop test tileserver website clean

# Default target
help:
	@echo "🌊 Flood Map - Simplified Commands:"
	@echo ""
	@echo "🚀 Main Commands:"
	@echo "  make start    - Start tileserver + API server"
	@echo "  make stop     - Stop all services"
	@echo "  make test     - Test tile endpoints"
	@echo "  make clean    - Clean up containers and processes"
	@echo ""
	@echo "🔧 Individual Services:"
	@echo "  make tileserver - Start tileserver only"
	@echo "  make website    - Start API server only"

# Main command - start everything
start:
	@echo "🚀 Starting flood map services..."
	@$(MAKE) tileserver
	@echo "⏳ Waiting for tileserver..."
	@timeout=30; while [ $$timeout -gt 0 ] && ! curl -s http://localhost:8080 > /dev/null; do sleep 1; timeout=$$((timeout-1)); done
	@echo "🌐 Starting API server..."
	@cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Start tileserver with static config (no dynamic generation)
tileserver:
	@echo "🚀 Starting tileserver on port 8080..."
	@# Stop existing container if running
	@docker stop tileserver-local 2>/dev/null || true
	@docker rm tileserver-local 2>/dev/null || true
	@# Use existing config from data/processed/maps
	@if [ ! -f "data/processed/maps/config.json" ]; then \
		echo "❌ Missing config file at data/processed/maps/config.json"; \
		exit 1; \
	fi
	@# Start tileserver container  
	@docker run -d --name tileserver-local \
		-p 8080:8080 \
		-v $(PWD)/data/processed/maps:/data \
		maptiler/tileserver-gl

# Start API server only
website:
	@echo "🌐 Starting API server at http://localhost:8000"
	@echo "💡 Make sure tileserver is running: make tileserver"
	@cd src/api && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Stop all services
stop:
	@echo "🛑 Stopping all services..."
	@docker stop tileserver-local 2>/dev/null || true
	@docker rm tileserver-local 2>/dev/null || true
	@pkill -f "uvicorn main:app" 2>/dev/null || true
	@echo "✅ All services stopped"

# Test endpoints
test:
	@echo "🧪 Testing flood map endpoints..."
	@echo "🌐 Testing API server..."
	@curl -s http://localhost:8000/api/v1/tiles/health > /dev/null && echo "✅ API server responds" || echo "❌ API server not responding"
	@echo "🗺️ Testing vector tiles..."
	@curl -s http://localhost:8000/api/v1/tiles/vector/usa/10/286/387.pbf > /dev/null && echo "✅ Vector tiles work" || echo "❌ Vector tiles failing"
	@echo "🏔️ Testing elevation tiles..."
	@curl -s http://localhost:8000/api/v1/tiles/elevation/10/286/387.png > /dev/null && echo "✅ Elevation tiles work" || echo "❌ Elevation tiles failing"
	@echo "🌊 Testing flood tiles..."  
	@curl -s http://localhost:8000/api/v1/tiles/flood/1.0/10/286/387.png > /dev/null && echo "✅ Flood tiles work" || echo "❌ Flood tiles failing"

# Clean up everything
clean:
	@echo "🧹 Cleaning up containers and processes..."
	@docker stop tileserver-local 2>/dev/null || true
	@docker rm tileserver-local 2>/dev/null || true
	@pkill -f "uvicorn main:app" 2>/dev/null || true
	@docker system prune -f
	@echo "✅ Cleanup complete"

# Legacy compatibility
run: start