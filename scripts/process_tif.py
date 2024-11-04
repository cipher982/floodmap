import warnings

def ignore_gdal_warnings():
    """Custom warning filter for GDAL"""
    warnings.simplefilter("ignore", FutureWarning)
    warnings.simplefilter("ignore", UserWarning)
    warnings.simplefilter("ignore", RuntimeWarning)
    warnings.filterwarnings("ignore", message=".*gdal.*")
    warnings.filterwarnings("ignore", message=".*GDAL.*")
    warnings.filterwarnings("ignore", message=".*UseExceptions.*")

ignore_gdal_warnings()

import os
os.environ["GDAL_PAM_ENABLED"] = "NO"
os.environ["CPL_DEBUG"] = "OFF"
os.environ["GDAL_LIBRARY_PATH"] = "/opt/homebrew/lib/libgdal.dylib"
os.environ["PROJ_LIB"] = "/opt/homebrew/share/proj"

from osgeo import gdal
gdal.PushErrorHandler("CPLQuietErrorHandler")
gdal.DontUseExceptions()

import numpy as np
from tqdm import tqdm
import logging
import dotenv
import subprocess

dotenv.load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


INPUT_DIR = str(os.getenv("INPUT_DIR"))
PROCESSED_DIR = str(os.getenv("PROCESSED_DIR"))
COLOR_RAMP = str(os.getenv("COLOR_RAMP"))
# Update these constants
ZOOM_RANGE = (10, 11)

MIN_ELEVATION = -100
MAX_ELEVATION = 5500  # rounded up from 5489 for clean numbers

NUM_CORES = 12
MEMORY_LIMIT = 32768  # 32GB RAM allocation for GDAL


def analyze_raster_values(input_file):
    """Analyze a single raster file for its data ranges and nodata values."""
    ds = gdal.Open(input_file)
    band = ds.GetRasterBand(1)
    
    # Get basic stats
    stats = band.GetStatistics(True, True)  # force computation
    nodata = band.GetNoDataValue()
    
    # Get data type info
    dtype = gdal.GetDataTypeName(band.DataType)
    
    logging.info(f"\nAnalyzing {os.path.basename(input_file)}")
    logging.info(f"Data type: {dtype}")
    logging.info(f"NoData value: {nodata}")
    logging.info(f"Min: {stats[0]:.2f}")
    logging.info(f"Max: {stats[1]:.2f}")
    logging.info(f"Mean: {stats[2]:.2f}")
    logging.info(f"StdDev: {stats[3]:.2f}")
    
    return {
        "file": input_file,
        "dtype": dtype,
        "nodata": nodata,
        "min": stats[0],
        "max": stats[1],
        "mean": stats[2],
        "stddev": stats[3]
    }

def elevation_to_color(elevation):
    """Generate a color based on elevation (0-20 feet scale)."""
    normalized = min(max(elevation, MIN_ELEVATION), MAX_ELEVATION) / MAX_ELEVATION
    if normalized < 0.5:
        r = int(0 + 510 * normalized)
        g = int(255 * normalized)
        b = int(255 * (0.5 - normalized) / 0.5)
    else:
        r = 255
        g = int(255 * (1 - normalized) / 0.5)
        b = 0
    return r, g, b


def process_group(files, output_dir, zoom_range):
    """Process one geographical group of files"""
    group_dir = os.path.join(output_dir, f"tiles_{os.path.basename(files[0])}")
    os.makedirs(group_dir, exist_ok=True)

    for input_file in files:
        vrt_file = os.path.join(output_dir, f"temp_{os.path.basename(input_file)}.vrt")
        translate_cmd = [
            "gdal_translate",
            "-of", "VRT",
            "-ot", "Byte",
            "-scale", str(MIN_ELEVATION), str(MAX_ELEVATION),
            "0", "255",
            "-a_nodata", "0",  # Set output nodata
            "-q",
            input_file,
            vrt_file,
        ]
        subprocess.run(translate_cmd, check=True)

        # Then generate tiles from the 8-bit VRT
        cmd = [
            "gdal2tiles.py",
            "--xyz",
            "-z",
            f"{zoom_range[0]}-{zoom_range[1]}",
            "--processes",
            "10",
            "-r",
            "average",
            "--profile",
            "mercator",
            "--webviewer",
            "none",  # This replaces --no-mapml
            "-q",  # Add quiet flag
            vrt_file,
            group_dir,
        ]
        subprocess.run(cmd, check=True)

        # Clean up temporary VRT file
        os.remove(vrt_file)


def group_files_by_location(input_files, grid_size=5):
    """Group files into geographical grid cells (e.g., 5x5 degree squares)"""
    groups = {}

    for file in input_files:
        ds = gdal.Open(file)
        gt = ds.GetGeoTransform()

        # Get center point of the TIF
        center_lat = gt[3] + (ds.RasterYSize * gt[5] / 2)
        center_lon = gt[0] + (ds.RasterXSize * gt[1] / 2)

        # Group by grid cell
        grid_lat = int(center_lat / grid_size) * grid_size
        grid_lon = int(center_lon / grid_size) * grid_size

        cell_id = f"{grid_lat}_{grid_lon}"
        groups.setdefault(cell_id, []).append(file)

    return groups


