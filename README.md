# Elevation Map Web Application

An interactive web application that overlays elevation data on a map based on the user's location.

![Elevation Map Screenshot](./static/screenshot.png)

## Overview

This project displays color-coded elevation data on an interactive map centered on the user's location. High-resolution elevation data is processed to generate map tiles that visually represent different elevation levels.

## Features

- **Automatic Location Detection**: Identifies the user's location using IP geolocation.
- **Elevation Overlay**: Displays color-coded elevation tiles over the map.
- **Interactive Map**: Users can zoom and pan to explore elevation data in different areas.
- **Fast Data Access**: Elevation data is loaded into memory for quick retrieval.

## How It Works

### Data Processing

1. **Merge Elevation Data**: Combines multiple TIFF files into a single dataset.
2. **Apply Color Ramp**: Assigns colors to elevation ranges using a fixed color scale.
3. **Generate Map Tiles**: Creates tiles for multiple zoom levels using GDAL tools.

### Web Application

1. **Location Detection**: Uses IP geolocation to determine the user's coordinates.
2. **Elevation Retrieval**: Fetches elevation data from in-memory datasets.
3. **Map Rendering**: Displays an interactive map with the elevation overlay.
4. **Tile Serving**: Serves pre-processed map tiles to the web application.

## Technologies Used

- **Python**: Core programming language for the application.
- **FastAPI**: Web framework for building the API.
- **GDAL**: Geospatial data processing library for handling raster data.
- **Rasterio**: Library for reading and writing raster datasets.
- **Google Maps API**: Provides the interactive map interface.
- **DiskCache**: Caching mechanism to improve performance.

## Data Processing Details

- **Elevation Data**: High-resolution TIFF files representing elevation.
- **Color Relief**: A fixed color ramp maps specific elevation ranges to colors.
- **Tile Generation**: Map tiles are created for zoom levels 10 to 15 for detailed visualization.

## Use Cases

- **Elevation Visualization**: Helps users understand the elevation of their surroundings.
- **Flood Risk Awareness**: Assists in identifying areas that may be prone to flooding.
- **Educational Tool**: Provides a visual aid for learning about geographic elevation differences.