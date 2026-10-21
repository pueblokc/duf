"""Take screenshots of Sherlock Web UI for docs."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        # Screenshot 1: Landing page
        await page.goto("http://127.0.0.1:8501/")
        await page.wait_for_timeout(1000)
        await page.screenshot(path="docs/screenshots/landing.png", full_page=False)
        print("Captured: landing.png")

        # Screenshot 2: Search in progress
        await page.fill("#usernameInput", "johndoe")
        await page.click("#searchBtn")
        await page.wait_for_timeout(8000)  # Let some results stream in
        await page.screenshot(path="docs/screenshots/search-progress.png", full_page=False)
        print("Captured: search-progress.png")

        # Wait for search to complete
        await page.wait_for_timeout(60000)
        await page.screenshot(path="docs/screenshots/search-complete.png", full_page=False)
        print("Captured: search-complete.png")

        # Screenshot 3: Filter to found only
        await page.click('[data-filter="CLAIMED"]')
        await page.wait_for_timeout(500)
        await page.screenshot(path="docs/screenshots/found-only.png", full_page=False)
        print("Captured: found-only.png")

        await browser.close()

asyncio.run(main())
