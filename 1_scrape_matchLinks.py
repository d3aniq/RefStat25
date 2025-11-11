from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from urllib.parse import urljoin
import sys

BASE = "https://stats.innebandy.se"
DATE = sys.argv[1] if len(sys.argv) > 1 else "2025-11-06"
URL  = f"{BASE}/forbund/21/livematches/{DATE}"

BLOCK_PATTERNS = (
    "googletagmanager", "google-analytics", "hotjar", "doubleclick",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".ttf", ".mp4", ".mp3"
)

def should_block(req):
    if req.resource_type in {"image", "media", "font"}:
        return True
    u = req.url.lower()
    return any(p in u for p in BLOCK_PATTERNS)

def get_links():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = browser.new_context()
        page = context.new_page()

        # Blockera onödiga resurser
        page.route("**/*", lambda route: route.abort() if should_block(route.request) else route.continue_())

        print("Öppnar:", URL)
        page.goto(URL, wait_until="domcontentloaded", timeout=12000)

        # Stäng ev. cookie-banner
        for sel in ("button:has-text('Acceptera')","button:has-text('Accept')","text=Acceptera alla","text=Godkänn"):
            try:
                page.locator(sel).first.click(timeout=1000)
            except Exception:
                pass

        try:
            page.wait_for_selector("div.x9FBF a", timeout=8000)
        except PWTimeout:
            pass

        hrefs = page.eval_on_selector_all(
            "div.x9FBF a",
            "els => els.map(a => a.getAttribute('href'))"
        ) or []

        browser.close()

    # Normalisera + dedupl. + lägg till "/laguppstallning"
    seen, full = set(), []
    for h in hrefs:
        if not h:
            continue
        u = urljoin(BASE, h)
        if not u.endswith("/laguppstallning"):
            u += "/laguppstallning"
        if u not in seen:
            seen.add(u)
            full.append(u)
    return full

if __name__ == "__main__":
    links = get_links()
    if not links:
        print("Inga länkar hittades (prova headless=False eller öka timeout).")
    else:
        print(f"Hittade {len(links)} länkar:\n")
        print("\n".join(links))
        with open("links.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(links))
        print("\nSparat i links.txt")
