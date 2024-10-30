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


INPUT_DIR = os.getenv("INPUT_DIR")
OUTPUT_DIR = os.getenv("OUTPUT_DIR")
COLOR_RAMP = os.getenv("COLOR_RAMP")
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

        # Create color ramp
        color_ramp = create_fixed_color_ramp()
        fixed_ramp_file = os.path.join(output_dir, f"{base_name}_color_ramp.txt")
        write_color_ramp_file(color_ramp, fixed_ramp_file)

        # Add this section here - before the tile generation
        logging.info("Applying color ramp...")
        cmd = [
            "gdaldem",
            "color-relief",
            "-alpha",
            input_file,
            fixed_ramp_file,
            output_file
        ]
        subprocess.run(cmd, check=True)

        os.environ["GDAL_NUM_THREADS"] = str(NUM_CORES)

        with tqdm(desc="Generating tiles") as pbar:
            for zoom in range(ZOOM_RANGE[0], ZOOM_RANGE[1] + 1):
                zoom_dir = os.path.join(tiles_dir, str(zoom))
                os.makedirs(zoom_dir, exist_ok=True)

                logging.info(f"Processing zoom level {zoom}")
                cmd = [
                    "gdal2tiles.py",
                    "--xyz",
                    "-z",
                    f"{zoom}",
                    "-w",
                    "none",
                    "--processes",
                    str(NUM_CORES),
                    "-r",
                    "average",
                    output_file,
                    tiles_dir,
                ]

                _ = subprocess.run(cmd, check=True, capture_output=True, text=True)

                # Count actual tiles generated
                tiles_count = 0
                for root, _, files in os.walk(zoom_dir):
                    tiles_count += sum(1 for f in files if f.endswith(".png"))
                pbar.update(tiles_count)
                logging.info(f"Generated {tiles_count} tiles at zoom level {zoom}")

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
