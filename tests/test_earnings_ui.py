"""
Playwright smoke tests for the EarningIntel earnings detail UI.
Run with:
    python tests/test_earnings_ui.py [--base-url http://localhost:3000]

Requires playwright: pip install playwright && playwright install chromium
"""
import argparse
import sys
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:3000"

# (ticker, period, required_visible_texts)
CASES = [
    ("IFX",  "Q2-2026", ["Infineon", "Segment Breakdown", "P&L Snapshot", "Guidance", "Source Documents"]),
    ("SIE",  "Q2-2026", ["Siemens",  "Post-Earnings Brief", "Guidance", "Custom KPIs"]),
    ("NVDA", "Q2-2026", ["NVIDIA",   "Key Highlights",    "Guidance", "Source Documents"]),
    ("AZN",  "Q4-2025", ["AstraZeneca", "Key Highlights", "Post-Earnings Brief"]),
    ("JPM",  "Q1-2026", ["JPMorgan", "Key Highlights",    "Post-Earnings Brief"]),
    ("NOVO", "Q1-2026", ["Novo Nordisk", "Key Highlights", "Post-Earnings Brief"]),
]


def run(base_url: str) -> int:
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for ticker, period, checks in CASES:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            url = f"{base_url}/earnings/{ticker}/{period}"
            page.goto(url, wait_until="networkidle")

            passed = [c for c in checks if page.locator(f"text={c}").first.is_visible()]
            failed = [c for c in checks if c not in passed]

            status = "✓" if not failed else "✗"
            print(f"  {status}  {ticker}/{period}  ({len(passed)}/{len(checks)} checks)")
            for f in failed:
                print(f"       MISSING: {f}")
            if failed:
                failures += 1
            page.close()
        browser.close()
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    print(f"\nRunning earnings UI tests against {args.base_url}\n")
    failures = run(args.base_url)
    print(f"\n{'All tests passed' if not failures else f'{failures} test(s) failed'}")
    sys.exit(failures)
