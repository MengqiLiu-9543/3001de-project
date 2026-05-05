"""Auto-report for the new clean DocETL v1 REV run.

Runs after outputs/rev/docetl_v1_REV.meta.json appears (signal that the
DocETL pipeline finished). Computes loose/strict metrics against
REV_sample_groundtruth.csv and compares them to the previous v1 (with
Rule 2/3) baseline.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from eval import compute_metrics, load_ground_truth, load_predictions  # noqa: E402

REV_GT = PROJECT_ROOT / "data" / "benchmarks" / "REV_sample_groundtruth.csv"
PRED = PROJECT_ROOT / "outputs" / "rev" / "docetl_v1_REV.jsonl"
META = PROJECT_ROOT / "outputs" / "rev" / "docetl_v1_REV.meta.json"
OUT_MD = PROJECT_ROOT / "outputs" / "rev" / "v1_clean_summary.md"

# Old v1 (with Rule 2/3) REV baseline — from outputs/rev/v1_with_rule3/
OLD_V1 = {
    "loose_p": 66.35,
    "loose_r": 98.73,
    "loose_f1": 79.36,
    "preds": 2802,
    "cost_usd": 18.0,  # approximate (some was cached)
}


def main() -> int:
    if not META.exists():
        print(f"ERROR: {META} not found — run did not complete.")
        return 1
    if not PRED.exists():
        print(f"ERROR: {PRED} not found.")
        return 1

    meta = json.loads(META.read_text())
    gt = load_ground_truth(REV_GT)
    preds = load_predictions(PRED)
    loose = compute_metrics(gt, preds, mode="loose")["micro"]
    strict = compute_metrics(gt, preds, mode="strict")["micro"]

    new_p = round(loose["precision"] * 100, 2)
    new_r = round(loose["recall"] * 100, 2)
    new_f1 = round(loose["f1"] * 100, 2)
    new_cost = round(meta.get("approx_cost_usd", 0.0), 4)
    new_preds = meta.get("total_predictions", 0)

    d_p = round(new_p - OLD_V1["loose_p"], 2)
    d_r = round(new_r - OLD_V1["loose_r"], 2)
    d_f1 = round(new_f1 - OLD_V1["loose_f1"], 2)

    md = f"""# DocETL v1 REV — Clean Prompt Auto-Report

**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Benchmark**: DataRef-REV (1,242 papers, 1,883 ground-truth records)

## Headline (loose-match)

| | Old v1 (with Rule 2/3) | **New v1 (clean)** | Δ |
|---|---|---|---|
| Predictions | {OLD_V1['preds']} | {new_preds} | {new_preds - OLD_V1['preds']:+d} |
| Precision | {OLD_V1['loose_p']:.2f}% | **{new_p:.2f}%** | {d_p:+.2f} pt |
| Recall | {OLD_V1['loose_r']:.2f}% | **{new_r:.2f}%** | {d_r:+.2f} pt |
| **F1** | **{OLD_V1['loose_f1']:.2f}%** | **{new_f1:.2f}%** | **{d_f1:+.2f} pt** |
| Cost (USD) | ~${OLD_V1['cost_usd']:.2f} (partly cached) | **${new_cost:.2f}** (fresh) | — |

## Strict-match (for completeness)

| | New v1 (clean) |
|---|---|
| Precision | {strict['precision']*100:.2f}% |
| Recall    | {strict['recall']*100:.2f}% |
| F1        | {strict['f1']*100:.2f}% |
| TP / FP / FN | {strict['tp']} / {strict['fp']} / {strict['fn']} |

## Run telemetry

| Field | Value |
|---|---|
| Wall time (s) | {meta.get('wall_time_s', 0):.1f} |
| LLM calls | {meta.get('llm_calls', 0)} |
| Prompt tokens | {meta.get('prompt_tokens', 0):,} |
| Completion tokens | {meta.get('completion_tokens', 0):,} |
| Pipeline yaml | `{meta.get('pipeline_yaml', '')}` |

## Comparison summary

- F1 changed by **{d_f1:+.2f} pt**, recall by **{d_r:+.2f} pt**, precision by **{d_p:+.2f} pt**.
- Old REV outputs preserved at `outputs/rev/v1_with_rule3/`.
- New outputs: `outputs/rev/docetl_v1_REV.{{jsonl, meta.json}}`
"""
    OUT_MD.write_text(md)
    print(md)
    print(f"\nWrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
