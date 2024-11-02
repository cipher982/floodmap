import os
import subprocess
import numpy as np
from osgeo import gdal  # type: ignore
from tqdm import tqdm
import logging
import dotenv

os.environ["GDAL_LIBRARY_PATH"] = "/opt/homebrew/lib/libgdal.dylib"
os.environ["PROJ_LIB"] = "/opt/homebrew/share/proj"

dotenv.load_dotenv()


gdal.UseExceptions()

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


INPUT_DIR = str(os.getenv("INPUT_DIR"))
PROCESSED_DIR = str(os.getenv("PROCESSED_DIR"))
COLOR_RAMP = str(os.getenv("COLOR_RAMP"))
# Update these constants
ZOOM_RANGE = (10, 11)

MIN_ELEVATION = 0
MAX_ELEVATION = 20  # feet

NUM_CORES = 12
MEMORY_LIMIT = 32768  # 32GB RAM allocation for GDAL


# def merge_tif_files(input_files, output_file):
#     """Merge multiple TIF files into a single file."""
#     total_files = len(input_files)
#     logging.info(f"Merging {total_files} TIF files into {output_file}")

#     # Log bounds of first and last files for debugging
#     for idx, f in enumerate([input_files[0], input_files[-1]]):
#         ds = gdal.Open(f)
#         gt = ds.GetGeoTransform()
#         width = ds.RasterXSize
#         height = ds.RasterYSize
#         lon_min = gt[0]
#         lat_max = gt[3]
#         lon_max = lon_min + width * gt[1]
#         lat_min = lat_max + height * gt[5]
#         logging.info(f"{'First' if idx == 0 else 'Last'} file bounds:")
#         logging.info(f"  Latitude: {lat_min:.4f}°N to {lat_max:.4f}°N")
#         logging.info(f"  Longitude: {lon_min:.4f}°W to {lon_max:.4f}°W")

#     temp_vrt = output_file.replace(".tif", "_temp.vrt")

#     merge_command = [
#         "gdalbuildvrt",
#         "-resolution",
#         "highest",
#         "-r",
#         "nearest",
#         "-separate",
#         "-overwrite",
#         temp_vrt,
#     ] + sorted(input_files)

#     try:
#         logging.info("Creating VRT file...")
#         result = subprocess.run(merge_command, capture_output=True, text=True)
#         if result.returncode != 0:
#             logging.error(f"Error creating VRT: {result.stderr}")
#             raise subprocess.CalledProcessError(
#                 result.returncode, merge_command, result.stdout, result.stderr
#             )

#         # Use gdalwarp instead of gdal_translate
#         logging.info("Converting VRT to GeoTIFF using gdalwarp...")
#         warp_command = [
#             "gdalwarp",
#             "-of", "GTiff",
#             "-co", "COMPRESS=LZW",
#             "-co", "BIGTIFF=YES",
#             "-co", "TILED=YES",
#             "-co", "NUM_THREADS=ALL_CPUS",  # Add this
#             "-wo", "NUM_THREADS=ALL_CPUS",
#             "--config", "GDAL_NUM_THREADS", str(NUM_CORES),
#             "--config", "GDAL_CACHEMAX", str(MEMORY_LIMIT),
#             "--config", "CHECK_DISK_FREE_SPACE", "FALSE",
#             "--config", "GDAL_DISABLE_READDIR_ON_OPEN", "TRUE",  # Add this
#             "-multi",
#             "-wm", str(MEMORY_LIMIT * 1024 * 1024),  # Memory in bytes
#             "-overwrite",
#             "-wo", f"NUM_THREADS={NUM_CORES}",  # Add explicit thread count
#             temp_vrt,
#             output_file
#         ]

#         subprocess.run(warp_command, check=True)
#         os.remove(temp_vrt)

#         # Log final merged file bounds
#         ds = gdal.Open(output_file)
#         gt = ds.GetGeoTransform()
#         width = ds.RasterXSize
#         height = ds.RasterYSize
#         lon_min = gt[0]
#         lat_max = gt[3]
#         lon_max = lon_min + width * gt[1]
#         lat_min = lat_max + height * gt[5]
#         logging.info("Merged file bounds:")
#         logging.info(f"  Latitude: {lat_min:.4f}°N to {lat_max:.4f}°N")
#         logging.info(f"  Longitude: {lon_min:.4f}°W to {lon_max:.4f}°W")

