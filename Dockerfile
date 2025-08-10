FROM python:3.12-alpine

# Prevent python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ----------------------------------------------------------------------
# Install system dependencies and uv
# ----------------------------------------------------------------------
RUN apk add --no-cache \
    curl \
    bash && \
    pip install --no-cache-dir uv

# ----------------------------------------------------------------------
# Setup application directory and copy project files
# ----------------------------------------------------------------------
WORKDIR /app

# Copy uv project files first for better Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (only core serving dependencies)
RUN uv sync --frozen --no-dev

# Copy application source code
COPY src/ ./src/

# Copy elevation data directly into container
COPY output/elevation ./output/elevation

# ----------------------------------------------------------------------
# Application environment variables for serving
# ----------------------------------------------------------------------
ENV PROJECT_ROOT=/app \
    ELEVATION_DATA_DIR=output/elevation \
    CACHE_DIR=/cache

# Create required directories
RUN mkdir -p ${CACHE_DIR}

# Expose API port
EXPOSE 8000

# Change to API directory for relative imports
WORKDIR /app/src/api

# Use uv to run the application
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]