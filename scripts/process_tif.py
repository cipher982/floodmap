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

from osgeo import gdal  # type: ignore

gdal.PushErrorHandler("CPLQuietErrorHandler")
gdal.DontUseExceptions()

import glob
import math
import numpy as np
from tqdm import tqdm
import logging
import dotenv
import subprocess
from multiprocessing import Pool
import multiprocessing as mp

dotenv.load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


INPUT_DIR = str(os.getenv("INPUT_DIR"))
PROCESSED_DIR = str(os.getenv("PROCESSED_DIR"))
COLOR_RAMP = str(os.getenv("COLOR_RAMP"))
# Update these constants
ZOOM_RANGE = (8, 9)

MIN_ELEVATION = -100
MAX_ELEVATION = 5500  # rounded up from 5489 for clean numbers

NUM_CORES = mp.cpu_count()
POOL_WORKERS = 4
GDAL_THREADS = NUM_CORES // POOL_WORKERS
CHUNK_SIZE = 1
GDAL_CACHE = 512

os.environ["GDAL_CACHEMAX"] = str(GDAL_CACHE)
os.environ["VSI_CACHE"] = "TRUE"
os.environ["VSI_CACHE_SIZE"] = str(GDAL_CACHE * 1024 * 1024)  # Convert to bytes



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
        "stddev": stats[3],
    }


def validate_coordinates(original_bounds, processed_bounds, tolerance=0.0001):
    """
    Validate that processed coordinates match original coordinates within tolerance.
    Returns (is_valid, error_message)
    """
    checks = {
        "North": (original_bounds["north"], processed_bounds["north"]),
        "South": (original_bounds["south"], processed_bounds["south"]),
        "East": (original_bounds["east"], processed_bounds["east"]),
        "West": (original_bounds["west"], processed_bounds["west"])
    }
    
    errors = []
    for direction, (orig, proc) in checks.items():
        if abs(orig - proc) > tolerance:
            errors.append(
                f"{direction} boundary mismatch: original={orig:.4f}, processed={proc:.4f}"
            )
    
    return (len(errors) == 0, errors)


def process_file(args):
    """Process a single file with optimized settings"""
    input_file, output_dir, zoom_range = args
    tiles_dir = os.path.join(output_dir, "tiles")
    os.makedirs(tiles_dir, exist_ok=True)

    # Create temporary VRT in the output directory
    base_name = os.path.basename(input_file)
    vrt_file = os.path.join(output_dir, f"temp_{base_name}.vrt")
    
    translate_opts = gdal.TranslateOptions(
        format="VRT",
        outputType=gdal.GDT_Byte,  # Changed to 8-bit
        scaleParams=[[MIN_ELEVATION, MAX_ELEVATION, 0, 255]],  # Scale to 0-255
        creationOptions=[
            "TILED=YES",
            "BLOCKSIZE=512",
            "COMPRESS=LZW"
        ]
    )
    
    gdal.Translate(vrt_file, input_file, options=translate_opts)

    cmd = [
        "gdal2tiles.py",
        "--xyz",
        "-z", f"{zoom_range[0]}-{zoom_range[1]}",
        "--processes", str(GDAL_THREADS),
        "-r", "cubic",
        "--webviewer", "none",
        "-q",
        vrt_file,
        tiles_dir,
    ]
    
    try:
        subprocess.run(cmd, check=True)
    finally:
        if os.path.exists(vrt_file):
            os.remove(vrt_file)
    
    return tiles_dir

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

        # Add detailed logging for first few files
        if len(all_bounds) < 3:
            logging.info(f"\nDetailed analysis for {file}:")
            logging.info(f"Geotransform: {geotransform}")
            logging.info(f"Size: {width}x{height} pixels")

            # Get projection info
            proj = ds.GetProjection()
            logging.info(f"Projection: {proj}")

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

