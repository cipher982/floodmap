import logging
import os
import dotenv
from tqdm import tqdm
import concurrent.futures
from functools import partial

from m2m import M2M

dotenv.load_dotenv()

logging.basicConfig(level=logging.INFO)


def remove_download(m2m, order):
    """Helper function to remove a single download"""
    try:
        if "downloadId" not in order:
            return False, "No downloadId found"

        # Only attempt to remove active downloads
        status = order.get("statusText", "").lower()
        if status in ["removed", "failed", "expired"]:
            return True, f"Already {status}: {order['downloadId']}"

        response = m2m._send_request(
            "download-remove", {"downloadId": order["downloadId"]}
        )
        if response:
            return True, order["downloadId"]
        return False, f"Failed to remove {order['downloadId']}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def clear_pending_downloads(m2m, max_workers):
    """Clear pending downloads concurrently with progress tracking"""
    logging.info("Fetching pending downloads...")

    # Only get active downloads
    download_orders = [
        order
        for order in m2m.downloadSearch()
        if order.get("statusText", "").lower() not in ["removed", "failed", "expired"]
    ]

    initial_count = len(download_orders)
    logging.info(f"Found {initial_count} active pending downloads")

    if not download_orders:
        logging.info("No active pending downloads found")
        return

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            fn = partial(remove_download, m2m)
            futures = list(
                tqdm(
                    executor.map(fn, download_orders),
                    total=len(download_orders),
                    desc="Clearing downloads",
                )
            )

        # Count actual successful removals
        successful_removals = sum(1 for success, _ in futures if success)
        logging.info(f"Successfully removed {successful_removals} downloads")

        # Verify remaining downloads
        remaining_downloads = m2m.downloadSearch()
        if remaining_downloads:
            logging.warning(f"Still have {len(remaining_downloads)} pending downloads")

    except Exception as e:
        logging.error(f"Error in clear_pending_downloads: {str(e)}")


def main():
    m2m = M2M(username=os.getenv("USGS_USER"), token=os.getenv("USGS_TOKEN"))
    logger = logging.getLogger(__name__)

    try:
        # Clear any pending downloads first
        clear_pending_downloads(m2m, 10)

        # SF Bay Area
        spatial_filter = {
            "filterType": "mbr",
            "lowerLeft": {"latitude": 37.5, "longitude": -122.5},
            "upperRight": {"latitude": 37.8, "longitude": -122.2},
        }

        # USA
        spatial_filter = {
            "filterType": "mbr",
            "lowerLeft": {"latitude": 9.4491, "longitude": -153.9844},
            "upperRight": {"latitude": 58.9500, "longitude": -40.2539},
        }

        # 1. Search for scenes in the area
        scenes = m2m.searchScenes("srtm_v3", spatial_filter=spatial_filter)
        logger.info(f"Found {len(scenes.get('results', [])):,} scenes")

        downloaded = m2m.download_scenes(
            dataset_name="srtm_v3",
            spatial_filter=spatial_filter,
            download_path="/Volumes/T9/srtm",
        )
        if downloaded:
            logger.info(f"Successfully downloaded {len(downloaded):,} scenes")
        else:
            logger.warning("No scenes were downloaded")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        m2m.logout()
        logger.info("Logged out")


if __name__ == "__main__":
    main()
