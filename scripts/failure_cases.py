"""Categorize disagreements between DocETL and DataGatherer.

4 categories (per paper, using loose matching to avoid noise from repo labels):
    - both_hit   : both systems caught this dataset
    - docetl_only: DocETL found it, DG (either strategy) did not
    - dg_only    : DG (RTR or FDR) found it, DocETL did not
    - both_missed: neither found it (ground truth has it)

Writes:
    outputs/failure_cases.json — full machine-readable dump
    outputs/failure_cases.md   — human-readable summary
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval import load_ground_truth, load_predictions  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "outputs"


def _loose_keys(records) -> set:
    """Flatten a list of record signature frozensets into a set of id keys."""
    keys = set()
    for r in records:
        for k_repo in r:
            keys.add(k_repo[0])
    return keys


def _record_label(record) -> tuple[str, str]:
    """Pick a representative (id, repo) for display from a multi-sig record."""
    sigs = sorted(record)
    for ident, repo in sigs:
        if repo:
            return ident, repo
    return sigs[0] if sigs else ("", "")


def categorize(gt, dg_rtr, dg_fdr, docetl):
    cats = {
        "both_hit": [],
        "docetl_only": [],
        "dg_only": [],
        "both_missed": [],
    }
    for pmcid, gt_records in gt.items():
        rtr_keys = _loose_keys(dg_rtr.get(pmcid, []))
        fdr_keys = _loose_keys(dg_fdr.get(pmcid, []))
        de_keys = _loose_keys(docetl.get(pmcid, []))
        dg_union = rtr_keys | fdr_keys
        for record in gt_records:
            record_keys = {k for k, _ in record}
            ident_label, repo_label = _record_label(record)
            in_dg = bool(record_keys & dg_union)
            in_de = bool(record_keys & de_keys)
            case = {
                "pmcid": pmcid,
                "ident": ident_label,
                "gt_repo": repo_label,
                "dg_rtr_hit": bool(record_keys & rtr_keys),
                "dg_fdr_hit": bool(record_keys & fdr_keys),
                "docetl_hit": in_de,
            }
            if in_dg and in_de:
                cats["both_hit"].append(case)
            elif in_de and not in_dg:
                cats["docetl_only"].append(case)
            elif in_dg and not in_de:
                cats["dg_only"].append(case)
            else:
                cats["both_missed"].append(case)
    return cats


def find_hallucinations(pred, gt):
    """Pred records whose loose keys do not overlap with any gt loose key."""
    out = []
    for pmcid, records in pred.items():
        gt_keys = _loose_keys(gt.get(pmcid, []))
        for record in records:
            record_keys = {k for k, _ in record}
            if record_keys & gt_keys:
                continue
            ident_label, repo_label = _record_label(record)
            out.append({"pmcid": pmcid, "ident": ident_label, "pred_repo": repo_label})
    return out


def main() -> int:
    gt = load_ground_truth()
    paths = {
        "dg_rtr": OUT_DIR / "dg_rtr_EXP.jsonl",
        "dg_fdr": OUT_DIR / "dg_fdr_EXP.jsonl",
        "docetl": OUT_DIR / "docetl_v1_EXP.jsonl",
    }
    for name, p in paths.items():
        if not p.exists():
            print(f"missing: {p}")
            return 1

    dg_rtr = load_predictions(paths["dg_rtr"])
    dg_fdr = load_predictions(paths["dg_fdr"])
    docetl = load_predictions(paths["docetl"])

    cats = categorize(gt, dg_rtr, dg_fdr, docetl)

    summary_counts = {k: len(v) for k, v in cats.items()}
    print("=== category counts ===")
    for k, v in summary_counts.items():
        print(f"  {k:<14} {v}")

    # Hallucinations / FPs
    fp_dg_rtr = find_hallucinations(dg_rtr, gt)
    fp_dg_fdr = find_hallucinations(dg_fdr, gt)
    fp_docetl = find_hallucinations(docetl, gt)

    full = {
        "categories": cats,
        "counts": summary_counts,
        "false_positives": {
            "dg_rtr": fp_dg_rtr,
            "dg_fdr": fp_dg_fdr,
            "docetl": fp_docetl,
        },
    }
    (OUT_DIR / "failure_cases.json").write_text(
        json.dumps(full, indent=2, ensure_ascii=False)
    )
    print(f"\nWrote {OUT_DIR / 'failure_cases.json'}")

    # Markdown summary with the most interesting examples
    md = ["# Failure Case Analysis — DataRef-EXP\n"]
    md.append("## Counts\n")
    md.append("| Category | Count |")
    md.append("|---|---|")
    for k in ["both_hit", "docetl_only", "dg_only", "both_missed"]:
        md.append(f"| {k} | {summary_counts[k]} |")
    md.append("")
    md.append(f"**False positives**: DG-RTR {len(fp_dg_rtr)}, "
              f"DG-FDR {len(fp_dg_fdr)}, DocETL {len(fp_docetl)}\n")

    def dump_section(title, cases, limit=10):
        md.append(f"## {title}  ({len(cases)} total, showing up to {limit})\n")
        md.append("| PMCID | identifier | gt_repo | DG-RTR | DG-FDR | DocETL |")
        md.append("|---|---|---|---|---|---|")
        for c in cases[:limit]:
            md.append(
                f"| {c['pmcid']} | `{c['ident']}` | {c['gt_repo']} | "
                f"{'✓' if c['dg_rtr_hit'] else '✗'} | "
                f"{'✓' if c['dg_fdr_hit'] else '✗'} | "
                f"{'✓' if c['docetl_hit'] else '✗'} |"
            )
        md.append("")

    dump_section("DocETL ✓ / DataGatherer ✗", cats["docetl_only"])
    dump_section("DataGatherer ✓ / DocETL ✗", cats["dg_only"])
    dump_section("Both missed", cats["both_missed"])

    # Also list DocETL false positives — likely hallucinations
    md.append("## DocETL predictions NOT in ground truth (possible hallucinations/noise)\n")
    md.append("| PMCID | identifier | pred_repo |")
    md.append("|---|---|---|")
    for fp in fp_docetl[:20]:
        md.append(f"| {fp['pmcid']} | `{fp['ident']}` | {fp['pred_repo']} |")
    md.append("")

    (OUT_DIR / "failure_cases.md").write_text("\n".join(md))
    print(f"Wrote {OUT_DIR / 'failure_cases.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
