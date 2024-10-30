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
ZOOM_RANGE = (10, 12)

MIN_ELEVATION = 0
MAX_ELEVATION = 20  # feet

NUM_CORES = 12
MEMORY_LIMIT = 32768  # 32GB RAM allocation for GDAL


def merge_tif_files(input_files, output_file):
    """Merge multiple TIF files into a single file using batches."""
    total_files = len(input_files)
    logging.info(f"Merging {total_files} TIF files into {output_file}")

    batch_size = 50
    batched_files = [
        input_files[i : i + batch_size] for i in range(0, total_files, batch_size)
    ]

    temp_vrt = output_file.replace(".tif", "_temp.vrt")

    base_command = ["gdalbuildvrt", "-resolution", "highest", "-r", "nearest", temp_vrt]

    with tqdm(total=total_files, desc="Merging TIF files") as pbar:
        for i, batch in enumerate(batched_files):
            merge_command = base_command + batch

            try:
                result = subprocess.run(merge_command, capture_output=True, text=True)
                if result.returncode != 0:
                    logging.error(f"Error in merge batch {i+1}: {result.stderr}")
                    raise subprocess.CalledProcessError(
                        result.returncode, merge_command, result.stdout, result.stderr
                    )
                pbar.update(len(batch))
            except subprocess.CalledProcessError as e:
                logging.error(f"Error in merge batch {i+1}: {e.stderr}")
                raise

        # Convert final VRT to GeoTIFF
        logging.info("Converting VRT to GeoTIFF...")
        translate_command = [
            "gdal_translate",
            "-of",
            "GTiff",
            "--config",
            "GDAL_NUM_THREADS",
            str(NUM_CORES),
            "--config",
            "GDAL_CACHEMAX",
            str(MEMORY_LIMIT),
            temp_vrt,
            output_file,
        ]

        subprocess.run(translate_command, check=True)
        os.remove(temp_vrt)  # Clean up temporary VRT file

    logging.info("Merge complete")

    # After merge is complete, log the bounds of merged file
    ds = gdal.Open(output_file)
    geotransform = ds.GetGeoTransform()
    width = ds.RasterXSize
    height = ds.RasterYSize
    
    lon_min = geotransform[0]
    lat_max = geotransform[3]
    lon_max = lon_min + width * geotransform[1]
    lat_min = lat_max + height * geotransform[5]
    
    logging.info("Merged file bounds:")
    logging.info(f"Latitude: {lat_min:.4f}°N to {lat_max:.4f}°N")
    logging.info(f"Longitude: {lon_min:.4f}°W to {lon_max:.4f}°W")


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
    files = [f for f in os.listdir(input_dir) if f.endswith('.tif')]
    
    all_bounds = []
    lat_min_global = float('inf')
    lat_max_global = float('-inf')
    lon_min_global = float('inf')
    lon_max_global = float('-inf')
    
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
        
        all_bounds.append({
            'file': file,
            'lat_min': lat_min,
            'lat_max': lat_max,
            'lon_min': lon_min,
            'lon_max': lon_max
        })
        
        # Update global bounds
        lat_min_global = min(lat_min_global, lat_min)
        lat_max_global = max(lat_max_global, lat_max)
        lon_min_global = min(lon_min_global, lon_min)
        lon_max_global = max(lon_max_global, lon_max)
    
    # Sort by latitude and longitude for better organization
    all_bounds.sort(key=lambda x: (-x['lat_max'], x['lon_min']))
    
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
    logging.info(f"First 3 latitude ranges: {[f'{x[0]}-{x[1]}N' for x in lat_ranges[:3]]}")
    logging.info(f"First 3 longitude ranges: {[f'{x[0]}-{x[1]}W' for x in lon_ranges[:3]]}")
    
    return all_bounds


def process_tif_file(input_file, output_dir):
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}_colored.tif")
        tiles_dir = os.path.join(output_dir, "tiles")

        # Get elevation range and geotransform
        ds = gdal.Open(input_file)
        logging.info(f"Input projection: {ds.GetProjection()}")
        
        # First, reproject to Web Mercator (EPSG:3857)
        reprojected_file = os.path.join(output_dir, f"{base_name}_mercator.tif")
        logging.info("Reprojecting to Web Mercator...")
        cmd = [
            "gdalwarp",
            "-s_srs", "EPSG:4326",
            "-t_srs", "EPSG:3857",
            "-r", "bilinear",
            input_file,
            reprojected_file
        ]
        subprocess.run(cmd, check=True)

        # Apply color ramp to the reprojected file
        logging.info("Applying color ramp...")
        color_ramp = create_fixed_color_ramp()
        fixed_ramp_file = os.path.join(output_dir, f"{base_name}_color_ramp.txt")
        write_color_ramp_file(color_ramp, fixed_ramp_file)
        
        cmd = [
            "gdaldem",
            "color-relief",
            "-alpha",
            reprojected_file,
            fixed_ramp_file,
            output_file
        ]
        subprocess.run(cmd, check=True)

        # Generate tiles from the reprojected and colored file
        os.environ["GDAL_NUM_THREADS"] = str(NUM_CORES)
        
        with tqdm(desc="Generating tiles") as pbar:
            for zoom in range(ZOOM_RANGE[0], ZOOM_RANGE[1] + 1):
                zoom_dir = os.path.join(tiles_dir, str(zoom))
                os.makedirs(zoom_dir, exist_ok=True)

                logging.info(f"Processing zoom level {zoom}")
                cmd = [
                    "gdal2tiles.py",
                    "--xyz",
                    "-z", f"{zoom}",
                    "-w", "none",
                    "--processes", str(NUM_CORES),
                    "-r", "average",
                    "--profile", "mercator",
                    output_file,
                    tiles_dir,
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logging.error(f"Tile generation error: {result.stderr}")
                    raise subprocess.CalledProcessError(result.returncode, cmd)

                # Count tiles
                tiles_count = 0
                for root, _, files in os.walk(zoom_dir):
                    tiles_count += sum(1 for f in files if f.endswith(".png"))
                pbar.update(tiles_count)
                logging.info(f"Generated {tiles_count} tiles at zoom level {zoom}")

        # Clean up intermediate files
        os.remove(reprojected_file)
        os.remove(fixed_ramp_file)

        return True

    except Exception as e:
        logging.error(f"Error processing {input_file}: {str(e)}")
        return False


def main():
    bounds = analyze_tif_files(INPUT_DIR)

    # Ask for confirmation before proceeding
    response = input("\nProceed with processing? (y/n): ")
    if response.lower() != 'y':
        logging.info("Processing cancelled")
        return

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    files_to_process = [
        os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.endswith(".tif")
    ]

    if not files_to_process:
        logging.warning(f"No .tif files found in {INPUT_DIR}")
        return

    # Merge all input files
    merged_file = os.path.join(PROCESSED_DIR, "merged_input.tif")
    merge_tif_files(files_to_process, merged_file)

    # Process the merged file
    process_tif_file(merged_file, PROCESSED_DIR)


if __name__ == "__main__":
    main()
