import logging
import os
import dotenv
from tqdm import tqdm

from m2m import M2M

dotenv.load_dotenv()

logging.basicConfig(level=logging.INFO)


def clear_pending_downloads(m2m, batch_size=100):
    """Clear pending downloads by label with better error handling"""
    logging.info("Fetching pending downloads...")
    try:
        download_orders = m2m.downloadSearch()
        if not download_orders:
            logging.info("No pending download orders found")
            return

        labels = set(order["label"] for order in download_orders if order.get("label"))
        failed_labels = []

        for label in tqdm(labels, desc="Clearing download labels"):
            try:
                m2m.downloadOrderRemove(label)
            except Exception as e:
                failed_labels.append(label)
                logging.error(f"Error clearing label {label}: {str(e)}")

        if failed_labels:
            logging.warning(f"Failed to clear labels: {failed_labels}")
            
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
        entity_ids = [scene["entityId"] for scene in scenes.get('results', [])]
        m2m._send_request(
            "scene-list-add",
            {
                "listId": list_id,
                "datasetName": "srtm_v3",
                "entityIds": entity_ids
            }
        )

        # Get download options
        download_options = m2m._send_request(
            "download-options",
            {
                "datasetName": "srtm_v3",
                "listId": list_id
            }
        )

        if download_options:
            # Request downloads
            downloads = [
                {
                    "entityId": product["entityId"],
                    "productId": product["id"]
                }
                for product in download_options
            ]

            download_response = m2m._send_request(
                "download-request",
                {
                    "downloads": downloads,
                    "label": list_id
                }
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


if __name__ == "__main__":
    main()
