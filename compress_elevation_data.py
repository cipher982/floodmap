#!/usr/bin/env python3
"""
Utility to compress SRTM elevation data for efficient storage.

Usage:
    python compress_elevation_data.py --input scratch/data_tampa --output compressed_data/tampa
    python compress_elevation_data.py --input data_v2/srtm --output compressed_data/usa
"""

import os
import json
import argparse
from pathlib import Path
import time
import logging
import psutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

import numpy as np
import rasterio
import zstandard as zstd
from tqdm import tqdm


def compress_tile(input_path: Path, output_dir: Path, compression_level: int = 3) -> dict:
    """Compress a single SRTM tile."""
    
    # Read the TIF file
    with rasterio.open(input_path) as src:
        elevation_data = src.read(1)  # Read first band
        bounds = src.bounds
        transform = src.transform
        crs = src.crs
        shape = elevation_data.shape
    
    # Convert to bytes
    raw_bytes = elevation_data.tobytes()
    original_size = len(raw_bytes)
    
    # Compress using ZSTD
    compressor = zstd.ZstdCompressor(level=compression_level)
    compressed_data = compressor.compress(raw_bytes)
    compressed_size = len(compressed_data)
    
    # Generate output filename
    tile_id = input_path.stem  # Remove .tif extension
    output_file = output_dir / f"{tile_id}.zst"
    metadata_file = output_dir / f"{tile_id}.json"
    
    # Write compressed data
    with open(output_file, 'wb') as f:
        f.write(compressed_data)
    
    # Write metadata
    metadata = {
        "tile_id": tile_id,
        "original_file": str(input_path),
        "bounds": {
            "left": float(bounds.left),
            "bottom": float(bounds.bottom), 
            "right": float(bounds.right),
            "top": float(bounds.top)
        },
        "transform": list(transform),
        "crs": str(crs),
        "shape": shape,
        "dtype": str(elevation_data.dtype),
        "original_size": original_size,
        "compressed_size": compressed_size,
        "compression_ratio": original_size / compressed_size,
        "nodata_value": -32768
    }
    
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    return {
        "tile_id": tile_id,
        "original_size": original_size,
        "compressed_size": compressed_size,
        "compression_ratio": original_size / compressed_size,
        "output_file": str(output_file)
    }


def test_decompression(compressed_file: Path, metadata_file: Path) -> bool:
    """Test that we can decompress the data correctly."""
    
    # Load metadata
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)
    
    # Load compressed data
    with open(compressed_file, 'rb') as f:
        compressed_data = f.read()
    
    # Decompress
    decompressor = zstd.ZstdDecompressor()
    decompressed_data = decompressor.decompress(compressed_data)
    
    # Convert back to numpy array
    shape = tuple(metadata['shape'])
    dtype = metadata['dtype']
    elevation_data = np.frombuffer(decompressed_data, dtype=dtype).reshape(shape)
    
    # Basic validation
    if elevation_data.shape != tuple(metadata['shape']):
        logging.error(f"Shape mismatch: expected {metadata['shape']}, got {elevation_data.shape}")
        return False
    
    # Check for reasonable elevation values (SRTM should be between -500 and 9000 meters)
    valid_elevations = elevation_data[elevation_data != -32768]  # Exclude no-data
    if len(valid_elevations) > 0:
        min_elev = np.min(valid_elevations)
        max_elev = np.max(valid_elevations)
        
        if min_elev < -500 or max_elev > 9000:
            logging.warning(f"Unusual elevation range: {min_elev} to {max_elev} meters")
    
    return True


def estimate_processing_time(tif_files: list, sample_size: int = 3) -> float:
    """Estimate total processing time by sampling a few files."""
    if len(tif_files) <= sample_size:
        return 0  # Too small to estimate
    
    logging.info(f"Estimating processing time with {sample_size} sample files...")
    sample_files = tif_files[:sample_size]
    
    start_time = time.time()
    for tif_file in sample_files:
        # Quick test: just read the file to estimate I/O time
        try:
            with rasterio.open(tif_file) as src:
                _ = src.read(1)
        except Exception:
            continue
    
    sample_time = time.time() - start_time
    avg_time_per_file = sample_time / len(sample_files)
    estimated_total = avg_time_per_file * len(tif_files)
    
    logging.info(f"Estimated total processing time: {estimated_total/60:.1f} minutes ({estimated_total/3600:.1f} hours)")
    return estimated_total


