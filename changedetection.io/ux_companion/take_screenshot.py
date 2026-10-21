import asyncio
import sys

sys.path.insert(0, r"C:\Users\kc0eks\projects\github-forks\sherlock\venv\Lib\site-packages")
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://127.0.0.1:8510/")
        await page.wait_for_timeout(2000)
        await page.screenshot(
            path=r"C:\Users\kc0eks\projects\github-forks\changedetection.io\ux_companion\docs\screenshots\dashboard.png"
        )
        print("dashboard captured")
        await browser.close()


asyncio.run(main())
