import os
import logging
import requests
from tqdm import tqdm
import os.path as osp
from concurrent.futures import ThreadPoolExecutor


class DownloadError(Exception):
    pass


def download_file(url, local_path, expected_size=None):
    """
    Download a single file with progress bar and size verification.
    """
    try:
        # Make directory if it doesn't exist
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # Stream download with progress bar
        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        if total_size == 0:
            raise DownloadError(f"Content length is 0 for {url}")

        with open(local_path, "wb") as f:
            with tqdm(
                total=total_size,
                unit="iB",
                unit_scale=True,
                desc=os.path.basename(local_path),
            ) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    pbar.update(size)

        # Verify file size
        actual_size = os.path.getsize(local_path)
        if expected_size and actual_size != expected_size:
            raise DownloadError(
                f"Size mismatch for {local_path}: expected {expected_size}, got {actual_size}"
            )

        # Write size verification file
        with open(f"{local_path}.size", "w") as f:
            f.write(str(actual_size))

        return True

    except Exception as e:
        if os.path.exists(local_path):
            os.remove(local_path)
        raise DownloadError(f"Failed to download {url}: {str(e)}")


def download_scenes(downloads, download_meta, download_path, max_workers=5):
    """Download multiple scenes concurrently with proper progress tracking.
    """
    def download_with_retry(download):
        # Get download identifiers
        download_id = str(download.get("downloadId"))
        meta = download_meta.get(download_id, {})
        url = download.get("url") or meta.get("url")
        
        if not url:
            logging.error(f"No URL found for download {download_id}")
            return download_id
            
        # Create unique filename
        display_id = meta.get("displayId") or download.get("displayId") or download_id
        local_path = osp.join(download_path, f"{display_id}_{download_id}.tar")
        expected_size = meta.get("filesize") or download.get("filesize")

        # Attempt download with retries
        for attempt in range(3):
            try:
                download_file(url, local_path, expected_size)
                return None
            except DownloadError as e:
                logging.warning(
                    f"Download attempt {attempt + 1}/3 failed for {display_id}: {e}"
                )
                if attempt == 2:  # Last attempt failed
                    return download_id

    # Execute downloads in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(download_with_retry, downloads))
        
    # Return list of failed download IDs
    return [r for r in results if r is not None]


def available_locally(download, download_meta, download_path):
    """Check if a file is already downloaded and valid."""
    download_id = str(download.get("downloadId", download.get("entityId")))
    meta = download_meta.get(download_id, {})
    display_id = meta.get("displayId", download_id)
    local_path = osp.join(download_path, f"{display_id}.tar")

    if not os.path.exists(local_path):
        return False

    size_file = f"{local_path}.size"
    if not os.path.exists(size_file):
        return False

    with open(size_file) as f:
        expected_size = int(f.read().strip())

    return os.path.getsize(local_path) == expected_size
