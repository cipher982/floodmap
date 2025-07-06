FROM ghcr.io/osgeo/gdal:alpine-latest

# Prevent python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ----------------------------------------------------------------------
# OS dependencies
# ----------------------------------------------------------------------
RUN apk add --no-cache \
    build-base \
    python3-dev \
    py3-pip \
    curl \
    bash

# Upgrade pip first
RUN pip install --upgrade pip

# ----------------------------------------------------------------------
# Copy application source
# ----------------------------------------------------------------------
WORKDIR /app
COPY . /app

# ----------------------------------------------------------------------
# Install Python dependencies (pin versions to match pyproject.toml)
# ----------------------------------------------------------------------
RUN pip install --no-cache-dir \
    diskcache==5.6.3 \
    folium==0.17.0 \
    geopy==2.4.1 \
    googlemaps==4.10.0 \
    ipykernel==6.29.5 \
    matplotlib==3.9.2 \
    numpy==2.1.2 \
    pyproj==3.7.0 \
    python-fasthtml==0.6.9 \
    rasterio==1.4.1 \
    scipy==1.14.1 \
    tqdm==4.66.5 \
    fastapi==0.110.0 \
    uvicorn[standard]==0.29.0 \
    requests==2.31.0 \
    python-dotenv==1.0.1

# ----------------------------------------------------------------------
# Application environment variables
# ----------------------------------------------------------------------
ENV PROCESSED_DIR=/data/processed \
    INPUT_DIR=/data/input \
    COLOR_RAMP=/app/scripts/color_ramp.txt \
    CACHE_DIR=/cache

# Create required directories
RUN mkdir -p ${PROCESSED_DIR} ${INPUT_DIR} ${CACHE_DIR}

# Expose API port
EXPOSE 5001

# Default command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]