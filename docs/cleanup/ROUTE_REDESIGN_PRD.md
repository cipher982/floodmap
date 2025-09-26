# Flood Map API Route Redesign - Technical PRD

## Problem Statement

The current tile serving routes have grown organically and are inconsistent, causing:

- **Testing failures** - Integration tests use wrong endpoints and accept 404s as valid
- **Frontend confusion** - Multiple URL patterns for similar resources
- **Maintenance burden** - Inconsistent naming makes debugging difficult
- **Caching issues** - Unclear cache keys due to inconsistent patterns
- **Integration complexity** - Different URL structures for vector vs elevation tiles

### Current Route Problems:
```
❌ /api/tiles/vector/{z}/{x}/{y}.pbf          # API proxy
❌ /api/tiles/elevation/{water_level}/{z}/{x}/{y}.png  # API generated
❌ /data/usa-complete/{z}/{x}/{y}.pbf         # Direct tileserver
❌ /tiles/flood/{level}/{z}/{x}/{y}.png       # Legacy endpoint
```

## Solution: Standardized REST API Design

### Design Principles

1. **Consistent Pattern** - All tile endpoints follow same structure
2. **RESTful Resources** - Clear resource hierarchy and identification
3. **Versioned API** - Future-proof with `/v1/` versioning
4. **Self-Documenting** - URL structure tells you what you get
5. **Cache-Friendly** - Predictable cache keys and headers
6. **Web Standards Compliant** - Follows TMS/XYZ tile conventions

### Proposed Route Structure

```
/api/v1/tiles/
├── vector/
│   ├── usa/{z}/{x}/{y}.pbf           # USA-wide vector tiles
│   └── tampa/{z}/{x}/{y}.pbf         # Tampa-specific vector tiles
├── elevation/{z}/{x}/{y}.png         # Raw elevation data (no water)
├── flood/
│   └── {water_level}/{z}/{x}/{y}.png # Flood overlay at specific water level
└── composite/
    └── {water_level}/{z}/{x}/{y}.png # Combined elevation + flood (optional)
```

## Technical Specifications

### Route Definitions

**Vector Tiles (Base Maps)**
```
GET /api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf
GET /api/v1/tiles/vector/tampa/{z}/{x}/{y}.pbf

Parameters:
- z: Zoom level (0-18)
- x, y: Tile coordinates
Returns:
- 200: application/x-protobuf with vector tile data
- 404: Tile not found
- 400: Invalid coordinates
```

**Elevation Tiles (No Water Level)**
```
GET /api/v1/tiles/elevation/{z}/{x}/{y}.png

Parameters:
- z: Zoom level (8-14)
- x, y: Tile coordinates
Returns:
- 200: image/png with elevation visualization
- 204: No elevation data (transparent tile)
- 400: Invalid coordinates
```

**Flood Overlay Tiles**
```
GET /api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png

Parameters:
- water_level: Float, water level in meters (-10.0 to 50.0)
- z: Zoom level (8-14)
- x, y: Tile coordinates
Returns:
- 200: image/png with flood overlay
- 204: No flood risk (transparent tile)
- 400: Invalid parameters
```

**Optional - Composite Tiles**
```
GET /api/v1/tiles/composite/{water_level}/{z}/{x}/{y}.png

Combined elevation + flood visualization in single tile
```

### HTTP Headers & Caching

```http
Cache-Control: public, max-age=3600, immutable
X-Tile-Source: elevation|vector|flood|composite
X-Water-Level: {level} (for flood/composite tiles)
X-Cache: HIT|MISS
Content-Type: image/png|application/x-protobuf
```

### Error Responses

```http
400 Bad Request - Invalid coordinates or parameters
404 Not Found - Tile does not exist
429 Too Many Requests - Rate limiting
500 Internal Server Error - Tile generation failed
503 Service Unavailable - Dependent service down
```

## Migration Strategy

### Phase 1: Implement New Routes (Parallel)
- Add new v1 routes alongside existing routes
- Maintain backward compatibility
- Update health checks to validate new routes

### Phase 2: Frontend Migration
- Update MapLibre/Leaflet tile URL templates
- Test new routes in staging environment
- Monitor performance and error rates

### Phase 3: Deprecation
- Add deprecation warnings to old routes
- Update documentation
- Set shorter cache TTL on old routes

### Phase 4: Cleanup
- Remove old route handlers
- Clean up integration tests
- Remove deprecated route documentation

## Success Metrics

### Performance
- ✅ Tile response time < 100ms (cached)
- ✅ Tile response time < 2000ms (generated)
- ✅ Cache hit rate > 80%
- ✅ Error rate < 1%

### Consistency
- ✅ All routes follow same URL pattern
- ✅ Consistent HTTP headers across all endpoints
- ✅ Standardized error responses
- ✅ Integration tests pass 100%

### Developer Experience
- ✅ Frontend can template URLs easily
- ✅ Routes are self-documenting
- ✅ Clear separation of concerns
- ✅ Debugging is straightforward

## Implementation Details

### Route Handler Organization
```python
# routers/tiles_v1.py - New clean implementation
@router.get("/api/v1/tiles/vector/{source}/{z}/{x}/{y}.pbf")
@router.get("/api/v1/tiles/elevation/{z}/{x}/{y}.png")
@router.get("/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png")
@router.get("/api/v1/tiles/composite/{water_level}/{z}/{x}/{y}.png")
```

### Frontend Integration
```javascript
// Clean, consistent tile URLs
const TILE_ENDPOINTS = {
  vector: '/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf',
  flood: '/api/v1/tiles/flood/{water_level}/{z}/{x}/{y}.png',
  elevation: '/api/v1/tiles/elevation/{z}/{x}/{y}.png'
};
```

### Testing Strategy
- Unit tests for each route handler
- Integration tests with actual tile coordinates
- Load testing for concurrent requests
- Validation of HTTP headers and caching
- Error scenario testing

## Risks & Mitigation

**Risk**: Breaking existing frontend during migration
**Mitigation**: Parallel deployment, feature flags, staged rollout

**Risk**: Performance regression with new routes
**Mitigation**: Benchmarking, monitoring, rollback plan

**Risk**: Cache invalidation during migration
**Mitigation**: Separate cache namespaces for v1 routes

## Timeline

- **Week 1**: Implement new route handlers
- **Week 2**: Add comprehensive testing
- **Week 3**: Frontend migration and testing
- **Week 4**: Production deployment and monitoring
- **Week 5**: Deprecate old routes
- **Week 6**: Final cleanup and documentation

## Acceptance Criteria

- [ ] All new routes implemented with consistent patterns
- [ ] Integration tests pass 100% with new routes
- [ ] Frontend successfully migrated to new routes
- [ ] Performance metrics meet or exceed current levels
- [ ] Old routes deprecated with clear migration path
- [ ] Documentation updated with new route specifications