def create_dynamic_color_ramp(min_elevation, max_elevation, num_steps=256):
    """Create a color ramp based on the elevation range."""
    elevations = np.linspace(min_elevation, max_elevation, num_steps)
    colors = [elevation_to_color(e) for e in elevations]
    return list(zip(elevations, colors))


def create_fixed_color_ramp(num_steps=256):
    """Create a color ramp based on the fixed elevation range (0-20 feet)."""
    elevations = np.linspace(MIN_ELEVATION, MAX_ELEVATION, num_steps)
    colors = [elevation_to_color(e) for e in elevations]
    return list(zip(elevations, colors))


def write_color_ramp_file(color_ramp, output_file):
    """Write the color ramp to a file."""
    with open(output_file, "w") as f:
        for elevation, (r, g, b) in color_ramp:
            f.write(f"{elevation} {r} {g} {b} 255\n")


def analyze_tif_files(input_dir):
    """Analyze all TIF files in directory to determine coverage."""
    files = [f for f in os.listdir(input_dir) if f.endswith(".tif")]

    all_bounds = []
    lat_min_global = float("inf")
    lat_max_global = float("-inf")
    lon_min_global = float("inf")
    lon_max_global = float("-inf")

    logging.info(f"Analyzing {len(files)} TIF files...")

    for file in tqdm(files, desc="Analyzing files"):
        filepath = os.path.join(input_dir, file)
        ds = gdal.Open(filepath)
        geotransform = ds.GetGeoTransform()
        width = ds.RasterXSize
        height = ds.RasterYSize

        lon_min = geotransform[0]
        lat_max = geotransform[3]
        lon_max = lon_min + width * geotransform[1]
        lat_min = lat_max + height * geotransform[5]

        all_bounds.append(
            {
                "file": file,
                "lat_min": lat_min,
                "lat_max": lat_max,
                "lon_min": lon_min,
                "lon_max": lon_max,
            }
        )

        # Update global bounds
        lat_min_global = min(lat_min_global, lat_min)
        lat_max_global = max(lat_max_global, lat_max)
        lon_min_global = min(lon_min_global, lon_min)
        lon_max_global = max(lon_max_global, lon_max)

    # Sort by latitude and longitude for better organization
    all_bounds.sort(key=lambda x: (-x["lat_max"], x["lon_min"]))

    logging.info("\nOverall Coverage:")
    logging.info(f"Latitude:  {lat_min_global:.4f}°N to {lat_max_global:.4f}°N")
    logging.info(f"Longitude: {lon_min_global:.4f}°W to {lon_max_global:.4f}°W")

    # Modify the range calculation section
    lat_ranges = []
    lon_ranges = []

    for bound in all_bounds:
        # Round to nearest degree for better grouping
        lat_min_round = round(bound["lat_min"])
        lat_max_round = round(bound["lat_max"])
        lon_min_round = round(bound["lon_min"])
        lon_max_round = round(bound["lon_max"])

        # Store as tuples for easier sorting
        lat_ranges.append((lat_min_round, lat_max_round))
        lon_ranges.append((lon_min_round, lon_max_round))

    # Remove duplicates and sort
    lat_ranges = sorted(set(lat_ranges), key=lambda x: x[0], reverse=True)
    lon_ranges = sorted(set(lon_ranges), key=lambda x: x[0])

    logging.info("\nCoverage Summary:")
    logging.info(f"Total files: {len(files)}")
    logging.info(f"Latitude ranges: {len(lat_ranges)} unique ranges")
    logging.info(f"Northernmost: {lat_max_global:.4f}°N")
    logging.info(f"Southernmost: {lat_min_global:.4f}°N")
    logging.info(f"Longitude ranges: {len(lon_ranges)} unique ranges")
    logging.info(f"Westernmost: {lon_min_global:.4f}°W")
    logging.info(f"Easternmost: {lon_max_global:.4f}°W")

    # Print some example ranges for verification
    logging.info("\nExample ranges:")
    logging.info(
        f"First 3 latitude ranges: {[f'{x[0]}-{x[1]}N' for x in lat_ranges[:3]]}"
    )
    logging.info(
        f"First 3 longitude ranges: {[f'{x[0]}-{x[1]}W' for x in lon_ranges[:3]]}"
    )

    return all_bounds


def main():
    # Get all input files
    input_files = [
        os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.endswith(".tif")
    ]

    # Group files by location
    groups = group_files_by_location(input_files)
    logging.info(f"Split files into {len(groups)} geographical groups")

    try:
        # Process groups serially
        for i, group_files in enumerate(groups.values(), 1):
            logging.info(f"Processing group {i} of {len(groups)}")
            process_group(group_files, PROCESSED_DIR, ZOOM_RANGE)
            
    except KeyboardInterrupt:
        logging.info("Received interrupt, shutting down gracefully...")
        raise

if __name__ == "__main__":
    main()
