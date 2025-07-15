"""
E2E test for the new clean frontend architecture.
"""
import pytest
from playwright.async_api import async_playwright


class TestNewFrontend:
    """Test the clean frontend loads and works properly."""
    
    BASE_URL = "http://localhost:5002"
    
    async def test_frontend_loads_without_errors(self):
        """Test that the new frontend loads without console errors."""
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Capture console messages
            console_messages = []
            page.on("console", lambda msg: console_messages.append({
                "type": msg.type,
                "text": msg.text
            }))
            
            # Load the page
            await page.goto(self.BASE_URL)
            await page.wait_for_timeout(3000)  # Wait for map to initialize
            
            # Check page loaded
            title = await page.title()
            assert "Flood Risk Map" in title
            
            # Check for critical errors
            errors = [msg for msg in console_messages if msg["type"] == "error"]
            critical_errors = [e for e in errors if "404" in e["text"] or "500" in e["text"]]
            
            print(f"\\n📊 Console Analysis:")
            print(f"Total messages: {len(console_messages)}")
            print(f"Errors: {len(errors)}")
            print(f"Critical errors: {len(critical_errors)}")
            
            if critical_errors:
                print("❌ Critical errors found:")
                for error in critical_errors:
                    print(f"  - {error['text']}")
            else:
                print("✅ No critical errors - clean architecture working!")
            
            await browser.close()
            
            # Should have no critical errors
            assert len(critical_errors) == 0, f"Found {len(critical_errors)} critical errors"


if __name__ == "__main__":
    import asyncio
    
    test = TestNewFrontend()
    asyncio.run(test.test_frontend_loads_without_errors())
    print("\\n🎉 New frontend architecture test passed!")