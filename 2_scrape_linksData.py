import asyncio
import csv
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from datetime import datetime

CONCURRENCY = 6
NAV_TIMEOUT = 12000   # ms
SEL_TIMEOUT = 8000    # ms
LINKS_FILE = "links.txt"  # ska innehålla /laguppstallning-länkar (en per rad)

BLOCK_PATTERNS = [
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".mp3",
    "googletagmanager", "google-analytics", "hotjar", "doubleclick",
]

async def block_resources(route):
    req = route.request
    url = req.url.lower()
    if req.resource_type in {"image", "media", "font"}:
        return await route.abort()
    if any(p in url for p in BLOCK_PATTERNS):
        return await route.abort()
    await route.continue_()

async def extract_text(page, selector, index=0, attr=None):
    """Hämtar trim:at textinnehåll eller attribut, annars None."""
    try:
        loc = page.locator(selector).nth(index)
        await loc.wait_for(timeout=SEL_TIMEOUT)
        if attr:
            v = await loc.get_attribute(attr)
        else:
            v = await loc.inner_text()
        return (v or "").strip()
    except Exception:
        return None


def normalize_date(raw_date):
    """Försöker omvandla olika datumformat till YYYY-MM-DD."""
    if not raw_date:
        return None
    text = raw_date.strip().replace("Matchdatum:", "").replace("kl", "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    import re
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        y, mth, d = m.groups()
        return f"{int(y):04d}-{int(mth):02d}-{int(d):02d}"
    m = re.search(r"(\d{1,2})\s+([A-Za-zåäöÅÄÖ]+)\s+(\d{4})", text)
    if m:
        d, month_name, y = m.groups()
        months = {
            "januari":1, "februari":2, "mars":3, "april":4, "maj":5, "juni":6,
            "juli":7, "augusti":8, "september":9, "oktober":10, "november":11, "december":12
        }
        month_name = month_name.lower()
        mnum = months.get(month_name)
        if mnum:
            return f"{int(y):04d}-{mnum:02d}-{int(d):02d}"
    return None


async def scrape_lineup(context, url):
    page = await context.new_page()
    try:
        await page.route("**/*", block_resources)
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)

        # ---- Datum ----
        datum = None
        try:
            await page.wait_for_selector("span.d6aBe", timeout=SEL_TIMEOUT)
            spans = page.locator("span.d6aBe")
            count = await spans.count()
            for i in range(count):
                txt = (await spans.nth(i).inner_text()).strip()
                if txt.lower().startswith("matchdatum"):
                    try:
                        datum = (await spans.nth(i).locator("strong").inner_text()).strip()
                    except Exception:
                        datum = txt.split(":", 1)[-1].strip()
                    break
        except Exception:
            pass

        datum = normalize_date(datum)

        # ---- Tid ----
        tid = None
        try:
            spans = page.locator("span.d6aBe")
            count = await spans.count()
            for i in range(count):
                txt = (await spans.nth(i).inner_text()).strip()
                if txt.lower().startswith("matchstart"):
                    try:
                        tid = (await spans.nth(i).locator("strong").inner_text()).strip()
                    except Exception:
                        tid = txt.split(":", 1)[-1].strip()
                    break
        except Exception:
            pass

        # ---- Serie ----
        serie = await extract_text(page, "div.zrccf h1")

        # ---- Hemma/Borta ----
        hemma = await extract_text(page, "h3.QmXlT", 0)
        borta = await extract_text(page, "h3.QmXlT", 1)

        # ---- Arena ----
        arena = None
        try:
            spans = page.locator("span.d6aBe")
            count = await spans.count()
            for i in range(count):
                txt = (await spans.nth(i).inner_text()).strip()
                if txt.lower().startswith("arena"):
                    try:
                        arena = (await spans.nth(i).locator("strong").inner_text()).strip()
                    except Exception:
                        arena = txt.split(":", 1)[-1].strip()
                    break
        except Exception:
            pass

        # ---- Domare ----
        domare = []
        try:
            await page.wait_for_selector("td.wMqhM a", timeout=SEL_TIMEOUT)
            names = await page.eval_on_selector_all(
                "td.wMqhM a",
                "els => els.map(e => e.textContent.trim()).filter(Boolean)"
            )
            domare = names[:2] if names else []
        except Exception:
            pass

        domare1 = domare[0] if len(domare) >= 1 else None
        domare2 = domare[1] if len(domare) >= 2 else None

        # 🟢 Ta bort "/laguppstallning" från URL
        clean_url = url
        if clean_url.endswith("/laguppstallning"):
            clean_url = clean_url[: -len("/laguppstallning")]

        return {
            "url": clean_url,   # 🟢 Spara den städade URL:en
            "Datum": datum,
            "Tid": tid,
            "Serie": serie,
            "Hemmalag": hemma,
            "Bortalag": borta,
            "Arena": arena,
            "Domare1": domare1,
            "Domare2": domare2,
        }

    except Exception:
        return {
            "url": url, "Datum": None, "Tid": None, "Serie": None,
            "Hemmalag": None, "Bortalag": None, "Arena": None,
            "Domare1": None, "Domare2": None
        }
    finally:
        await page.close()


async def main():
    lines = Path(LINKS_FILE).read_text(encoding="utf-8").splitlines()
    lineup_links = [l.strip() for l in lines if l.strip()]
    if not lineup_links:
        print("links.txt saknar länkar.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = await browser.new_context()

        sem = asyncio.Semaphore(CONCURRENCY)
        async def worker(u):
            async with sem:
                return await scrape_lineup(context, u)

        results = await asyncio.gather(*[worker(u) for u in lineup_links])

        # Skriv CSV
        out_file = "matches.csv"
        headers = ["Datum","Tid","Serie","Hemmalag","Bortalag","Arena","Domare1","Domare2","url"]
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            w.writerows(results)

        print(f"Sparat i {out_file} ({len(results)} rader).")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
