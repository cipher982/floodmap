#!/usr/bin/env python3
"""
Generate simple colored test tiles to show elevation overlays.
Creates tiles for Tampa area at zoom levels 10-12.
"""
import os
from PIL import Image, ImageDraw

def create_test_tiles():
    """Create colored test tiles for Tampa area."""
    
    # Tampa area tile coordinates at different zoom levels
    tile_coords = {
        10: [(275, 427), (276, 427), (275, 428), (276, 428)],  # 4 tiles at zoom 10
        11: [(551, 854), (552, 854), (551, 855), (552, 855),   # 4 tiles at zoom 11  
             (550, 854), (550, 855), (553, 854), (553, 855)],
        12: [(1102, 1708), (1103, 1708), (1102, 1709), (1103, 1709)]  # 4 tiles at zoom 12
    }
    
    # Colors for different elevation ranges
    colors = [
        (0, 100, 0, 100),    # Low elevation - green
        (255, 255, 0, 100),  # Medium elevation - yellow  
        (255, 100, 0, 100),  # High elevation - orange
        (255, 0, 0, 100),    # Very high elevation - red
    ]
    
    # Create tile directories
    for zoom in tile_coords:
        for x, y in tile_coords[zoom]:
            dir_path = f"data/elevation_tiles/{zoom}/{x}"
            os.makedirs(dir_path, exist_ok=True)
            
            # Create a 256x256 colored tile
            img = Image.new("RGBA", (256, 256), colors[zoom % len(colors)])
            
            # Add some pattern to make it visible
            draw = ImageDraw.Draw(img)
            draw.rectangle([50, 50, 206, 206], outline=(255, 255, 255, 200), width=3)
            draw.text((100, 120), f"Z{zoom}", fill=(255, 255, 255, 255))
            draw.text((100, 140), f"{x},{y}", fill=(255, 255, 255, 255))
            
            # Save tile
            tile_path = f"{dir_path}/{y}.png"
            img.save(tile_path)
            print(f"Created: {tile_path}")

if __name__ == "__main__":
    print("🎨 Creating test elevation tiles...")
    create_test_tiles()
    print("✅ Test tiles created!")
    print("🌐 Restart server to see elevation overlays")