def compress_directory(input_dir: Path, output_dir: Path, test_decompression_flag: bool = True, max_workers: int = None):
    """Compress all SRTM tiles in a directory with progress tracking and memory efficiency."""
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all TIF files
    tif_files = list(input_dir.glob("*.tif"))
    
    if not tif_files:
        logging.error(f"No TIF files found in {input_dir}")
        return
    
    logging.info(f"Found {len(tif_files)} TIF files to compress")
    
    # Estimate processing time
    estimate_processing_time(tif_files)
    
    # Check available memory
    available_memory_gb = psutil.virtual_memory().available / (1024**3)
    logging.info(f"Available memory: {available_memory_gb:.1f} GB")
    
    # Check available disk space
    available_disk_gb = psutil.disk_usage(str(output_dir)).free / (1024**3)
    logging.info(f"Available disk space: {available_disk_gb:.1f} GB")
    
    # Set up parallel processing
    if max_workers is None:
        max_workers = min(cpu_count(), 4)  # Don't overwhelm the system
    
    logging.info(f"Using {max_workers} parallel workers")
    
    total_original_size = 0
    total_compressed_size = 0
    successful_compressions = 0
    failed_files = []
    
    start_time = time.time()
    
    # Process files with progress bar
    with tqdm(total=len(tif_files), desc="Compressing tiles", unit="file") as pbar:
        # Process in batches to avoid memory issues
        batch_size = max_workers * 2
        
        for i in range(0, len(tif_files), batch_size):
            batch = tif_files[i:i + batch_size]
            
            # Process batch in parallel
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # Submit jobs
                futures = {
                    executor.submit(compress_tile, tif_file, output_dir): tif_file 
                    for tif_file in batch
                }
                
                # Collect results
                for future in as_completed(futures):
                    tif_file = futures[future]
                    try:
                        result = future.result()
                        
                        total_original_size += result['original_size']
                        total_compressed_size += result['compressed_size']
                        successful_compressions += 1
                        
                        # Test decompression if requested
                        if test_decompression_flag:
                            metadata_file = output_dir / f"{result['tile_id']}.json"
                            compressed_file = Path(result['output_file'])
                            
                            if not test_decompression(compressed_file, metadata_file):
                                logging.error(f"Decompression test failed for {result['tile_id']}")
                        
                        # Update progress bar with compression info
                        pbar.set_postfix({
                            'ratio': f"{result['compression_ratio']:.1f}x",
                            'success': f"{successful_compressions}/{len(tif_files)}",
                            'memory': f"{psutil.virtual_memory().percent:.1f}%"
                        })
                        
                    except Exception as e:
                        logging.error(f"Failed to compress {tif_file.name}: {e}")
                        failed_files.append(tif_file.name)
                    
                    pbar.update(1)
    
    elapsed_time = time.time() - start_time
    
    # Summary
    overall_ratio = total_original_size / total_compressed_size if total_compressed_size > 0 else 0
    
    logging.info(f"""
=== Compression Summary ===
Files processed: {successful_compressions}/{len(tif_files)}
Original size: {total_original_size / 1024 / 1024 / 1024:.1f} GB
Compressed size: {total_compressed_size / 1024 / 1024 / 1024:.1f} GB
Overall compression ratio: {overall_ratio:.1f}x
Time elapsed: {elapsed_time/60:.1f} minutes ({elapsed_time/3600:.1f} hours)
Average time per file: {elapsed_time / len(tif_files):.1f} seconds
Throughput: {len(tif_files) / (elapsed_time/60):.1f} files/minute
Failed files: {len(failed_files)}
    """)
    
    if failed_files:
        logging.warning(f"Failed files: {', '.join(failed_files[:10])}")
        if len(failed_files) > 10:
            logging.warning(f"... and {len(failed_files) - 10} more")


def main():
    parser = argparse.ArgumentParser(description="Compress SRTM elevation data")
    parser.add_argument("--input", required=True, help="Input directory containing .tif files")
    parser.add_argument("--output", required=True, help="Output directory for compressed files")
    parser.add_argument("--compression-level", type=int, default=3, help="ZSTD compression level (1-22)")
    parser.add_argument("--no-test", action="store_true", help="Skip decompression testing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    
    if not input_dir.exists():
        logging.error(f"Input directory does not exist: {input_dir}")
        return
    
    logging.info(f"Compressing elevation data from {input_dir} to {output_dir}")
    logging.info(f"Using ZSTD compression level {args.compression_level}")
    
    compress_directory(
        input_dir, 
        output_dir, 
        test_decompression_flag=not args.no_test
    )


if __name__ == "__main__":
    main()