#     except Exception as e:
#         logging.error(f"Error in merge process: {str(e)}")
#         if os.path.exists(temp_vrt):
#             os.remove(temp_vrt)
#         raise


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
        # Generate tiles directly from each file
        cmd = [
            "gdal2tiles.py",
            "--xyz",
            "-z", f"{zoom_range[0]}-{zoom_range[1]}",
            "--processes", "ALL_CPUS",
            "-r", "average",
            "--profile", "mercator",
            input_file,
            group_dir
        ]
        subprocess.run(cmd, check=True)


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


# def process_tif_file(input_file, output_dir):
#     try:
#         base_name = os.path.splitext(os.path.basename(input_file))[0]
#         output_file = os.path.join(output_dir, f"{base_name}_colored.tif")
#         tiles_dir = os.path.join(output_dir, "tiles")

#         # Get elevation range and geotransform
#         ds = gdal.Open(input_file)
#         logging.info(f"Input projection: {ds.GetProjection()}")

#         # First, reproject to Web Mercator (EPSG:3857)
#         reprojected_file = os.path.join(output_dir, f"{base_name}_mercator.tif")
#         logging.info("Reprojecting to Web Mercator...")
#         cmd = [
#             "gdalwarp",
#             "-s_srs",
#             "EPSG:4326",
#             "-t_srs",
#             "EPSG:3857",
#             "-r",
#             "bilinear",
#             input_file,
#             reprojected_file,
#         ]
#         subprocess.run(cmd, check=True)

#         # Apply color ramp to the reprojected file
#         logging.info("Applying color ramp...")
#         color_ramp = create_fixed_color_ramp()
#         fixed_ramp_file = os.path.join(output_dir, f"{base_name}_color_ramp.txt")
#         write_color_ramp_file(color_ramp, fixed_ramp_file)

#         cmd = [
#             "gdaldem",
#             "color-relief",
#             "-alpha",
#             reprojected_file,
#             fixed_ramp_file,
#             output_file,
#         ]
#         subprocess.run(cmd, check=True)

#         # Generate tiles from the reprojected and colored file
#         os.environ["GDAL_NUM_THREADS"] = str(NUM_CORES)

#         with tqdm(desc="Generating tiles") as pbar:
#             for zoom in range(ZOOM_RANGE[0], ZOOM_RANGE[1] + 1):
#                 zoom_dir = os.path.join(tiles_dir, str(zoom))
#                 os.makedirs(zoom_dir, exist_ok=True)

#                 logging.info(f"Processing zoom level {zoom}")
#                 cmd = [
#                     "gdal2tiles.py",
#                     "--xyz",
#                     "-z",
#                     f"{zoom}",
#                     "-w",
#                     "none",
#                     "--processes",
#                     str(NUM_CORES),
#                     "-r",
#                     "average",
#                     "--profile",
#                     "mercator",
#                     output_file,
#                     tiles_dir,
#                 ]

#                 result = subprocess.run(cmd, capture_output=True, text=True)
#                 if result.returncode != 0:
#                     logging.error(f"Tile generation error: {result.stderr}")
#                     raise subprocess.CalledProcessError(result.returncode, cmd)

#                 # Count tiles
#                 tiles_count = 0
#                 for root, _, files in os.walk(zoom_dir):
#                     tiles_count += sum(1 for f in files if f.endswith(".png"))
#                 pbar.update(tiles_count)
#                 logging.info(f"Generated {tiles_count} tiles at zoom level {zoom}")

#         # Clean up intermediate files
#         os.remove(reprojected_file)
#         os.remove(fixed_ramp_file)

#         return True

#     except Exception as e:
#         logging.error(f"Error processing {input_file}: {str(e)}")
#         return False

def main():
    # Get all input files
    input_files = [
        os.path.join(INPUT_DIR, f) 
        for f in os.listdir(INPUT_DIR) 
        if f.endswith(".tif")
    ]
    
    # Group files by location
    groups = group_files_by_location(input_files)
    logging.info(f"Split files into {len(groups)} geographical groups")
    
    # Process groups in parallel
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor() as executor:
        futures = []
        for group_files in groups.values():
            futures.append(
                executor.submit(
                    process_group, 
                    group_files, 
                    PROCESSED_DIR, 
                    ZOOM_RANGE
                )
            )
        
        # Wait for all groups to complete
        for future in tqdm(futures):
            future.result()


if __name__ == "__main__":
    main()
