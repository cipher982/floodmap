"""
Predictive Tile Preloader - Anticipate user needs with multi-core processing
Preloads surrounding tiles and common zoom levels before user requests them.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TileRequest:
    """Represents a tile request pattern."""

    z: int
    x: int
    y: int
    water_level: float
    timestamp: float
    user_session: str = "default"


class PredictiveTilePreloader:
    """
    Predictive tile preloading system.
    Uses multiple cores to generate tiles before users request them.
    """

    def __init__(self, max_preload_workers: int = None):
        self.max_workers = max_preload_workers or min(12, os.cpu_count())
        self.preload_pool = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="tile-preload"
        )

        # Request history for pattern detection
        self.request_history: deque = deque(maxlen=1000)
        self.user_patterns: dict[str, list[TileRequest]] = defaultdict(list)

        # Currently preloading tiles
        self.preloading_tiles: set[str] = set()
        self.preload_stats = {
            "tiles_preloaded": 0,
            "cache_hits_from_preload": 0,
            "preload_workers_active": 0,
        }

        logger.info(
            f"🧠 Predictive preloader: {self.max_workers} cores for tile anticipation"
        )

    def record_tile_request(
        self, z: int, x: int, y: int, water_level: float, user_session: str = "default"
    ):
        """Record a tile request to learn user patterns."""
        request = TileRequest(z, x, y, water_level, time.time(), user_session)
        self.request_history.append(request)
        self.user_patterns[user_session].append(request)

        # Trigger predictive preloading
        asyncio.create_task(self._predict_and_preload(request))

    async def _predict_and_preload(self, current_request: TileRequest):
        """Predict what tiles user will need next and preload them."""
        predictions = []

        # 1. Surrounding tiles (zoom/pan prediction)
        surrounding = self._predict_surrounding_tiles(current_request)
        predictions.extend(surrounding)

        # 2. Zoom level predictions
        zoom_predictions = self._predict_zoom_levels(current_request)
        predictions.extend(zoom_predictions)

        # 3. Water level variations
        water_level_predictions = self._predict_water_levels(current_request)
        predictions.extend(water_level_predictions)

        # 4. User pattern predictions
        pattern_predictions = self._predict_from_patterns(current_request)
        predictions.extend(pattern_predictions)

        # Remove duplicates and current tile
        unique_predictions = []
        seen = set()
        current_key = f"{current_request.z}_{current_request.x}_{current_request.y}_{current_request.water_level:.1f}"

        for pred in predictions:
            pred_key = f"{pred.z}_{pred.x}_{pred.y}_{pred.water_level:.1f}"
            if pred_key not in seen and pred_key != current_key:
                seen.add(pred_key)
                unique_predictions.append(pred)

        # Limit preloading to avoid overwhelming the system
        top_predictions = unique_predictions[:20]  # Top 20 most likely tiles

        if top_predictions:
            logger.debug(f"🔮 Preloading {len(top_predictions)} predicted tiles")
            await self._schedule_preloading(top_predictions)

    def _predict_surrounding_tiles(self, request: TileRequest) -> list[TileRequest]:
        """Predict surrounding tiles user might pan to."""
        predictions = []

        # 3x3 grid around current tile
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue  # Skip current tile

                new_x = request.x + dx
                new_y = request.y + dy

                # Validate tile coordinates
                if self._is_valid_tile(request.z, new_x, new_y):
                    predictions.append(
                        TileRequest(
                            z=request.z,
                            x=new_x,
                            y=new_y,
                            water_level=request.water_level,
                            timestamp=time.time(),
                            user_session=request.user_session,
                        )
                    )

        return predictions

    def _predict_zoom_levels(self, request: TileRequest) -> list[TileRequest]:
        """Predict tiles at different zoom levels."""
        predictions = []

        # Zoom in (higher detail)
        if request.z < 14:
            zoom_in_z = request.z + 1
            # When zooming in, the tile splits into 4 tiles
            for dx in [0, 1]:
                for dy in [0, 1]:
                    new_x = request.x * 2 + dx
                    new_y = request.y * 2 + dy

                    if self._is_valid_tile(zoom_in_z, new_x, new_y):
                        predictions.append(
                            TileRequest(
                                z=zoom_in_z,
                                x=new_x,
                                y=new_y,
                                water_level=request.water_level,
                                timestamp=time.time(),
                                user_session=request.user_session,
                            )
                        )

        # Zoom out (overview)
        if request.z > 8:
            zoom_out_z = request.z - 1
            new_x = request.x // 2
            new_y = request.y // 2

            if self._is_valid_tile(zoom_out_z, new_x, new_y):
                predictions.append(
                    TileRequest(
                        z=zoom_out_z,
                        x=new_x,
                        y=new_y,
                        water_level=request.water_level,
                        timestamp=time.time(),
                        user_session=request.user_session,
                    )
                )

        return predictions

    def _predict_water_levels(self, request: TileRequest) -> list[TileRequest]:
        """Predict tiles with similar water levels."""
        predictions = []

        # Common water level variations (±0.5m, ±1m)
        water_variations = [
            request.water_level + 0.5,
            request.water_level - 0.5,
            request.water_level + 1.0,
            request.water_level - 1.0,
        ]

        for water_level in water_variations:
            if -10 <= water_level <= 50:  # Valid range
                predictions.append(
                    TileRequest(
                        z=request.z,
                        x=request.x,
                        y=request.y,
                        water_level=water_level,
                        timestamp=time.time(),
                        user_session=request.user_session,
                    )
                )

        return predictions

    def _predict_from_patterns(self, request: TileRequest) -> list[TileRequest]:
        """Predict based on user's historical patterns."""
        predictions = []
        user_history = self.user_patterns.get(request.user_session, [])

        if len(user_history) < 3:
            return predictions

        # Look for movement patterns in recent history
        recent_requests = user_history[-5:]  # Last 5 requests

        # Calculate movement velocity
        if len(recent_requests) >= 2:
            last_req = recent_requests[-1]
            prev_req = recent_requests[-2]

            if last_req.z == prev_req.z:  # Same zoom level
                dx = last_req.x - prev_req.x
                dy = last_req.y - prev_req.y

                # Predict continued movement
                if abs(dx) <= 2 and abs(dy) <= 2:  # Reasonable movement
                    predicted_x = request.x + dx
                    predicted_y = request.y + dy

                    if self._is_valid_tile(request.z, predicted_x, predicted_y):
                        predictions.append(
                            TileRequest(
                                z=request.z,
                                x=predicted_x,
                                y=predicted_y,
                                water_level=request.water_level,
                                timestamp=time.time(),
                                user_session=request.user_session,
                            )
                        )

        return predictions

    def _is_valid_tile(self, z: int, x: int, y: int) -> bool:
        """Check if tile coordinates are valid."""
        if not (8 <= z <= 14):
            return False

        max_coord = 2**z
        return (0 <= x < max_coord) and (0 <= y < max_coord)

    def predict_adjacent_tiles(
        self, z: int, x: int, y: int
    ) -> list[tuple[int, int, int]]:
        """Predict tiles user will likely request next."""
        adjacent = [
            (z, x - 1, y),
            (z, x + 1, y),  # Horizontal pan
            (z, x, y - 1),
            (z, x, y + 1),  # Vertical pan
            (z + 1, x * 2, y * 2),
            (z + 1, x * 2 + 1, y * 2),
            (z + 1, x * 2, y * 2 + 1),
            (z + 1, x * 2 + 1, y * 2 + 1),  # Zoom in
            (z - 1, x // 2, y // 2),  # Zoom out
        ]
        return [
            (tz, tx, ty) for tz, tx, ty in adjacent if self._is_valid_tile(tz, tx, ty)
        ]

    async def preload_predicted_tiles(
        self, current_z: int, current_x: int, current_y: int, water_level: float
    ):
        """Generate predicted tiles during idle time."""
        predictions = self.predict_adjacent_tiles(current_z, current_x, current_y)

        from tile_cache import tile_cache

        for z, x, y in predictions:
            # Try both PNG and WEBP formats for comprehensive preloading
            for format in ["PNG", "WEBP"]:
                cache_key = f"{water_level}_{format}"
                if not tile_cache.exists(cache_key, z, x, y):
                    # Use idle workers to pregenerate
                    tile_req = TileRequest(z, x, y, water_level, time.time())
                    await self._preload_tile_with_format(tile_req, format)

    async def _preload_tile_with_format(self, tile_req: TileRequest, format: str):
        """Preload a single tile with specific format."""
        from routers.tiles import generate_elevation_tile_sync
        from tile_cache import tile_cache

        tile_key = f"{tile_req.z}_{tile_req.x}_{tile_req.y}_{tile_req.water_level:.1f}_{format}"

        # Skip if already preloading
        if tile_key in self.preloading_tiles:
            return

        # Check if already in cache
        cache_key = f"{tile_req.water_level}_{format}"
        cached = tile_cache.get(cache_key, tile_req.z, tile_req.x, tile_req.y)
        if cached is not None:
            return

        self.preloading_tiles.add(tile_key)
        self.preload_stats["preload_workers_active"] += 1

        try:
            # Generate tile in background with format
            loop = asyncio.get_event_loop()
            tile_data = await loop.run_in_executor(
                self.preload_pool,
                generate_elevation_tile_sync,
                tile_req.water_level,
                tile_req.z,
                tile_req.x,
                tile_req.y,
                format,
            )

            # Cache the preloaded tile
            if (
                tile_data and len(tile_data) > 0
            ):  # Valid tile data (even 1x1 tiles are valid)
                tile_cache.put(cache_key, tile_req.z, tile_req.x, tile_req.y, tile_data)
                self.preload_stats["tiles_preloaded"] += 1
                logger.debug(f"✅ Preloaded tile {tile_key} ({len(tile_data)} bytes)")

        except Exception as e:
            logger.warning(f"Preload failed for {tile_key}: {e}")
        finally:
            self.preloading_tiles.discard(tile_key)
            self.preload_stats["preload_workers_active"] -= 1

    async def _schedule_preloading(self, predictions: list[TileRequest]):
        """Schedule tile preloading using the thread pool with format awareness."""
        # Preload both PNG and WEBP formats for optimal coverage
        tasks = []
        for pred in predictions:
            for format in ["PNG", "WEBP"]:
                tasks.append(self._preload_tile_with_format(pred, format))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_stats(self) -> dict:
        """Get preloader performance statistics."""
        return {
            "max_preload_workers": self.max_workers,
            "currently_preloading": len(self.preloading_tiles),
            "request_history_size": len(self.request_history),
            "user_sessions": len(self.user_patterns),
            **self.preload_stats,
        }

    def clear_history(self):
        """Clear request history and patterns."""
        self.request_history.clear()
        self.user_patterns.clear()
        logger.info("🧹 Cleared preloader history")

    def shutdown(self):
        """Shutdown the preloader."""
        self.preload_pool.shutdown(wait=True)
        logger.info("🛑 Predictive preloader shutdown")


# Global preloader instance
import os

predictive_preloader = PredictiveTilePreloader(
    max_preload_workers=min(12, os.cpu_count())
)
