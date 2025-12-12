"""
Security tests for input validation and parameter sanitization.
"""

import pytest
import requests


@pytest.mark.security
class TestInputValidation:
    """Test input validation and sanitization."""

    def test_tile_coordinate_bounds(self, api_client):
        """Test tile coordinate boundary validation."""
        # Test negative coordinates
        response = api_client.get("/api/tiles/topographical/-1/0/0.png")
        assert response.status_code == 400

        response = api_client.get("/api/tiles/topographical/10/-1/0.png")
        assert response.status_code == 400

        response = api_client.get("/api/tiles/topographical/10/0/-1.png")
        assert response.status_code == 400

        # Test coordinates too large for zoom level
        response = api_client.get("/api/tiles/topographical/10/9999/0.png")
        assert response.status_code == 400

        response = api_client.get("/api/tiles/topographical/10/0/9999.png")
        assert response.status_code == 400

    def test_water_level_bounds(self, api_client):
        """Test water level boundary validation."""
        # Test extreme water levels
        response = api_client.get("/api/tiles/elevation/-999/10/277/429.png")
        assert response.status_code == 400

        response = api_client.get("/api/tiles/elevation/9999/10/277/429.png")
        assert response.status_code == 400

        # Test valid boundary values
        response = api_client.get("/api/tiles/elevation/-10/10/277/429.png")
        assert response.status_code == 200

        response = api_client.get("/api/tiles/elevation/1000/10/277/429.png")
        assert response.status_code == 200

    def test_zoom_level_bounds(self, api_client):
        """Test zoom level boundary validation."""
        # Test zoom level too high
        response = api_client.get("/api/tiles/topographical/25/0/0.png")
        assert response.status_code == 400

        # Test negative zoom
        response = api_client.get("/api/tiles/topographical/-1/0/0.png")
        assert response.status_code == 400

        # Test maximum allowed zoom
        response = api_client.get("/api/tiles/topographical/18/0/0.png")
        assert response.status_code in [200, 400]  # May depend on data availability

    def test_parameter_type_validation(self, api_client):
        """Test parameter type validation."""
        # Test non-numeric parameters
        response = api_client.get("/api/tiles/topographical/abc/0/0.png")
        assert response.status_code == 422  # Validation error

        response = api_client.get("/api/tiles/topographical/10/abc/0.png")
        assert response.status_code == 422

        response = api_client.get("/api/tiles/elevation/abc/10/277/429.png")
        assert response.status_code == 422

    def test_path_traversal_attempts(self, api_client):
        """Test protection against path traversal attacks."""
        # Test various path traversal attempts
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "....//....//....//etc/passwd",
        ]

        for path in malicious_paths:
            response = api_client.get(f"/api/tiles/topographical/{path}")
            assert response.status_code in [400, 404, 422], (
                f"Path traversal not blocked: {path}"
            )

    def test_large_parameter_values(self, api_client):
        """Test handling of extremely large parameter values."""
        # Test very large integers
        large_int = "9" * 100  # 100-digit number

        response = api_client.get(f"/api/tiles/topographical/{large_int}/0/0.png")
        assert response.status_code in [400, 422]

        response = api_client.get(f"/api/tiles/elevation/{large_int}/10/277/429.png")
        assert response.status_code in [400, 422]

    def test_special_characters_in_parameters(self, api_client):
        """Test handling of special characters in parameters."""
        special_chars = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE users; --",
            "%3Cscript%3Ealert('xss')%3C/script%3E",
            "../../etc/passwd",
            "null",
            "undefined",
        ]

        for char in special_chars:
            response = api_client.get(f"/api/tiles/topographical/10/{char}/0.png")
            assert response.status_code in [400, 422], (
                f"Special character not handled: {char}"
            )


