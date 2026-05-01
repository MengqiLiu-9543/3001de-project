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
    ap.add_argument(
        "--gt-csv",
        type=Path,
        default=GT_CSV,
        help="Path to ground-truth CSV (defaults to EXP).",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help=(
            "If --out already exists, skip pmcids already present and append "
            "remaining. Useful for long REV runs."
        ),
    )
    args = ap.parse_args()

    gt = pd.read_csv(args.gt_csv)
    urls = sorted(gt["citing_publication_link"].unique().tolist())
    print(f"Running DG {args.strategy.upper()} on {len(urls)} papers with {MODEL}")
    print(f"GT csv -> {args.gt_csv}")
    print(f"Output -> {args.out}")

    # Resume support: read existing output, find which PMCIDs are already done.
    done_pmcids: set[str] = set()
    if args.resume and args.out.exists():
        try:
            for line in args.out.open():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("pmcid") and rec.get("error") is None:
                    done_pmcids.add(rec["pmcid"])
        except Exception as exc:
            print(f"warning: could not read existing output for resume: {exc}")
        if done_pmcids:
            print(f"resume: found {len(done_pmcids)} pmcids already processed; skipping them")

    process_entire_document = args.strategy == "fdr"
    dg = DataGatherer(
        llm_name=MODEL,
        process_entire_document=process_entire_document,
    )

    # Reset usage counter.
    llm_mod._usage_counter = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    # Hard budget kill switch: refuse to start a new paper if cumulative
    # cost would exceed this. Prevents over-spending on tight quotas.
    MAX_USD = float(os.environ.get("DG_MAX_USD", "0") or 0)  # 0 = disabled
    if MAX_USD > 0:
        print(f"Budget kill switch: will stop if cumulative cost exceeds ${MAX_USD}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tot_t = 0.0
    n_ok = len(done_pmcids)
    n_err = 0
    n_skipped = 0
    total_preds = 0
    n_budget_stopped = 0
    open_mode = "a" if (args.resume and args.out.exists()) else "w"
    with args.out.open(open_mode) as f:
        for i, url in enumerate(urls, 1):
            pmcid = extract_pmcid(url)
            if pmcid in done_pmcids:
                n_skipped += 1
                continue
            # Budget check: if we'd exceed budget, stop gracefully (output
            # already flushed to disk line by line — partial run is salvageable).
            if MAX_USD > 0:
                u = llm_mod._usage_counter
                so_far = (u["prompt_tokens"]/1_000_000*0.60
                          + u["completion_tokens"]/1_000_000*2.50)
                if so_far >= MAX_USD:
                    print(
                        f"\n[BUDGET STOP] cumulative cost ${so_far:.4f} >= "
                        f"${MAX_USD}. Stopping at paper {i}/{len(urls)}. "
                        f"{i-1} papers processed; remaining {len(urls)-i+1} skipped."
                    )
                    n_budget_stopped = len(urls) - i + 1
                    break
            preds, latency, err = run_one(dg, url, fdr=process_entire_document)
            tot_t += latency
            if err:
                n_err += 1
                print(f"  [{i:>5}/{len(urls)}] ✗ {pmcid}  {latency:5.1f}s  ERROR: {err}")
            else:
                n_ok += 1
                total_preds += len(preds)
                print(
                    f"  [{i:>5}/{len(urls)}] ✓ {pmcid}  {latency:5.1f}s  "
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
        "gt_csv": str(args.gt_csv),
        "n_papers": len(urls),
        "n_ok": n_ok,
        "n_err": n_err,
        "n_skipped_resume": n_skipped,
        "n_budget_stopped": n_budget_stopped,
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
