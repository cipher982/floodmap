import json
import requests
import sys
import datetime
import threading
import re
import dotenv
import os

dotenv.load_dotenv()

path = "./downloads"  # Set the download directory
maxthreads = 5
sema = threading.Semaphore(value=maxthreads)
threads = []

def sendRequest(url, data=None, apiKey=None):
    headers = {"X-Auth-Token": apiKey} if apiKey else {}
    response = requests.post(url, json=data, headers=headers) if data else requests.get(url, headers=headers)
    if response.status_code not in [200, 201]:
        print(f"Error {response.status_code}: {response.text}")
        return None  # Return None instead of exiting
    return response.json().get("data", response.json())


def downloadFile(url):
    sema.acquire()
    try:
        response = requests.get(url, stream=True)
        filename = re.findall("filename=\"?([^\";]+)", response.headers.get("content-disposition", ""))[0]
        with open(f"{path}/{filename}", "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")
    finally:
        sema.release()

def runDownload(url):
    thread = threading.Thread(target=downloadFile, args=(url,))
    threads.append(thread)
    thread.start()

if __name__ == "__main__":
    serviceUrl = "https://m2m.cr.usgs.gov/api/json/stable/"
    payload = {"username": os.getenv("USGS_USER"), "token": os.getenv("USGS_TOKEN")}
    apiKey = sendRequest(f"{serviceUrl}login-token", payload)
    if apiKey is None:
        print("Failed to authenticate. Please check your credentials and API endpoint.")
        sys.exit(1)


    datasetName = "SRTM_GL1"
    spatialFilter = {
        "filterType": "mbr",
        "lowerLeft": {"latitude": 9.4491, "longitude": -153.9844},
        "upperRight": {"latitude": 58.9500, "longitude": -40.2539}
    }
    temporalFilter = {"start": "2000-01-01", "end": "2023-12-31"}

    print("Verifying API key...")
    datasets = sendRequest(f"{serviceUrl}dataset-catalog", {"datasetName": "SRTM_GL1"}, apiKey)
    if datasets is None:
        print("Failed to retrieve dataset catalog. Please check your API key and permissions.")
        sendRequest(f"{serviceUrl}logout", data=None, apiKey=apiKey)
        sys.exit(1)

    print(f"Dataset catalog response: {json.dumps(datasets, indent=2)}")

    searchPayload = {
        "datasetName": datasetName,
        "spatialFilter": spatialFilter,
        "temporalFilter": temporalFilter
    }
    print(f"Searching for dataset with payload: {json.dumps(searchPayload, indent=2)}")
    datasets = sendRequest(f"{serviceUrl}dataset-search", searchPayload, apiKey)
    print(f"Raw dataset search response: {json.dumps(datasets, indent=2)}")
    
    if not datasets:
        print("No datasets found. Check your search parameters and API key.")
        sendRequest(f"{serviceUrl}logout", data=None, apiKey=apiKey)
        sys.exit(1)

    for dataset in datasets:
        if dataset["datasetAlias"] != datasetName:
            continue
        scenePayload = {
            "datasetName": datasetName,
            "maxResults": 50000,
            "startingNumber": 1,
            "sceneFilter": {
                "spatialFilter": spatialFilter,
                "acquisitionFilter": temporalFilter
            }
        }
        scenes = sendRequest(f"{serviceUrl}scene-search", scenePayload, apiKey)
        if scenes.get("recordsReturned", 0) > 0:
            sceneIds = [s["entityId"] for s in scenes["results"]]
            downloadOptions = sendRequest(f"{serviceUrl}download-options", {"datasetName": datasetName, "entityIds": sceneIds}, apiKey)
            downloads = [{"entityId": d["entityId"], "productId": d["id"]} for d in downloadOptions if d.get("available")]
            if downloads:
                label = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                requestPayload = {"downloads": downloads, "label": label}
                requestResults = sendRequest(f"{serviceUrl}download-request", requestPayload, apiKey)
                available = requestResults.get("availableDownloads", [])
                for download in available:
                    runDownload(download["url"])

    for thread in threads:
        thread.join()

    sendRequest(f"{serviceUrl}logout", data=None, apiKey=apiKey)
    print("Download complete and logged out.")