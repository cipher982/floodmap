import logging
import os
import requests
import json
import time
from pathlib import Path
from tqdm import tqdm

# from downloader import download_scenes
# from filters import Filter


M2M_ENDPOINT = "https://m2m.cr.usgs.gov/api/api/json/stable/"
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


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
        logger.info(f"Searching for scenes in {dataset_name}...")
        scenes = self._send_request(
            "scene-search",
            {
                "datasetName": dataset_name,
                "maxResults": max_results,
                "sceneFilter": {"spatialFilter": spatial_filter},
            },
        )

        if not scenes["results"]:
            logger.info("No scenes found.")
            return []

        logger.info(f"Found {len(scenes['results']):,} scenes.")

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
        logger.info(
            f"Download options received: {json.dumps(download_options, indent=2)}"
        )

        if not download_options:
            logger.info("No download options available.")
            return []

        # Request downloads
        downloads = []
        for product in download_options:
            downloads.append(
                {"entityId": product["entityId"], "productId": product["id"]}
            )
        logger.info(f"Requesting downloads for: {json.dumps(downloads, indent=2)}")

        download_request = self._send_request(
            "download-request", {"downloads": downloads, "label": list_id}
        )
        json_response = json.dumps(download_request, indent=2)
        logger.info(f"Download request response: {json_response}")

        # In the download_scenes method, modify where we handle the preparingDownloads:
        if download_request.get("preparingDownloads"):
            logger.info(
                "Downloads are being prepared. Waiting for them to be ready..."
            )
            max_attempts = 10
            wait_time = 30

            for attempt in range(max_attempts):
                search_result = self._send_request(
                    "download-search", {"label": list_id}
                )

                if search_result:
                    # Filter for only relevant downloads and check their status
                    relevant_downloads = [
                        d
                        for d in search_result
                        if d.get("statusText", "").lower()
                        not in ["removed", "failed", "expired"]
                    ]

                    if not relevant_downloads:
                        logger.error("No active downloads found")
                        return []

                    all_ready = all(
                        d.get("statusText", "").lower() == "available"
                        for d in relevant_downloads
                    )

                    if all_ready:
                        # Get the download URLs for each download
                        for download in relevant_downloads:
                            download_id = str(download["downloadId"])
                            # Get the URL from the preparingDownloads list
                            matching_prep = next(
                                (
                                    d
                                    for d in download_request["preparingDownloads"]
                                    if str(d["downloadId"]) == download_id
                                ),
                                None,
                            )
                            if matching_prep:
                                download["url"] = matching_prep["url"]
                        downloads = relevant_downloads
                        logger.info(
                            f"All downloads are ready after {attempt + 1} attempts"
                        )
                        break
                    else:
                        ready_count = sum(
                            1
                            for d in relevant_downloads
                            if d.get("statusText", "").lower() == "available"
                        )
                        logger.info(
                            f"{ready_count}/{len(relevant_downloads)} downloads ready..."
                        )
                        time.sleep(wait_time)

        logger.info(f"Available downloads: {json.dumps(downloads, indent=2)}")

        # Extract direct URLs for GeoTIFF downloads
        geotiff_urls = [
            download["url"] 
            for download in downloads 
            if download["productCode"] == "D539"
        ]
        
        # Log URLs for manual download
        for url in geotiff_urls:
            logger.info(f"GeoTIFF direct download URL: {url}")

        # Download the URLs with tqdm and status tracking
        failed_downloads = []

        for url in geotiff_urls:
            local_filename = os.path.join(download_path, url.split("/")[-1])
            try:
                with requests.get(url, stream=True) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    with open(local_filename, "wb") as f, tqdm(
                        total=total_size,
                        unit="iB",
                        unit_scale=True,
                        desc=os.path.basename(local_filename),
                    ) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            size = f.write(chunk)
                            pbar.update(size)
                logger.info(f"Successfully downloaded {local_filename}")
            except Exception as e:
                logger.error(f"Failed to download {url}: {e}")
                failed_downloads.append(url)

        if failed_downloads:
            logger.warning(f"Failed to download {len(failed_downloads)} files: {failed_downloads}")
        else:
            logger.info("All downloads completed successfully.")


    def downloadSearch(self, label=None):
        """Search downloads, filtering out inactive ones by default"""
        params = {"label": label} if label else {}
        results = self._send_request("download-search", params)

        # Filter out inactive downloads
        active_downloads = [
            download
            for download in results
            if download.get("statusText", "").lower()
            not in ["removed", "failed", "expired"]
        ]
        return active_downloads

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
            logger.info(
                f"Found {scenes['totalHits']} total scenes, returning first {scenes['recordsReturned']}"
            )

        return scenes

    def downloadOrderRemove(self, label):
        """Permanently remove all downloads (including historical) for a label"""
        try:
            # Remove all downloads with this label, regardless of status
            self._send_request("download-order-remove", {"label": label})
            
            # Verify removal
            remaining = self._send_request("download-search", {"label": label})
            if remaining:
                logger.warning(f"Failed to fully remove downloads for label {label}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error removing downloads: {e}")
            return False

    def logout(self):
        """Logout from the API"""
        if self.api_key:
            self._send_request("logout")
            self.api_key = None
