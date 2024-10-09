import os
import subprocess
import numpy as np
from osgeo import gdal
import configparser
import logging

gdal.UseExceptions()

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Read configuration
config = configparser.ConfigParser()
config.read("config.ini")

INPUT_DIR = config.get("Paths", "input_dir", fallback="./data")
OUTPUT_DIR = config.get("Paths", "output_dir", fallback="./processed_data")
COLOR_RAMP = config.get("Files", "color_ramp", fallback="./scripts/color_ramp.txt")
# Update these constants
ZOOM_RANGE = (10, 15)

MIN_ELEVATION = 0
MAX_ELEVATION = 20  # feet

NUM_CORES = 10


def merge_tif_files(input_files, output_file):
    """Merge multiple TIF files into a single file."""
    logging.info(f"Merging {len(input_files)} TIF files into {output_file}")
    merge_command = ["gdal_merge.py", "-o", output_file, "-of", "GTiff"]
    merge_command.extend(input_files)
    subprocess.run(merge_command, check=True, capture_output=True, text=True)
    logging.info("Merge complete")


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
    colors = [elevation_to_color(e, min_elevation, max_elevation) for e in elevations]
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


def process_tif_file(input_file, output_dir):
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}_colored.tif")
        tiles_dir = os.path.join(output_dir, "tiles")

        # Get elevation range and geotransform
        ds = gdal.Open(input_file)
        band = ds.GetRasterBand(1)
        min_elevation, max_elevation = band.ComputeRasterMinMax()
        geotransform = ds.GetGeoTransform()

        # Calculate and log the bounding box
        width = ds.RasterXSize
        height = ds.RasterYSize
        lon_min = geotransform[0]
        lat_max = geotransform[3]
        lon_max = lon_min + width * geotransform[1]
        lat_min = lat_max + height * geotransform[5]

        logging.info(f"File: {base_name}")
        logging.info(f"Bounding Box: ({lat_min}, {lon_min}) to ({lat_max}, {lon_max})")
        logging.info(f"Elevation range: {min_elevation} to {max_elevation}")

        # Create dynamic color ramp
        # color_ramp = create_dynamic_color_ramp(min_elevation, max_elevation)
        color_ramp = create_fixed_color_ramp()
        fixed_ramp_file = os.path.join(output_dir, f"{base_name}_color_ramp.txt")
        write_color_ramp_file(color_ramp, fixed_ramp_file)

        os.environ["GDAL_NUM_THREADS"] = str(NUM_CORES)

        # Generate color relief using the dynamic color ramp
        subprocess.run(
            [
                "gdaldem",
                "color-relief",
                "-co",
                "TILED=YES",
                "-co",
                "COMPRESS=LZW",
                "-co",
                "BIGTIFF=YES",
                input_file,
                fixed_ramp_file,
                output_file,
            ],
            check=True,
            capture_output=True,
        )

        for zoom in range(ZOOM_RANGE[0], ZOOM_RANGE[1] + 1):
            zoom_dir = os.path.join(tiles_dir, str(zoom))
            os.makedirs(zoom_dir, exist_ok=True)
            cmd = [
                "gdal2tiles.py",
                "--xyz",
                "-z",
                f"{zoom}",  # Changed to process one zoom level at a time
                "-w",
                "none",
                "--processes",
                str(NUM_CORES),  # Use all available cores
                "-r",
                "average",  # Use average resampling for better quality
                output_file,
                tiles_dir,
            ]
            logging.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logging.info(f"Command output: {result.stdout}")

            # Log generated tiles
            generated_tiles = []
            for root, dirs, files in os.walk(zoom_dir):
                for file in files:
                    if file.endswith(".png"):
                        tile_path = os.path.relpath(os.path.join(root, file), zoom_dir)
                        generated_tiles.append(tile_path)

        logging.info(f"Processed {base_name}")

        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error processing {input_file}: {e}")
        logging.error(f"Command output: {e.stdout}")
        logging.error(f"Command error: {e.stderr}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error processing {input_file}: {e}")
        return False


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files_to_process = [
        os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR) if f.endswith(".tif")
    ]

    if not files_to_process:
        logging.warning(f"No .tif files found in {INPUT_DIR}")
        return

    # Merge all input files
    merged_file = os.path.join(OUTPUT_DIR, "merged_input.tif")
    merge_tif_files(files_to_process, merged_file)

    # Process the merged file
    process_tif_file(merged_file, OUTPUT_DIR)


if __name__ == "__main__":
    main()
