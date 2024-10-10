import os
import dotenv
from api import M2M  # Ensure api.py from m2m-api is in your project

dotenv.load_dotenv()


def main():
    m2m = M2M(username=os.getenv("USGS_USER"), token=os.getenv("USGS_TOKEN"))

    # Check available datasets
    print("Fetching available datasets...")
    # datasets = m2m.searchDatasets()
    dataset_name = "SRTM 1 Arc-Second Global"
    dataset_name = "srtm"

    srtm_datasets = [
        dataset
        for dataset in m2m.allDatasets
        if "abstractText" in dataset
        and dataset["abstractText"]
        and "srtm" in dataset["abstractText"].lower()
    ]
    if not srtm_datasets:
        print(f"Dataset '{dataset_name}' is not available.")
        return
    for dataset in srtm_datasets:
        print(f"Dataset Name: {dataset.get('datasetAlias', 'N/A')}")
    print(f"Dataset '{dataset_name}' is available.")

    dataset_name = "srtm_v3"

    # Create spatial filter using lat/lon
    spatial_filter = {
        "filterType": "mbr",
        "lowerLeft": {"latitude": 9.4491, "longitude": -153.9844},
        "upperRight": {"latitude": 58.9500, "longitude": -40.2539},
    }
    # Search for scenes
    print("Searching for scenes...")
    scenes = m2m.searchScenes(
        dataset_name,
        spatialFilter=spatial_filter,
        maxResults=15_000,
    )
    print(f"Found {len(scenes)} scenes.")
    # Retrieve and download scenes
    print("Retrieving scenes...")
    download_meta = m2m.retrieveScenes(dataset_name, scenes)
    print("Scenes retrieved.")

    return download_meta


if __name__ == "__main__":
    main()
