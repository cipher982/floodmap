import json
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
        if "downloadId" in order:
            # Check download status before removal
            status = order.get("status", "").lower()
            if status in ["failed", "expired"]:
                logging.info(f"Skipping removal of {status} download: {order['downloadId']}")
                return True, order["downloadId"]
                
            response = m2m._send_request(
                "download-remove", {"downloadId": order["downloadId"]}
            )
            if response:
                return True, order["downloadId"]
            logging.error(f"Failed to remove download ID: {order['downloadId']}")
        return False, f"No downloadId found for order with label {order.get('label')}"
    except Exception as e:
        return False, f"Error clearing download {order.get('downloadId')}: {str(e)}"


def clear_pending_downloads(m2m, max_workers):
    """Clear pending downloads concurrently with progress tracking"""
    logging.info("Fetching pending downloads...")

    download_orders = m2m.downloadSearch()
    initial_count = len(download_orders)
    logging.info(f"Found {initial_count} pending downloads")

    if not download_orders:
        logging.info("No pending download orders found")
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


# Example usage
# spatial_filter = {
#     "filterType": "mbr",
#     "lowerLeft": {"latitude": 9.4491, "longitude": -153.9844},
#     "upperRight": {"latitude": 58.9500, "longitude": -40.2539},
# }


def main():
    m2m = M2M(username=os.getenv("USGS_USER"), token=os.getenv("USGS_TOKEN"))
    logger = logging.getLogger(__name__)

    try:
        # Clear any pending downloads first
        clear_pending_downloads(m2m, 10)

        # Define area of interest (San Francisco Bay Area)
        spatial_filter = {
            "filterType": "mbr",
            "lowerLeft": {"latitude": 37.5, "longitude": -122.5},
            "upperRight": {"latitude": 37.8, "longitude": -122.2},
        }

        # 1. Search for scenes in the area
        scenes = m2m.searchScenes("srtm_v3", spatial_filter=spatial_filter)
        logger.info(f"Found {len(scenes.get('results', [])):,} scenes")

        # 2. Get download options first to filter for GeoTIFF
        download_options = m2m._send_request(
            "download-options",
            {
                "datasetName": "srtm_v3",
                "entityIds": [scene["entityId"] for scene in scenes.get("results", [])],
            },
        )

        # Filter for GeoTIFF only
        geotiff_downloads = [
            product["entityId"]
            for product in download_options
            if product["productCode"] == "D539"  # GeoTIFF format
        ]

        # 3. Create list with only GeoTIFF scenes
        list_id = "download_srtm_batch"
        m2m._send_request(
            "scene-list-add",
            {
                "listId": list_id,
                "datasetName": "srtm_v3",
                "entityIds": geotiff_downloads,
            },
        )

        # 4. Request the downloads
        downloads = [
            {"entityId": entity_id, "productId": "D539"}
            for entity_id in geotiff_downloads
        ]

        download_response = m2m._send_request(
            "download-request", {"downloads": downloads, "label": list_id}
        )

        # Log and start downloads
        if download_response.get("availableDownloads"):
            for download in download_response["availableDownloads"]:
                logger.info(f"Available download URL: {download.get('url')}")

        downloaded = m2m.download_scenes(
            dataset_name="srtm_v3",
            spatial_filter=spatial_filter,
            download_path="/Volumes/T9/srtm",
        )
        logger.info(f"Successfully downloaded {len(downloaded):,} scenes")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        m2m.logout()
        logger.info("Logged out")


if __name__ == "__main__":
    main()
