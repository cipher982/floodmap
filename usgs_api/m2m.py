import logging
import requests
import json
import time
from pathlib import Path

from downloader import download_scenes
from filters import Filter


M2M_ENDPOINT = "https://m2m.cr.usgs.gov/api/api/json/stable/"
logging.getLogger("requests").setLevel(logging.WARNING)


class M2MError(Exception):
    pass


class M2M:
    """Simplified M2M EarthExplorer API focused on scene downloads."""

    def __init__(self, username=None, password=None, token=None):
        self.api_key = None
        self._authenticate(username, password, token)
        self.datasets = self._get_datasets()

    def _authenticate(self, username, password, token):
        """Authenticate with username + password or token"""
        if not username:
            username = self._get_stored_credentials().get("username")
            if not username:
                username = input("Enter your USGS username: ")

        if password:
            self._login_with_password(username, password)
        elif token:
            self._login_with_token(username, token)
        else:
            stored_token = self._get_stored_credentials().get("token")
            if stored_token:
                self._login_with_token(username, stored_token)
            else:
                token = input("Enter your USGS token: ")
                self._login_with_token(username, token)
                self._store_credentials(username, token)

    def _get_stored_credentials(self):
        """Get stored credentials from config file"""
        config_file = Path.home() / ".config" / "m2m_api" / "config.json"
        try:
            return json.load(open(config_file))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _store_credentials(self, username, token):
        """Store credentials in config file"""
        config_file = Path.home() / ".config" / "m2m_api" / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        json.dump(
            {"username": username, "token": token}, open(config_file, "w"), indent=4
        )

    def _login_with_password(self, username, password):
        """Login using password"""
        response = self._send_request(
            "login", {"username": username, "password": password}
        )
        self.api_key = response

    def _login_with_token(self, username, token):
        """Login using token"""
        response = self._send_request(
            "login-token", {"username": username, "token": token}
        )
        self.api_key = response

    def _get_datasets(self):
        """Get available datasets"""
        response = self._send_request("dataset-search")
        return {d["datasetAlias"]: d for d in response}

    def _send_request(self, endpoint, data=None):
        """Send request to M2M API"""
        headers = {"X-Auth-Token": self.api_key} if self.api_key else {}

        response = requests.post(
            f"{M2M_ENDPOINT}{endpoint}", json=data or {}, headers=headers, timeout=300
        )

        if response.status_code != 200:
            raise M2MError(f"API request failed: {response.text}")

        result = response.json()
        if not result.get("data") and result.get("errorCode"):
            raise M2MError(f"API error: {result['errorMessage']}")

        return result["data"]

    def datasetFilters(self, **args):
        """Create dataset filters from metadata info"""
        return {"metadataFilter": args.get("metadataInfo", [])}

    def download_scenes(
        self, dataset_name, spatial_filter, max_results=100, download_path="downloads"
    ):
        """
        Main method to search and download scenes for a given dataset and area.

        Args:
            dataset_name: Name of the dataset (e.g. "srtm_v3")
            spatial_filter: Dictionary with spatial filter parameters
            max_results: Maximum number of scenes to return
            download_path: Path where to save downloaded files
        """
        if dataset_name not in self.datasets:
            raise M2MError(
                f"Dataset {dataset_name} not found. Available datasets: {list(self.datasets.keys())}"
            )

        # Search for scenes
        logging.info(f"Searching for scenes in {dataset_name}...")
        scenes = self._send_request(
            "scene-search",
            {
                "datasetName": dataset_name,
                "maxResults": max_results,
                "sceneFilter": {"spatialFilter": spatial_filter},
            },
        )

        if not scenes["results"]:
            logging.info("No scenes found.")
            return []

        logging.info(f"Found {len(scenes['results']):,} scenes.")

        # Prepare download request
        entity_ids = [scene["entityId"] for scene in scenes["results"]]

        # Add scenes to download list
        list_id = f"download_{dataset_name}"
        self._send_request(
            "scene-list-add",
            {"listId": list_id, "datasetName": dataset_name, "entityIds": entity_ids},
        )

        # Get download options
        download_options = self._send_request(
            "download-options", {"datasetName": dataset_name, "listId": list_id}
        )
        logging.info(
            f"Download options received: {json.dumps(download_options, indent=2)}"
        )

        if not download_options:
            logging.info("No download options available.")
            return []

        # Request downloads
        downloads = []
        for product in download_options:
            downloads.append(
                {"entityId": product["entityId"], "productId": product["id"]}
            )
        logging.info(f"Requesting downloads for: {json.dumps(downloads, indent=2)}")

        download_request = self._send_request(
            "download-request", {"downloads": downloads, "label": list_id}
        )
        json_response = json.dumps(download_request, indent=2)
        logging.info(f"Download request response: {json_response}")

        # Enhanced download preparation handling
        if download_request.get("preparingDownloads"):
            logging.info("Downloads are being prepared. Waiting for them to be ready...")
            max_attempts = 20  # Increased from 10
            wait_time = 60  # Increased from 30
            
            for attempt in range(max_attempts):
                search_result = self._send_request("download-search", {"label": list_id})
                
                if search_result:
                    # Check if all downloads are actually ready
                    all_ready = all(
                        download.get("status", "").lower() == "available" 
                        for download in search_result
                    )
                    
                    if all_ready:
                        downloads = search_result
                        logging.info(f"All downloads are ready after {attempt + 1} attempts")
                        break
                    else:
                        logging.info("Some downloads still preparing...")
                
                if attempt < max_attempts - 1:
                    logging.info(f"Downloads not ready, waiting {wait_time} seconds...")
                    time.sleep(wait_time)
            else:
                logging.error("Downloads failed to prepare after maximum attempts")
                return []

        logging.info(f"Available downloads: {json.dumps(downloads, indent=2)}")

        # Get download metadata
        download_meta = {}
        search_result = self._send_request("download-search", {"label": list_id})
        logging.info(f"Download search result: {json.dumps(search_result, indent=2)}")
        if search_result:
            for item in search_result:
                download_meta[str(item["downloadId"])] = item

        # Download files
        logging.info(f"Starting download of {len(downloads):,} files...")
        failed = download_scenes(downloads, download_meta, download_path)

        # Cleanup
        self._send_request("download-order-remove", {"label": list_id})

        if failed:
            logging.warning(f"Failed to download {len(failed)} scenes: {failed}")
        else:
            logging.info("All downloads completed successfully.")

        return [d for d in downloads if str(d.get("entityId")) not in failed]

    def downloadSearch(self, label=None):
        if label is not None:
            params = {"label": label}
            return self._send_request("download-search", params)
        return self._send_request("download-search")

    def searchScenes(self, datasetName, spatial_filter=None, max_results=100, **args):
        if datasetName not in self.datasets:
            raise M2MError(
                "Dataset {} not one of the available datasets {}".format(
                    datasetName, list(self.datasets.keys())
                )
            )

        # Construct request parameters with proper scene filter structure
        params = {
            "datasetName": datasetName,
            "maxResults": max_results,
            "sceneFilter": {},  # Add sceneFilter object
        }

        if spatial_filter:
            params["sceneFilter"]["spatialFilter"] = (
                spatial_filter  # Nest spatialFilter inside sceneFilter
            )

        scenes = self._send_request("scene-search", params)

        if scenes["totalHits"] > scenes["recordsReturned"]:
            logging.info(
                f"Found {scenes['totalHits']} total scenes, returning first {scenes['recordsReturned']}"
            )

        return scenes

    def downloadOrderRemove(self, label):
        """Remove a download order and verify removal"""
        params = {"label": label}
        response = self._send_request("download-order-remove", params)

        # Verify removal by checking if downloads with this label still exist
        remaining = self._send_request("download-search", {"label": label})
        if remaining:
            raise M2MError(f"Failed to remove downloads for label {label}")

        return response

    def logout(self):
        """Logout from the API"""
        if self.api_key:
            self._send_request("logout")
            self.api_key = None
