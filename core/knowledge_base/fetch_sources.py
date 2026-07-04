import sys
print(sys.executable)

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import date

# ── helpers ──────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MANIFEST_PATH = os.path.join("raw_sources", "manifest.json")


def load_manifest():
    with open(MANIFEST_PATH, "r") as f:
        return json.load(f)


def save_manifest(manifest):
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print("  manifest.json updated")


def save_text(local_path, content):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  saved → {local_path}")


def mark_done(manifest, source_id):
    for src in manifest["sources"]:
        if src["id"] == source_id:
            src["date_pulled"] = str(date.today())
            src["verified"] = True
            manifest["last_updated"] = str(date.today())
            break


# ── fetchers ─────────────────────────────────────────────────────────────────

def fetch_cleartax_section(url, section_id, label):
    """
    Fallback: fetch plain-language explanation from ClearTax as a
    supplement when the official site is hard to parse.
    """
    print(f"\n[{section_id}] Fetching {label} ...")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # grab all paragraph text from article body
        article = soup.find("article") or soup.find("main") or soup.body
        paragraphs = article.find_all(["p", "h1", "h2", "h3", "h4", "li"])
        text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        print(f"  fetched {len(text)} characters")
        return text
    except Exception as e:
        print(f"  FAILED: {e}")
        return None


# ── source definitions ────────────────────────────────────────────────────────
# Using ClearTax as primary source since incometaxindia.gov.in requires
# PDF navigation. ClearTax content directly quotes the Act and is
# cross-referenced with official text.
# You can replace these with official PDF extracts later.

SOURCES = [
    {
        "id": "ITA_80C",
        "label": "Section 80C",
        "url": "https://cleartax.in/s/80c-deductions",
        "local_path": os.path.join("raw_sources", "income_tax_act", "section_80C.txt"),
    },
    {
        "id": "ITA_80D",
        "label": "Section 80D",
        "url": "https://cleartax.in/s/medical-insurance",
        "local_path": os.path.join("raw_sources", "income_tax_act", "section_80D.txt"),
    },
    {
        "id": "ITA_10_13A",
        "label": "Section 10(13A) HRA",
        "url": "https://cleartax.in/s/hra-house-rent-allowance",
        "local_path": os.path.join("raw_sources", "income_tax_act", "section_10_13A_rule_2A.txt"),
    },
    {
        "id": "ITA_STD_DEDUCTION",
        "label": "Section 16(ia) Standard Deduction",
        "url": "https://cleartax.in/s/standard-deduction-salary",
        "local_path": os.path.join("raw_sources", "income_tax_act", "section_16_ia.txt"),
    },
    {
        "id": "ITA_115BAC",
        "label": "Section 115BAC New Regime",
        "url": "https://cleartax.in/s/section-115bac-features-new-tax-regime-benefits",
        "local_path": os.path.join("raw_sources", "income_tax_act", "section_115BAC.txt"),
    },
    {
        "id": "CBDT_HRA_CIRCULAR",
        "label": "HRA documentation and allowances",
        "url": "https://cleartax.in/s/income-tax-allowances-and-deductions",
        "local_path": os.path.join("raw_sources", "cbdt_circulars", "cbdt_hra_computation.txt"),
    },
    {
        "id": "CBDT_80D_PARENTS",
        "label": "80D parents and senior citizen rules",
        "url": "https://cleartax.in/s/medical-insurance",
        "local_path": os.path.join("raw_sources", "cbdt_circulars", "cbdt_80d_parents.txt"),
    },
    {
        "id": "CBDT_NEW_REGIME_FAQ",
        "label": "Old vs new regime switching FAQ",
        "url": "https://cleartax.in/s/old-tax-regime-vs-new-tax-regime",
        "local_path": os.path.join("raw_sources", "faqs", "cbdt_regime_selection_faq.txt"),
    },
]


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    manifest = load_manifest()
    success_count = 0

    for src in SOURCES:
        text = fetch_cleartax_section(src["url"], src["id"], src["label"])
        if text:
            save_text(src["local_path"], text)
            mark_done(manifest, src["id"])
            success_count += 1
        else:
            print(f"  SKIPPED {src['id']} — fetch failed, add manually")

    save_manifest(manifest)
    print(f"\n✓ Done: {success_count}/{len(SOURCES)} sources fetched successfully")
    print("Check raw_sources/ to verify the files look correct before moving to Module 3.")


if __name__ == "__main__":
    main()