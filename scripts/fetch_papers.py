"""Fetch unique PMC papers from the DataRef-EXP benchmark.

Uses NCBI E-utils efetch (db=pmc) to pull full-text JATS XML — this is the
canonical academic access path and is not blocked by reCAPTCHA unlike the
public PMC web pages.

For each unique citing_publication_link in EXP_groundtruth.csv:
  1. efetch the JATS XML.
  2. Write data/papers/{PMCID}.xml (raw JATS).
  3. Strip to plain text (lxml.etree text content) -> data/papers/{PMCID}.txt.
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
from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GT_CSV = PROJECT_ROOT / "data" / "benchmarks" / "EXP_groundtruth.csv"
PAPERS_DIR = PROJECT_ROOT / "data" / "papers"
CORPUS_JSON = PAPERS_DIR / "corpus.json"

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
HEADERS = {"User-Agent": "rwadata/3001-DE-Project (academic; ml9543@nyu.edu)"}


def extract_pmcid(url: str) -> str:
    m = re.search(r"PMC\d+", url)
    return m.group(0) if m else url.rstrip("/").split("/")[-1]


def xml_to_text(xml_bytes: bytes) -> tuple[str, str]:
    """Return (title, plain_text). Falls back gracefully on malformed XML."""
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        # Some articles contain HTML entities that trip the strict parser.
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(xml_bytes, parser)

    # Title: front/article-meta/title-group/article-title
    title = ""
    title_elem = root.find(".//article-meta/title-group/article-title")
    if title_elem is not None:
        title = "".join(title_elem.itertext()).strip()[:400]

    # Drop structural noise elements before text extraction
    for drop in root.xpath(".//xref | .//tex-math | .//inline-formula"):
        if drop.getparent() is not None:
            drop.text = " "
            drop.tail = (drop.tail or "") + " "

    # Plain text: walk all text under <article>
    article_elem = root.find(".//article")
    if article_elem is None:
        article_elem = root
    text = "\n".join(
        line.strip()
        for line in "".join(article_elem.itertext()).splitlines()
        if line.strip()
    )
    return title, text


def fetch_one(url: str) -> dict:
    pmcid = extract_pmcid(url)
    pmcid_num = pmcid.replace("PMC", "")
    xml_path = PAPERS_DIR / f"{pmcid}.xml"
    txt_path = PAPERS_DIR / f"{pmcid}.txt"

    if xml_path.exists() and txt_path.exists() and xml_path.stat().st_size > 5000:
        xml_bytes = xml_path.read_bytes()
        title, text = xml_to_text(xml_bytes)
        return {
            "id": pmcid,
            "url": url,
            "paper_title": title,
            "paper_text": text,
            "char_len": len(text),
            "status": "cached",
        }

    # Retry with exponential backoff to handle NCBI's 429 rate limiting.
    last_err = None
    for attempt in range(6):
        try:
            resp = requests.get(
                EFETCH_URL,
                params={
                    "db": "pmc",
                    "id": pmcid_num,
                    "rettype": "full",
                    "retmode": "xml",
                },
                headers=HEADERS,
                timeout=120,
            )
            if resp.status_code == 429:
                wait = 2 ** attempt + 1
                time.sleep(wait)
                last_err = requests.HTTPError(f"429 after {wait}s backoff")
                continue
            resp.raise_for_status()
            xml_bytes = resp.content
            if len(xml_bytes) < 1000:
                last_err = ValueError(f"response too small: {len(xml_bytes)} bytes")
                time.sleep(2 ** attempt)
                continue
            xml_path.write_bytes(xml_bytes)
            title, text = xml_to_text(xml_bytes)
            txt_path.write_text(text)
            return {
                "id": pmcid,
                "url": url,
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
        "url": url,
        "paper_title": "",
        "paper_text": "",
        "char_len": 0,
        "status": f"error: {type(last_err).__name__}: {last_err}",
    }


def main() -> int:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    # NCBI asks for <= 3 req/s without an API key; our 21 requests with 6 threads
    # and a small sleep stays comfortably under that.
    gt = pd.read_csv(GT_CSV)
    urls = sorted(gt["citing_publication_link"].unique().tolist())
    print(f"Unique papers in EXP ground truth: {len(urls)}")

    # Serial fetching to stay under NCBI rate limits.
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
        # NCBI asks <= 3 req/s without API key; 0.5s spacing is comfortable.
        time.sleep(0.5)

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
