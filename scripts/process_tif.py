import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
import tqdm

def process_tif_file(input_file, output_dir):
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(output_dir, f"{base_name}_colored.tif")
    
    # Generate color relief
    color_ramp = "color_ramp.txt"
    subprocess.run([
        "gdaldem", "color-relief", input_file, color_ramp, output_file
    ])
    
    # Generate tiles
    tiles_dir = os.path.join(output_dir, "tiles", base_name)
    os.makedirs(tiles_dir, exist_ok=True)
    subprocess.run([
        "gdal2tiles.py", "-z", "8-12", output_file, tiles_dir
    ])

def main():
    input_dir = "../data"
    output_dir = "../processed_data"
    os.makedirs(output_dir, exist_ok=True)

    files_to_process = [
        os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.endswith(".tif")
    ]

    with tqdm.tqdm(total=len(files_to_process), desc="Overall Progress") as pbar:
        with ProcessPoolExecutor() as executor:
            futures = [executor.submit(process_tif_file, f, output_dir) for f in files_to_process]
            for future in futures:
                future.result()
                pbar.update(1)

if __name__ == "__main__":
    main()