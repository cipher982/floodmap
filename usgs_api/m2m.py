import logging
import requests
import json
import time
from pathlib import Path
from tqdm import tqdm
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor


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

    def _create_session(self):
        """Create a requests session with retry strategy"""
        session = requests.Session()
        retries = Retry(
            total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def datasetFilters(self, **args):
        """Create dataset filters from metadata info"""
        return {"metadataFilter": args.get("metadataInfo", [])}

    def _download_file(self, download, download_dir, session):
        """Download a single file with progress bar"""
        try:
            filename = download["url"].split("/")[-1]
            file_path = download_dir / filename

            # Skip if file already exists and has content
            if file_path.exists() and file_path.stat().st_size > 0:
                logger.info(f"Skipping existing file: {filename}")
                return file_path, None

            response = session.get(download["url"], stream=True)
            response.raise_for_status()

            filename = (
                response.headers["content-disposition"]
                .split("filename=")[-1]
                .strip('"')
            )
            file_path = download_dir / filename

            total_size = int(response.headers.get("content-length", 0))
            if total_size == 0:
                raise Exception("Content length is 0")

            with open(file_path, "wb") as f:
                with tqdm(
                    total=total_size, unit="iB", unit_scale=True, desc=filename
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        size = f.write(chunk)
                        pbar.update(size)

            return file_path, None
        except Exception as e:
            if file_path.exists():
                file_path.unlink()
            return download["url"], str(e)

    def download_scenes(
        self,
        dataset_name,
        spatial_filter,
        max_results=100,
        download_path="downloads",
        max_workers=5,
    ):
        """Download scenes for a given dataset and spatial filter."""
        if dataset_name not in self.datasets:
            raise M2MError(
                f"Dataset {dataset_name} not found. Available: {list(self.datasets.keys())}"
            )

        # Search for scenes
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
        else:
            logger.info(f"Found {len(scenes['results']):,} scenes")

        # Prepare download request
        list_id = f"download_{dataset_name}"
        entity_ids = [scene["entityId"] for scene in scenes["results"]]

        self._send_request(
            "scene-list-add",
            {"listId": list_id, "datasetName": dataset_name, "entityIds": entity_ids},
        )

        # Get download options and prepare download request
        download_options = self._send_request(
            "download-options", {"datasetName": dataset_name, "listId": list_id}
        )
        if not download_options:
            logger.info("No download options available.")
            return []

        downloads = [
            {"entityId": product["entityId"], "productId": product["id"]}
            for product in download_options
            if product["productCode"] == "D539"  # Only GeoTIFF format
        ]

        # Request downloads
        download_request = self._send_request(
            "download-request", {"downloads": downloads[:max_results], "label": list_id}
        )
        if not download_request.get("preparingDownloads"):
            logger.info("No downloads are being prepared.")
            return []

        # Wait for downloads to become available
        available_downloads = []
        with tqdm(total=len(downloads), desc="Waiting for downloads") as pbar:
            while len(available_downloads) < len(downloads):
                download_status = self._send_request(
                    "download-retrieve", {"label": list_id}
                )
                available_downloads = download_status.get("available", [])
                if available_downloads:
                    pbar.update(len(available_downloads) - pbar.n)
                time.sleep(5)  # Wait 5 seconds before checking again

        # Create download directory
        download_dir = Path(download_path)
        download_dir.mkdir(parents=True, exist_ok=True)
        session = self._create_session()

        self._interrupted = False
        downloaded_files = []
        failed_downloads = []
        skipped_files = []

        # Main download loop
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        self._download_file, download, download_dir, session
                    )
                    for download in available_downloads
                ]

                for future in concurrent.futures.as_completed(futures):
                    if self._interrupted:
                        executor.shutdown(wait=False)
                        break
                    result, error = future.result()
                    if error:
                        failed_downloads.append((result, error))
                        logger.error(f"Failed to download {result}: {error}")
                    elif isinstance(result, Path) and result.exists():
                        if result not in downloaded_files:
                            downloaded_files.append(result)

            logger.info(
                f"Downloaded: {len(downloaded_files)}, Skipped: {len(skipped_files)}, Failed: {len(failed_downloads)}"
            )
            return downloaded_files

        except KeyboardInterrupt:
            self._interrupted = True
            logger.info("Interrupting downloads...")
            return downloaded_files

        return downloaded_files

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

    def get_rate_limits(self):
        try:
            response = self._send_request("rate-limit-summary")

            # Extract and format the response data for readability
            formatted_response = (
                "Rate Limits Full Response:\n"
                "Initial Limits:\n"
                f"  - Recent Download Count: {response['initialLimits'][0]['recentDownloadCount']}\n"
                f"  - Pending Download Count: {response['initialLimits'][0]['pendingDownloadCount']}\n"
                f"  - Unattempted Download Count: {response['initialLimits'][0]['unattemptedDownloadCount']}\n\n"
                "Remaining Limits:\n"
                "  - User Limits:\n"
                f"      - Username: {response['remainingLimits'][0]['username']}\n"
                f"      - Recent Download Count: {response['remainingLimits'][0]['recentDownloadCount']}\n"
                f"      - Pending Download Count: {response['remainingLimits'][0]['pendingDownloadCount']}\n"
                f"      - Unattempted Download Count: {response['remainingLimits'][0]['unattemptedDownloadCount']}\n"
                "  - IP Limits:\n"
                f"      - IP Address: {response['remainingLimits'][1]['ipAddress']}\n"
                f"      - Recent Download Count: {response['remainingLimits'][1]['recentDownloadCount']}\n"
                f"      - Pending Download Count: {response['remainingLimits'][1]['pendingDownloadCount']}\n"
                f"      - Unattempted Download Count: {response['remainingLimits'][1]['unattemptedDownloadCount']}\n\n"
                f"Recent Download Counts: {response.get('recentDownloadCounts', [])}\n"
            )

            return formatted_response

        except Exception as e:
            raise M2MError(f"Failed to get rate limits: {str(e)}")

    def logout(self):
        """Logout from the API"""
        if self.api_key:
            self._send_request("logout")
            self.api_key = None
