"""Run DataGatherer (RTR or FDR) on all EXP papers with Kimi.

Writes one jsonl line per paper:
    {"pmcid": "PMC6141466", "predictions": [{"dataset_identifier": "...",
    "repository": "...", "url": "..."}, ...], "latency_s": 8.3, "error": null}

Usage:
    python scripts/run_datagatherer.py --strategy rtr --out outputs/dg_rtr_EXP.jsonl
    python scripts/run_datagatherer.py --strategy fdr --out outputs/dg_fdr_EXP.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

os.environ.setdefault("DATA_GATHERER_USER_NAME", "ml9543")

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from data_gatherer.data_gatherer import DataGatherer  # noqa: E402
import data_gatherer.llm.llm_client as llm_mod  # noqa: E402

GT_CSV = PROJECT_ROOT / "data" / "benchmarks" / "EXP_groundtruth.csv"
MODEL = "kimi-k2-0905-preview"


def extract_pmcid(url: str) -> str:
    m = re.search(r"PMC\d+", url)
    return m.group(0) if m else url.rstrip("/").split("/")[-1]


def df_to_predictions(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    cols_present = set(df.columns)
    # FDR in DG also returns supplementary-material rows with NaN identifier.
    if "dataset_identifier" in cols_present:
        df = df[df["dataset_identifier"].notna()]
    preds = []
    for _, row in df.iterrows():
        ident = row.get("dataset_identifier")
        if not ident or (isinstance(ident, float) and pd.isna(ident)):
            continue
        repo = row.get("data_repository") or row.get("repository") or ""
        url = row.get("dataset_webpage") or ""
        preds.append(
            {
                "dataset_identifier": str(ident),
                "repository": str(repo) if pd.notna(repo) else "",
                "url": str(url) if pd.notna(url) else "",
            }
        )
    return preds


def run_one(dg: DataGatherer, url: str, fdr: bool) -> tuple[list[dict], float, str | None]:
    t0 = time.time()
    try:
        # Critical fixes for DG Kimi support:
        # 1. process_articles default is full_document_read=False, which
        #    silently overrides the constructor process_entire_document flag.
        # 2. process_articles default prompt is GPT_FewShot (RTR-style, one
        #    dataset per response). FDR should use GPT_FDR_FewShot which has
        #    a multi-item array example and instructs the LLM to list all
        #    datasets found in the paper.
        result = dg.process_articles(
            [url],
            full_document_read=fdr,
            prompt_name="GPT_FDR_FewShot" if fdr else "GPT_FewShot",
            semantic_retrieval=False,
        )
        df = result.get(url)
        if df is None:
            # DG normalizes URLs internally; look up any matching key.
            for key, val in result.items():
                if extract_pmcid(key) == extract_pmcid(url):
                    df = val
                    break
        preds = df_to_predictions(df) if df is not None else []
        return preds, time.time() - t0, None
    except Exception as exc:
        return [], time.time() - t0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=["rtr", "fdr"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    gt = pd.read_csv(GT_CSV)
    urls = sorted(gt["citing_publication_link"].unique().tolist())
    print(f"Running DG {args.strategy.upper()} on {len(urls)} papers with {MODEL}")
    print(f"Output -> {args.out}")

    process_entire_document = args.strategy == "fdr"
    dg = DataGatherer(
        llm_name=MODEL,
        process_entire_document=process_entire_document,
    )

    # Reset usage counter.
    llm_mod._usage_counter = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tot_t = 0.0
    n_ok = 0
    n_err = 0
    total_preds = 0
    with args.out.open("w") as f:
        for i, url in enumerate(urls, 1):
            pmcid = extract_pmcid(url)
            preds, latency, err = run_one(dg, url, fdr=process_entire_document)
            tot_t += latency
            if err:
                n_err += 1
                print(f"  [{i:>2}/{len(urls)}] ✗ {pmcid}  {latency:5.1f}s  ERROR: {err}")
            else:
                n_ok += 1
                total_preds += len(preds)
                print(
                    f"  [{i:>2}/{len(urls)}] ✓ {pmcid}  {latency:5.1f}s  "
                    f"preds={len(preds)}"
                )
            f.write(
                json.dumps(
                    {
                        "pmcid": pmcid,
                        "url": url,
                        "predictions": preds,
                        "latency_s": round(latency, 2),
                        "error": err,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            f.flush()

    usage = llm_mod._usage_counter
    cost_usd = (
        usage["prompt_tokens"] / 1_000_000 * 0.60
        + usage["completion_tokens"] / 1_000_000 * 2.50
    )  # approx Kimi K2 pricing, Moonshot CN (CNY) → rough USD

    meta = {
        "strategy": args.strategy,
        "model": MODEL,
        "n_papers": len(urls),
        "n_ok": n_ok,
        "n_err": n_err,
        "total_predictions": total_preds,
        "wall_time_s": round(tot_t, 1),
        "llm_calls": usage["calls"],
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "approx_cost_usd": round(cost_usd, 4),
    }
    meta_path = args.out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))
    print("\n=== run summary ===")
    print(json.dumps(meta, indent=2))
    print(f"\nMeta -> {meta_path}")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
