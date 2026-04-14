"""Aggregate system outputs into comparison tables.

Run after the three system jsonl files exist:
    outputs/dg_rtr_EXP.jsonl  (+ .meta.json)
    outputs/dg_fdr_EXP.jsonl  (+ .meta.json)
    outputs/docetl_v0_EXP.jsonl  (+ .meta.json)

Produces:
    outputs/metrics.json      — full numbers
    outputs/summary.md        — human-readable tables
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Import eval helpers without CLI
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval import (  # noqa: E402
    compute_metrics,
    load_ground_truth,
    load_predictions,
    per_repo_recall,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "outputs"

SYSTEMS = [
    ("DataGatherer RTR", OUT_DIR / "dg_rtr_EXP.jsonl"),
    ("DataGatherer FDR", OUT_DIR / "dg_fdr_EXP.jsonl"),
    ("DocETL v0", OUT_DIR / "docetl_v0_EXP.jsonl"),
    ("DocETL v1", OUT_DIR / "docetl_v1_EXP.jsonl"),
]


def load_meta(jsonl: Path) -> dict:
    meta = jsonl.with_suffix(".meta.json")
    if meta.exists():
        try:
            return json.loads(meta.read_text())
        except Exception:
            return {}
    return {}


def fmt_pct(x: float) -> str:
    return f"{x * 100:6.2f}"


def main() -> int:
    gt = load_ground_truth()
    n_gt_papers = len(gt)
    n_gt_pairs = sum(len(v) for v in gt.values())

    rows = []
    for name, path in SYSTEMS:
        if not path.exists():
            print(f"[skip] missing: {path}")
            continue
        pred = load_predictions(path)
        strict = compute_metrics(gt, pred, mode="strict")
        loose = compute_metrics(gt, pred, mode="loose")
        repo_rec = per_repo_recall(gt, pred)
        meta = load_meta(path)
        rows.append(
            {
                "name": name,
                "path": str(path),
                "n_papers_pred": len(pred),
                "n_predictions_total": sum(len(v) for v in pred.values()),
                "strict": strict["micro"],
                "loose": loose["micro"],
                "per_repo_recall": repo_rec,
                "meta": meta,
                "strict_per_paper": strict["per_paper"],
                "loose_per_paper": loose["per_paper"],
            }
        )

    # ---- Write full JSON
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(
            {
                "benchmark": "DataRef-EXP",
                "n_ground_truth_papers": n_gt_papers,
                "n_ground_truth_pairs": n_gt_pairs,
                "systems": rows,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"Wrote {OUT_DIR / 'metrics.json'}")

    # ---- Write markdown summary
    md = []
    md.append("# Comparison Summary — DataRef-EXP (Kimi K2-0905-preview)\n")
    md.append(
        f"**Benchmark**: DataRef-EXP ground truth — {n_gt_papers} papers, "
        f"{n_gt_pairs} (dataset_identifier, repository) pairs.\n"
    )
    md.append("")

    md.append("## Table 1 — Accuracy (strict = id+repo must match)\n")
    md.append("| System | Strict P | Strict R | Strict F1 | Loose P | Loose R | Loose F1 | TP/FP/FN (strict) |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        s = r["strict"]
        l = r["loose"]
        md.append(
            f"| {r['name']} | {fmt_pct(s['precision'])} | {fmt_pct(s['recall'])} | "
            f"**{fmt_pct(s['f1'])}** | {fmt_pct(l['precision'])} | "
            f"{fmt_pct(l['recall'])} | **{fmt_pct(l['f1'])}** | "
            f"{s['tp']}/{s['fp']}/{s['fn']} |"
        )
    md.append("")

    md.append("## Table 2 — Coverage (total predictions & per-repo recall)\n")
    md.append("| System | # Preds | # Unique papers w/ preds |")
    md.append("|---|---|---|")
    for r in rows:
        md.append(
            f"| {r['name']} | {r['n_predictions_total']} | {r['n_papers_pred']} |"
        )
    md.append("")

    # Per-repo recall pivoted: repo across columns
    all_repos = sorted({r for row in rows for r in row["per_repo_recall"].keys()})
    md.append("### Per-repository recall (loose match)\n")
    md.append("| System | " + " | ".join(all_repos) + " |")
    md.append("|---|" + "|".join(["---"] * len(all_repos)) + "|")
    for r in rows:
        cells = []
        for repo in all_repos:
            stats = r["per_repo_recall"].get(repo)
            if stats:
                cells.append(
                    f"{stats['hit_count']}/{stats['gt_count']}"
                )
            else:
                cells.append("-")
        md.append(f"| {r['name']} | " + " | ".join(cells) + " |")
    md.append("")

    md.append("## Table 3 — Cost & latency\n")
    md.append(
        "| System | Wall time (s) | LLM calls | Prompt tokens | Completion tokens | Approx USD |"
    )
    md.append("|---|---|---|---|---|---|")
    for r in rows:
        m = r["meta"]
        md.append(
            "| {name} | {wall} | {calls} | {pt} | {ct} | {usd} |".format(
                name=r["name"],
                wall=m.get("wall_time_s", "?"),
                calls=m.get("llm_calls", "?"),
                pt=m.get("prompt_tokens", "?"),
                ct=m.get("completion_tokens", "?"),
                usd=m.get("approx_cost_usd", "?"),
            )
        )
    md.append("")

    md.append("## Per-paper F1 (strict) — for disagreement analysis\n")
    md.append("| PMCID | " + " | ".join(r["name"] for r in rows) + " |")
    md.append("|---|" + "|".join(["---"] * len(rows)) + "|")
    all_papers = sorted(gt.keys())
    # Build lookup
    lookups = []
    for r in rows:
        by_paper = {pp["pmcid"]: pp for pp in r["strict_per_paper"]}
        lookups.append(by_paper)
    for p in all_papers:
        cells = []
        for lu in lookups:
            pp = lu.get(p)
            if pp:
                cells.append(f"{pp['f1']:.2f} ({pp['tp']}/{pp['tp']+pp['fn']})")
            else:
                cells.append("-")
        md.append(f"| {p} | " + " | ".join(cells) + " |")
    md.append("")

    (OUT_DIR / "summary.md").write_text("\n".join(md))
    print(f"Wrote {OUT_DIR / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
