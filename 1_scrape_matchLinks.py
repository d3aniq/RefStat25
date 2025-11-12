from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from urllib.parse import urljoin
from datetime import datetime, timedelta
import sys

BASE = "https://stats.innebandy.se"
BLOCK_PATTERNS = (
    "googletagmanager", "google-analytics", "hotjar", "doubleclick",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".ttf", ".mp4", ".mp3"
)

def should_block(req):
    if req.resource_type in {"image", "media", "font"}:
        return True
    u = req.url.lower()
    return any(p in u for p in BLOCK_PATTERNS)

def daterange(start_date, end_date):
    """Generera alla datum från start till slut, inklusive båda."""
    for n in range((end_date - start_date).days + 1):
        yield start_date + timedelta(n)

def get_links_for_date(page, date_str):
    """Hämtar länkar för ett specifikt datum (YYYY-MM-DD)."""
    url = f"{BASE}/forbund/21/livematches/{date_str}"
    print(f"\n📅 Hämtar {date_str} -> {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=12000)
    except Exception as e:
        print("Fel vid laddning:", e)
        return []

    # Stäng cookie-banners
    for sel in ("button:has-text('Acceptera')","button:has-text('Accept')","text=Acceptera alla","text=Godkänn"):
        try:
            page.locator(sel).first.click(timeout=1000)
        except Exception:
            pass

    try:
        page.wait_for_selector("div.x9FBF a", timeout=8000)
    except PWTimeout:
        print("⚠️  Inga matcher hittades denna dag.")
        return []

    hrefs = page.eval_on_selector_all(
        "div.x9FBF a",
        "els => els.map(a => a.getAttribute('href'))"
    ) or []

    full = []
    for h in hrefs:
        if not h:
            continue
        u = urljoin(BASE, h)
        if not u.endswith("/laguppstallning"):
            u += "/laguppstallning"
        full.append(u)
    return full

def get_links(start_date_str, end_date_str):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    all_links = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = browser.new_context()
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if should_block(route.request) else route.continue_())

        for d in daterange(start_date, end_date):
            date_str = d.strftime("%Y-%m-%d")
            links = get_links_for_date(page, date_str)
            for u in links:
                if u not in seen:
                    seen.add(u)
                    all_links.append(u)

        browser.close()

    return all_links

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    elif len(sys.argv) == 2:
        start_date = end_date = sys.argv[1]
    else:
        start_date = end_date = datetime.now().strftime("%Y-%m-%d")

    links = get_links(start_date, end_date)

    if not links:
        print("\nInga länkar hittades.")
    else:
        print(f"\n✅ Totalt hittade {len(links)} länkar:")
        print("\n".join(links))
        with open("links.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(links))
        print("\n💾 Sparat i links.txt")
