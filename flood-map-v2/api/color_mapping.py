"""
Dynamic elevation-to-color mapping for contextual flood risk visualization.

Core algorithm: elevation + water_level → RGBA color
Based on Jony Ive's vision of intuitive flood risk communication.
"""

import numpy as np
from typing import Tuple, Optional
import colorsys


class FloodRiskColorMapper:
    """Convert elevation data to contextual flood risk colors."""
    
    def __init__(self):
        # Color scheme constants
        self.SAFE_COLOR = (76, 175, 80, 120)      # Green, semi-transparent
        self.CAUTION_COLOR = (255, 193, 7, 160)   # Yellow, more visible  
        self.DANGER_COLOR = (244, 67, 54, 200)    # Red, prominent
        self.FLOODED_COLOR = (33, 150, 243, 220)  # Blue, very visible
        
        # Risk zone thresholds (meters relative to water level)
        self.SAFE_THRESHOLD = 10.0      # 10m+ above water = safe
        self.CAUTION_THRESHOLD = 3.0    # 3-10m above water = caution
        self.DANGER_THRESHOLD = 0.5     # 0.5-3m above water = danger
        # Below 0.5m = flooded
        
    def elevation_to_risk_level(self, elevation: float, water_level: float) -> float:
        """
        Convert absolute elevation to flood risk level.
        
        Returns:
            risk_level: 0.0 (safe) to 1.0 (flooded)
        """
        relative_elevation = elevation - water_level
        
        if relative_elevation >= self.SAFE_THRESHOLD:
            return 0.0  # Safe
        elif relative_elevation >= self.CAUTION_THRESHOLD:
            # Linear interpolation between safe and caution
            return (self.SAFE_THRESHOLD - relative_elevation) / (self.SAFE_THRESHOLD - self.CAUTION_THRESHOLD) * 0.33
        elif relative_elevation >= self.DANGER_THRESHOLD:
            # Linear interpolation between caution and danger  
            return 0.33 + (self.CAUTION_THRESHOLD - relative_elevation) / (self.CAUTION_THRESHOLD - self.DANGER_THRESHOLD) * 0.33
        elif relative_elevation >= -0.5:
            # Linear interpolation between danger and flooded
            return 0.66 + (self.DANGER_THRESHOLD - relative_elevation) / (self.DANGER_THRESHOLD + 0.5) * 0.34
        else:
            return 1.0  # Completely flooded
    
    def risk_to_color(self, risk_level: float) -> Tuple[int, int, int, int]:
        """
        Convert risk level to RGBA color.
        
        Args:
            risk_level: 0.0 (safe) to 1.0 (flooded)
            
        Returns:
            (r, g, b, a) tuple
        """
        if risk_level <= 0.33:
            # Safe to caution transition
            t = risk_level / 0.33
            return self._blend_colors(self.SAFE_COLOR, self.CAUTION_COLOR, t)
        elif risk_level <= 0.66:
            # Caution to danger transition
            t = (risk_level - 0.33) / 0.33
            return self._blend_colors(self.CAUTION_COLOR, self.DANGER_COLOR, t)
        else:
            # Danger to flooded transition
            t = (risk_level - 0.66) / 0.34
            return self._blend_colors(self.DANGER_COLOR, self.FLOODED_COLOR, t)
    
    def _blend_colors(self, color1: Tuple[int, int, int, int], 
                      color2: Tuple[int, int, int, int], 
                      t: float) -> Tuple[int, int, int, int]:
        """Smooth color blending between two RGBA colors."""
        return tuple(
            int(color1[i] * (1 - t) + color2[i] * t)
            for i in range(4)
        )
    
    def elevation_array_to_rgba(self, elevation_data: np.ndarray, 
                               water_level: float, 
                               no_data_value: Optional[float] = None) -> np.ndarray:
        """
        Convert 2D elevation array to RGBA color array.
        
        Args:
            elevation_data: 2D numpy array of elevation values
            water_level: Current water level in meters
            no_data_value: Value representing missing data (becomes transparent)
            
        Returns:
            3D numpy array (height, width, 4) with RGBA values
        """
        height, width = elevation_data.shape
        rgba_array = np.zeros((height, width, 4), dtype=np.uint8)
        
        # Handle no-data values
        if no_data_value is not None:
            valid_mask = elevation_data != no_data_value
        else:
            valid_mask = np.ones_like(elevation_data, dtype=bool)
        
        # Vectorized color mapping
        for y in range(height):
            for x in range(width):
                if valid_mask[y, x]:
                    elevation = elevation_data[y, x]
                    risk_level = self.elevation_to_risk_level(elevation, water_level)
                    rgba_array[y, x] = self.risk_to_color(risk_level)
                else:
                    # Transparent for no-data areas
                    rgba_array[y, x] = (0, 0, 0, 0)
        
        return rgba_array
    
    def get_legend_colors(self, water_level: float) -> dict:
        """Get legend colors for current water level."""
        return {
            f"Safe (>{water_level + self.SAFE_THRESHOLD:.1f}m)": self.SAFE_COLOR,
            f"Caution ({water_level + self.CAUTION_THRESHOLD:.1f}-{water_level + self.SAFE_THRESHOLD:.1f}m)": self.CAUTION_COLOR,
            f"Danger ({water_level + self.DANGER_THRESHOLD:.1f}-{water_level + self.CAUTION_THRESHOLD:.1f}m)": self.DANGER_COLOR,
            f"Flooded (<{water_level + self.DANGER_THRESHOLD:.1f}m)": self.FLOODED_COLOR,
        }


# Global instance for use across the API
color_mapper = FloodRiskColorMapper()