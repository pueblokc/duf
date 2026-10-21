import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://127.0.0.1:8503/")
        await page.wait_for_timeout(2000)
        await page.screenshot(path="docs/screenshots/dashboard.png", full_page=False)
        print("dashboard captured")
        await browser.close()

asyncio.run(main())
