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
            # logging.info(f"Attempting to remove download ID: {order['downloadId']}")
            response = m2m._send_request("download-remove", {"downloadId": order["downloadId"]})
            if response:
                return True, order["downloadId"]
            else:
                logging.error(f"Failed to remove download ID: {order['downloadId']}")
        return False, f"No downloadId found for order with label {order.get('label')}"
    except Exception as e:
        return False, f"Error clearing download {order.get('downloadId')}: {str(e)}"

def clear_pending_downloads(m2m, max_workers=5):
    """Clear pending downloads concurrently with progress tracking"""
    logging.info("Fetching pending downloads...")
    try:
        download_orders = m2m.downloadSearch()
        initial_count = len(download_orders)
        logging.info(f"Found {initial_count} pending downloads")

        if not download_orders:
            logging.info("No pending download orders found")
            return
        
        # Store initial download IDs
        initial_ids = {order["downloadId"] for order in download_orders if "downloadId" in order}
        logging.info(f"Initial download IDs (first 5): {list(initial_ids)[:5]}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create partial function with m2m argument fixed
            fn = partial(remove_download, m2m)
            
            # Process downloads with progress bar
            futures = list(tqdm(
                executor.map(fn, download_orders),
                total=len(download_orders),
                desc="Clearing downloads"
            ))

            # Log results
            for success, msg in futures:
                if success:
                    logging.info(f"Successfully removed download ID: {msg}")
                else:
                    logging.error(msg)
    
        # Verify specific removals
        remaining_downloads = m2m.downloadSearch()
        remaining_ids = {order["downloadId"] for order in remaining_downloads if "downloadId" in order}
        
        removed_ids = initial_ids - remaining_ids
        logging.info(f"Successfully removed {len(removed_ids)} downloads")
        logging.info(f"Failed to remove {len(initial_ids - removed_ids)} downloads")

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
        clear_pending_downloads(m2m)

        spatial_filter = {
            "filterType": "mbr",
            "lowerLeft": {"latitude": 37.5, "longitude": -122.5},
            "upperRight": {"latitude": 37.8, "longitude": -122.2},
        }

        scenes = m2m.searchScenes("srtm_v3", spatial_filter=spatial_filter)
        logger.info(f"Found {len(scenes.get('results', [])):,} scenes")

        # Create a list ID for these scenes
        list_id = "download_srtm_batch"

        # Add scenes to a list
        entity_ids = [scene["entityId"] for scene in scenes.get("results", [])]
        m2m._send_request(
            "scene-list-add",
            {"listId": list_id, "datasetName": "srtm_v3", "entityIds": entity_ids},
        )

        # Now get download options
        download_options = m2m._send_request(
            "download-options", {"datasetName": "srtm_v3", "listId": list_id}
        )
        logger.info(
            f"Download options received: {json.dumps(download_options, indent=2)}"
        )

        # Add scenes to a list
        entity_ids = [scene["entityId"] for scene in scenes.get("results", [])]
        m2m._send_request(
            "scene-list-add",
            {"listId": list_id, "datasetName": "srtm_v3", "entityIds": entity_ids},
        )

        # Get download options
        download_options = m2m._send_request(
            "download-options", {"datasetName": "srtm_v3", "listId": list_id}
        )

        if download_options:
            # Request downloads
            downloads = [
                {"entityId": product["entityId"], "productId": product["id"]}
                for product in download_options
            ]

            download_response = m2m._send_request(
                "download-request", {"downloads": downloads, "label": list_id}
            )

            # Log available and preparing downloads
            if download_response.get("availableDownloads"):
                for download in download_response["availableDownloads"]:
                    logger.info(f"Available download URL: {download.get('url')}")

            if download_response.get("preparingDownloads"):
                for download in download_response["preparingDownloads"]:
                    logger.info(f"Preparing download URL: {download.get('url')}")

        # # Proceed with bulk download
        # downloaded = m2m.download_scenes(
        #     dataset_name="srtm_v3",
        #     spatial_filter=spatial_filter,
        #     download_path="/Volumes/T9/srtm",
        # )
        # logger.info(f"Successfully downloaded {len(downloaded):,} scenes")

    except Exception as e:
        logger.info(f"Unexpected error: {e}")
    finally:
        m2m.logout()
        logger.info("Logged out")


if __name__ == "__main__":
    main()
