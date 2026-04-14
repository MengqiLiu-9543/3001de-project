"""Fetch unique PMC papers as HTML.

Per the project spec ("DocETL pipeline takes a corpus of scientific papers
(PDFs or HTML) as input"), we fetch the actual rendered HTML page for each
PMC article from the canonical pmc.ncbi.nlm.nih.gov URL.

For each unique citing_publication_link in EXP_groundtruth.csv:
  1. GET https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/ with a real browser
     User-Agent (PMC's bot detection blocks default requests UAs).
  2. Save raw HTML to data/papers/{PMCID}.html.
  3. Strip to plain text with BeautifulSoup -> data/papers/{PMCID}.txt.
  4. Build data/papers/corpus.json for DocETL input:
     [{id, url, paper_title, paper_text}, ...]

Usage:
    python scripts/fetch_papers.py
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GT_CSV = PROJECT_ROOT / "data" / "benchmarks" / "EXP_groundtruth.csv"
PAPERS_DIR = PROJECT_ROOT / "data" / "papers"
CORPUS_JSON = PAPERS_DIR / "corpus.json"

# Real-browser User-Agent. PMC's web frontend rejects non-browser UAs with a
# reCAPTCHA challenge page.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def extract_pmcid(url: str) -> str:
    m = re.search(r"PMC\d+", url)
    return m.group(0) if m else url.rstrip("/").split("/")[-1]


def html_to_text(html: str) -> tuple[str, str]:
    """Strip HTML to (title, plain_text) using BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    # Drop noise containers that aren't part of the article body.
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "noscript",
            "form",
        ]
    ):
        tag.decompose()

    # PMC pages also embed boilerplate sections (cookie banners, related-
    # articles sidebars, etc). Strip a few well-known ones by id/class.
    for sel in [
        "#mc-banner",
        "#cookie-banner",
        ".usa-banner",
        ".pmc-sidenav",
        ".col-side",
    ]:
        for el in soup.select(sel):
            el.decompose()

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)[:400]
    if not title:
        t = soup.find("title")
        if t:
            title = t.get_text(strip=True)[:400]

    text = "\n".join(
        line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()
    )
    return title, text


def fetch_one(url: str) -> dict:
    pmcid = extract_pmcid(url)
    canonical = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    html_path = PAPERS_DIR / f"{pmcid}.html"
    txt_path = PAPERS_DIR / f"{pmcid}.txt"

    # Reuse cached real HTML (>50k bytes is a heuristic for a real article
    # page; anything smaller is probably a reCAPTCHA challenge fragment).
    if (
        html_path.exists()
        and txt_path.exists()
        and html_path.stat().st_size > 50_000
    ):
        html = html_path.read_text()
        title, text = html_to_text(html)
        return {
            "id": pmcid,
            "url": canonical,
            "paper_title": title,
            "paper_text": text,
            "char_len": len(text),
            "status": "cached",
        }

    last_err: Exception | None = None
    for attempt in range(5):
        try:
            resp = requests.get(canonical, headers=HEADERS, timeout=60, allow_redirects=True)
            if resp.status_code == 429:
                wait = 2 ** attempt + 1
                time.sleep(wait)
                last_err = requests.HTTPError(f"429 after {wait}s backoff")
                continue
            resp.raise_for_status()
            html = resp.text
            if len(html) < 50_000 or "recaptcha" in html.lower():
                # Probably a challenge page. Back off and retry.
                last_err = ValueError(
                    f"response looks like a challenge page ({len(html)} bytes)"
                )
                time.sleep(2 ** attempt)
                continue
            html_path.write_text(html)
            title, text = html_to_text(html)
            txt_path.write_text(text)
            return {
                "id": pmcid,
                "url": canonical,
                "paper_title": title,
                "paper_text": text,
                "char_len": len(text),
                "status": f"fetched (attempt {attempt + 1})",
            }
        except Exception as exc:
            last_err = exc
            time.sleep(2 ** attempt)

    return {
        "id": pmcid,
        "url": canonical,
        "paper_title": "",
        "paper_text": "",
        "char_len": 0,
        "status": f"error: {type(last_err).__name__}: {last_err}",
    }


def main() -> int:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    gt = pd.read_csv(GT_CSV)
    urls = sorted(gt["citing_publication_link"].unique().tolist())
    print(f"Unique papers in EXP ground truth: {len(urls)}")
    print(f"Source: pmc.ncbi.nlm.nih.gov canonical HTML pages\n")

    corpus = []
    errors = []
    for i, url in enumerate(urls, 1):
        rec = fetch_one(url)
        pmcid = rec["id"]
        if rec["status"].startswith("error"):
            errors.append(rec)
            print(f"  [{i:>2}/{len(urls)}] ✗ {pmcid}  {rec['status']}")
        else:
            corpus.append(
                {
                    "id": rec["id"],
                    "url": rec["url"],
                    "paper_title": rec["paper_title"],
                    "paper_text": rec["paper_text"],
                }
            )
            print(
                f"  [{i:>2}/{len(urls)}] ✓ {pmcid}  "
                f"{rec['char_len']:>8} chars  {rec['status']}"
            )
        # Polite spacing — PMC accepts ~3 req/s but slowing down avoids
        # tripping bot detection on repeated runs.
        time.sleep(1.0)

    corpus.sort(key=lambda r: r["id"])
    CORPUS_JSON.write_text(json.dumps(corpus, ensure_ascii=False))
    print(f"\nWrote {len(corpus)} papers to {CORPUS_JSON}")
    if errors:
        print(f"{len(errors)} failed:")
        for e in errors:
            print(" ", e["url"], e["status"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
