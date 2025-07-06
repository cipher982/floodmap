import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import time

import fsspec
from tqdm import tqdm
from dotenv import load_dotenv
import rasterio

load_dotenv()

INPUT_DIR = os.getenv("INPUT_DIR", "./data/input")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Public S3 bucket hosting SRTM 1-ArcSecond COGs
SRTM_BUCKET = "s3://usgs-srtm/"
PREFIX = "SRTMGL1/"

VALIDATE = bool(os.getenv("VALIDATE_DEM", "1") == "1")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def list_cogs(fs: fsspec.AbstractFileSystem, prefix: str):
    """Return a list of COG URLs under the given prefix."""
    objects = fs.ls(prefix, detail=False)
    return [f"{SRTM_BUCKET}{key}" for key in objects if key.lower().endswith(".tif")]


def download_one(fs: fsspec.AbstractFileSystem, url: str, dest_dir: str, retries: int = 3):
    """Download a single COG with retry logic."""
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    dest_path = os.path.join(dest_dir, filename)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return False  # already exists

    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            fs.get(url, dest_path)

            # Optional validation step – ensure file opens and has GeoTransform
            if VALIDATE:
                try:
                    with rasterio.open(dest_path) as src:
                        _ = src.transform
                        _ = src.crs
                except Exception as val_err:
                    logging.error(f"Validation failed for {filename}: {val_err}")
                    os.remove(dest_path)
                    raise val_err

            return True
        except Exception as e:
            logging.warning(
                f"Failed to download {filename} (attempt {attempt}/{retries}): {e}"
            )
            if attempt == retries:
                logging.error(f"Giving up on {filename}")
                return False
            time.sleep(delay)
            delay *= 2  # exponential backoff


def main(max_workers: int = 8):
    os.makedirs(INPUT_DIR, exist_ok=True)

    fs = fsspec.filesystem("s3", anon=True, region_name=AWS_REGION)
    cog_urls = list_cogs(fs, PREFIX)
    logging.info(f"Found {len(cog_urls):,} COG files to consider")

    downloaded = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_one, fs, url, INPUT_DIR): url for url in cog_urls}
        for f in tqdm(as_completed(futures), total=len(futures), desc="Downloading COGs"):
            if f.result():
                downloaded += 1
    logging.info(f"Newly downloaded {downloaded} files. Stored in {INPUT_DIR}")


if __name__ == "__main__":
    main()