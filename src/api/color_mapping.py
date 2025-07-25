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
        
        # Elevation color scheme for topographical visualization
        self.ELEVATION_COLORS = [
            (33, 150, 243, 255),   # Blue: Sea level / very low (0-5m)
            (76, 175, 80, 255),    # Green: Low elevation (5-50m)
            (139, 195, 74, 255),   # Light green: Medium-low (50-100m) 
            (255, 235, 59, 255),   # Yellow: Medium (100-200m)
            (255, 152, 0, 255),    # Orange: Medium-high (200-500m)
            (121, 85, 72, 255),    # Brown: High (500-1000m)
            (158, 158, 158, 255),  # Gray: Very high (1000m+)
        ]
        
        # Elevation thresholds in meters
        self.ELEVATION_THRESHOLDS = [0, 5, 50, 100, 200, 500, 1000, 3000]
        
        # Risk zone thresholds (meters relative to water level) - REALISTIC FLOOD ZONES
        self.SAFE_THRESHOLD = 5.0       # 5m+ above water = safe  
        self.CAUTION_THRESHOLD = 2.0    # 2-5m above water = caution   
        self.DANGER_THRESHOLD = 0.5     # 0.5-2m above water = danger
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
        
        # True vectorized color mapping using NumPy operations
        # Calculate risk levels for all pixels at once
        risk_levels = np.zeros_like(elevation_data, dtype=np.int8)
        
        # Vectorized risk level calculation
        flooded_mask = elevation_data < (water_level + self.DANGER_THRESHOLD)
        danger_mask = (elevation_data >= (water_level + self.DANGER_THRESHOLD)) & (elevation_data < (water_level + self.CAUTION_THRESHOLD))
        caution_mask = (elevation_data >= (water_level + self.CAUTION_THRESHOLD)) & (elevation_data < (water_level + self.SAFE_THRESHOLD))
        safe_mask = elevation_data >= (water_level + self.SAFE_THRESHOLD)
        
        risk_levels[flooded_mask & valid_mask] = 0  # FLOODED
        risk_levels[danger_mask & valid_mask] = 1   # DANGER  
        risk_levels[caution_mask & valid_mask] = 2  # CAUTION
        risk_levels[safe_mask & valid_mask] = 3     # SAFE
        
        # Create color lookup array for vectorized assignment
        colors = np.array([
            self.FLOODED_COLOR,  # 0
            self.DANGER_COLOR,   # 1  
            self.CAUTION_COLOR,  # 2
            self.SAFE_COLOR,     # 3
            (0, 0, 0, 0)        # 4 - invalid/no-data (transparent)
        ], dtype=np.uint8)
        
        # Set invalid pixels to index 4 (transparent)
        risk_levels[~valid_mask] = 4
        
        # Vectorized color assignment
        rgba_array = colors[risk_levels]
        
        return rgba_array
    
    def elevation_array_to_topographical_rgba(self, elevation_data: np.ndarray, 
                                            no_data_value: Optional[float] = None) -> np.ndarray:
        """
        Convert 2D elevation array to topographical RGBA colors (absolute elevation).
        
        Args:
            elevation_data: 2D numpy array of elevation values
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
        
        # Assign colors based on elevation thresholds
        for i in range(len(self.ELEVATION_THRESHOLDS) - 1):
            min_elev = self.ELEVATION_THRESHOLDS[i]
            max_elev = self.ELEVATION_THRESHOLDS[i + 1]
            
            # Create mask for this elevation band
            band_mask = (elevation_data >= min_elev) & (elevation_data < max_elev) & valid_mask
            
            # Assign color to this band
            rgba_array[band_mask] = self.ELEVATION_COLORS[i]
        
        # Handle highest elevation band (above last threshold)
        highest_mask = (elevation_data >= self.ELEVATION_THRESHOLDS[-1]) & valid_mask
        rgba_array[highest_mask] = self.ELEVATION_COLORS[-1]
        
        # Invalid pixels remain transparent (initialized as zeros)
        
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