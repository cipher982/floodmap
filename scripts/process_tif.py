import os
import subprocess
import signal
from concurrent.futures import ProcessPoolExecutor, as_completed
import tqdm
import configparser
import logging

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
MIN_ZOOM = config.getint("Tiles", "min_zoom", fallback=8)
MAX_ZOOM = config.getint("Tiles", "max_zoom", fallback=14)


def process_tif_file(input_file, output_dir):
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}_colored.tif")
        tiles_dir = os.path.join(output_dir, "tiles", base_name)

        # Generate color relief
        subprocess.run(
            ["gdaldem", "color-relief", input_file, COLOR_RAMP, output_file],
            check=True,
            capture_output=True,
        )

        # Generate tiles
        subprocess.run(
            [
                "gdal2tiles.py",
                "-z",
                f"{MIN_ZOOM}-{MAX_ZOOM}",
                "--xyz",
                output_file,
                tiles_dir,
            ],
            check=True,
            capture_output=True,
        )

        logging.info(f"Processed {base_name}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Error processing {input_file}: {e}")
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

    logging.info(f"Found {len(files_to_process)} .tif files to process")

    # Set up signal handling
    original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)

    with ProcessPoolExecutor() as executor:
        signal.signal(signal.SIGINT, original_sigint_handler)
        try:
            with tqdm.tqdm(
                total=len(files_to_process), desc="Processing TIF files"
            ) as pbar:
                futures = {
                    executor.submit(process_tif_file, f, OUTPUT_DIR): f
                    for f in files_to_process
                }
                for future in as_completed(futures):
                    if future.result():
                        pbar.update(1)
                    else:
                        pbar.total -= 1
        except KeyboardInterrupt:
            logging.warning("Caught KeyboardInterrupt, cancelling tasks...")
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False)
            logging.info("All tasks cancelled")
            return

    logging.info("Processing complete")


if __name__ == "__main__":
    main()
