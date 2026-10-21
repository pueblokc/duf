import asyncio, sys
sys.path.insert(0, r"C:\Users\kc0eks\projects\github-forks\sherlock\venv\Lib\site-packages")
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1100, "height": 800})
        await page.goto("http://127.0.0.1:8504/")
        await page.wait_for_timeout(2000)
        await page.screenshot(path=r"C:\Users\kc0eks\projects\github-forks\ytdl-web\docs\screenshots\landing.png")
        print("landing captured")
        await browser.close()

asyncio.run(main())