def analyze_coverage(input_dir, output_dir):
    """Analyze and compare input TIFs vs output tile coverage"""
    
    # Input analysis stays the same
    input_files = glob.glob(os.path.join(input_dir, "*.tif"))
    input_bounds = []
    
    logging.info(f"\nAnalyzing {len(input_files)} input TIF files...")
    for file in tqdm(input_files, desc="Analyzing inputs"):
        ds = gdal.Open(file)
        gt = ds.GetGeoTransform()
        
        # Calculate bounds
        north = gt[3]
        south = gt[3] + (ds.RasterYSize * gt[5])
        west = gt[0]
        east = gt[0] + (ds.RasterXSize * gt[1])
        
        input_bounds.append({
            "file": os.path.basename(file),
            "north": north,
            "south": south,
            "west": west,
            "east": east
        })
    
    # New output analysis for unified tile structure
    tiles_dir = os.path.join(output_dir, "tiles")
    output_coverage = []
    
    if os.path.exists(tiles_dir):
        zoom_levels = [int(d) for d in os.listdir(tiles_dir) 
                      if os.path.isdir(os.path.join(tiles_dir, d))]
        
        logging.info(f"\nAnalyzing tiles for zoom levels: {zoom_levels}")
        for z in zoom_levels:
            zoom_dir = os.path.join(tiles_dir, str(z))
            x_coords = [int(d) for d in os.listdir(zoom_dir) 
                       if os.path.isdir(os.path.join(zoom_dir, d))]
            
            if not x_coords:
                continue
                
            # Find bounds for this zoom level
            min_x, max_x = min(x_coords), max(x_coords)
            
            # Find y bounds by checking all x directories
            y_coords = []
            for x in x_coords:
                y_files = glob.glob(os.path.join(zoom_dir, str(x), "*.png"))
                y_coords.extend([int(os.path.basename(f).split('.')[0]) for f in y_files])
            
            if y_coords:
                min_y, max_y = min(y_coords), max(y_coords)
                
                # Convert tile coordinates to lat/lon
                output_coverage.append({
                    "zoom": z,
                    "bounds": {
                        "north": tile2lat(min_y, z),
                        "south": tile2lat(max_y + 1, z),
                        "west": tile2lon(min_x, z),
                        "east": tile2lon(max_x + 1, z)
                    },
                    "tile_counts": {
                        "x_range": (min_x, max_x),
                        "y_range": (min_y, max_y),
                        "total_tiles": len(y_coords)
                    }
                })
    
    # Report findings
    logging.info("\nCoverage Analysis Results:")
    logging.info(f"Input files: {len(input_files)}")
    
    if output_coverage:
        for zoom_data in output_coverage:
            z = zoom_data["zoom"]
            bounds = zoom_data["bounds"]
            counts = zoom_data["tile_counts"]
            
            logging.info(f"\nZoom level {z}:")
            logging.info(f"Bounds: {bounds['north']:.4f}°N to {bounds['south']:.4f}°N, "
                        f"{bounds['west']:.4f}°W to {bounds['east']:.4f}°W")
            logging.info(f"Tile coverage: {counts['total_tiles']} tiles "
                        f"({counts['x_range'][1] - counts['x_range'][0] + 1}x"
                        f"{counts['y_range'][1] - counts['y_range'][0] + 1} grid)")
    else:
        logging.info("No output tiles found!")
    
    return input_bounds, output_coverage

def tile2lat(y, z):
    """Convert tile y coordinate to latitude"""
    n = math.pi - 2.0 * math.pi * y / math.pow(2.0, z)
    return math.degrees(math.atan(math.sinh(n)))

def tile2lon(x, z):
    """Convert tile x coordinate to longitude"""
    return x / math.pow(2.0, z) * 360.0 - 180.0


def main():
    analyze_tif_files(INPUT_DIR)

    # Clear entire processed directory at start
    if os.path.exists(PROCESSED_DIR):
        logging.info(f"Clearing output directory: {PROCESSED_DIR}")
        subprocess.run(["rm", "-rf", PROCESSED_DIR])
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # Get all input files directly (no grouping needed)
    input_files = [
        os.path.join(INPUT_DIR, f) 
        for f in os.listdir(INPUT_DIR) 
        if f.endswith(".tif")
    ]

    # Process all files in parallel
    process_args = [
        (file, PROCESSED_DIR, ZOOM_RANGE)
        for file in input_files
    ]

    try:
        with Pool(POOL_WORKERS) as pool:
            list(tqdm(
                pool.imap_unordered(process_file, process_args, chunksize=CHUNK_SIZE),
                total=len(process_args),
                desc="Processing files"
            ))

    except KeyboardInterrupt:
        logging.info("Received interrupt, shutting down gracefully...")
        raise

    logging.info("\nAnalyzing final coverage...")
    _, _ = analyze_coverage(INPUT_DIR, PROCESSED_DIR)


if __name__ == "__main__":
    main()