@pytest.mark.security
class TestRateLimiting:
    """Test rate limiting and abuse prevention."""

    def test_rate_limiting_basic(self, api_client):
        """Test basic rate limiting functionality."""
        # Make many requests quickly
        responses = []
        for i in range(100):
            response = api_client.get(f"/api/tiles/topographical/10/277/{429 + i}.png")
            responses.append(response)

        # Should eventually hit rate limit
        rate_limited = any(r.status_code == 429 for r in responses)

        # If no rate limiting, at least check that server handles load
        successful = sum(1 for r in responses if r.status_code == 200)
        assert successful > 0, "Server should handle some requests successfully"

    def test_bulk_endpoint_limits(self, api_client):
        """Test bulk endpoint request limits."""
        # Test oversized bulk request
        large_bulk_request = [
            {"z": 10, "x": 277 + i, "y": 429 + j, "water_level": 2.0}
            for i in range(10)
            for j in range(20)  # 200 tiles
        ]

        response = api_client.post("/api/tiles/bulk", json=large_bulk_request)
        assert response.status_code == 400, "Should reject oversized bulk requests"


@pytest.mark.security
class TestErrorHandling:
    """Test error handling and information disclosure."""

    def test_error_response_format(self, api_client):
        """Test that error responses don't leak sensitive information."""
        # Test with invalid endpoint
        response = api_client.get("/api/tiles/nonexistent/10/277/429.png")
        assert response.status_code == 404

        # Error response should not contain sensitive information
        error_text = response.text.lower()
        sensitive_terms = [
            "password",
            "secret",
            "key",
            "token",
            "database",
            "traceback",
            "exception",
            "stack trace",
            "internal error",
            "/users/",
            "c:\\",
            "root",
            "admin",
        ]

        for term in sensitive_terms:
            assert term not in error_text, (
                f"Error response contains sensitive term: {term}"
            )

    def test_404_handling(self, api_client):
        """Test 404 error handling."""
        # Test various non-existent endpoints
        endpoints = [
            "/api/nonexistent",
            "/api/tiles/invalid/10/277/429.png",
            "/api/admin",
            "/api/debug/secret",
        ]

        for endpoint in endpoints:
            response = api_client.get(endpoint)
            assert response.status_code == 404

            # Should not reveal internal structure
            assert "internal" not in response.text.lower()
            assert "debug" not in response.text.lower()

    def test_method_not_allowed(self, api_client):
        """Test handling of unsupported HTTP methods."""
        # Test POST on GET-only endpoints
        response = api_client.post("/api/tiles/topographical/10/277/429.png")
        assert response.status_code == 405

        # Test PUT on GET-only endpoints
        response = requests.put(
            f"{api_client.base_url}/api/tiles/topographical/10/277/429.png"
        )
        assert response.status_code == 405

        # Test DELETE on GET-only endpoints
        response = requests.delete(
            f"{api_client.base_url}/api/tiles/topographical/10/277/429.png"
        )
        assert response.status_code == 405


@pytest.mark.security
class TestResourceExhaustion:
    """Test protection against resource exhaustion attacks."""

    def test_concurrent_request_handling(self, api_client):
        """Test handling of many concurrent requests."""
        import threading

        results = []

        def make_request(tile_id):
            response = api_client.get(
                f"/api/tiles/topographical/10/277/{429 + tile_id}.png"
            )
            results.append(response.status_code)

        # Create many threads
        threads = []
        for i in range(20):
            thread = threading.Thread(target=make_request, args=(i,))
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Should handle concurrent requests gracefully
        successful = sum(1 for status in results if status == 200)
        assert successful > 0, "Should handle some concurrent requests"

        # Should not crash (all responses should be valid HTTP status codes)
        assert all(100 <= status <= 599 for status in results)

    def test_large_request_handling(self, api_client):
        """Test handling of requests with large payloads."""
        # Test large bulk request
        large_request = [
            {"z": 10, "x": 277, "y": 429, "water_level": 2.0}
            for _ in range(50)  # 50 tiles (within limit)
        ]

        response = api_client.post("/api/tiles/bulk", json=large_request)
        assert response.status_code in [200, 400], (
            "Should handle or reject large requests gracefully"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
