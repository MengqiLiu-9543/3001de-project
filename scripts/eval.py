"""Evaluate a system output against DataRef-EXP ground truth.

System output format (per paper):
    {"pmcid": "PMC6141466", "predictions": [{"dataset_identifier": "...",
                                             "repository": "...", ...}, ...]}

Ground truth from EXP_groundtruth.csv:
    citing_publication_link, dataset_webpage, repo_link, identifier, repository

Usage:
    python scripts/eval.py outputs/dg_rtr_EXP.jsonl --name dg_rtr
    python scripts/eval.py outputs/docetl_v0_EXP.jsonl --name docetl_v0 \
                           --out outputs/metrics_docetl_v0.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GT_CSV = PROJECT_ROOT / "data" / "benchmarks" / "EXP_groundtruth.csv"


# ---------- Normalization --------------------------------------------------

# Canonical repository names. Keys are lowercase after stripping punctuation.
REPO_ALIASES = {
    "dbgap": "dbGaP",
    "dbgapdatabaseofgenotypesandphenotypes": "dbGaP",
    "pride": "PRIDE",
    "prideproteomicsidentificationdatabase": "PRIDE",
    "proteomexchange": "ProteomeXchange",
    "proteomexchangeconsortium": "ProteomeXchange",
    "massive": "MassIVE",
    "massivemassspectrometryinteractivevirtualenvironment": "MassIVE",
    "geo": "GEO",
    "geneexpressionomnibus": "GEO",
    "ncbigeo": "GEO",
    "sra": "SRA",
    "sequencereadarchive": "SRA",
    "ncbisra": "SRA",
    "bioproject": "BioProject",
    "ncbibioproject": "BioProject",
    "ena": "ENA",
    "europeannucleotidearchive": "ENA",
    "ega": "EGA",
    "europeangenomephenomearchive": "EGA",
    "pdb": "PDB",
    "proteindatabank": "PDB",
    "rcsb": "PDB",
    "rcsbpdb": "PDB",
    "zenodo": "Zenodo",
    "figshare": "Figshare",
    "mendeleydata": "Mendeley",
    "mendeley": "Mendeley",
    "dryad": "Dryad",
    "pdc": "PDC",
    "proteomicdatacommons": "PDC",
    "proteomicdatacommonspdc": "PDC",
    "proteomicsdatacommons": "PDC",
    "iprox": "iProX",
    "jpost": "jPOST",
    "depmap": "DepMap",
    "dependencymapdepmap": "DepMap",
    "biostudies": "BioStudies",
    "arrayexpress": "ArrayExpress",
    "cptacassayportal": "CPTAC",
    "cptac": "CPTAC",
    "panoramapublic": "PanoramaPublic",
    "ddbj": "DDBJ",
    "genbank": "GenBank",
    "odensepatientdataexploratorynetwork": "OPEN",
    "odensepatientdataexplorativenetwork": "OPEN",
    "otherunknown": "Other",
    # URL-hostname-style values that DataGatherer emits as data_repository:
    "wwwebiacuk": "PRIDE",  # ebi.ac.uk/pride/...
    "ebiacuk": "PRIDE",
    "massiveucsdedu": "MassIVE",
    "massivemsucsdedu": "MassIVE",
    "egaarchiveorg": "EGA",
    "wwwiproxcn": "iProX",
    "wwwiproxorg": "iProX",
    "iproxcn": "iProX",
    "proteomecentralproteomexchangeorg": "ProteomeXchange",
    "ncbinlmnihgov": "GenBank",
    "pdccancergov": "PDC",
    "proteomicdatacommonscancergov": "PDC",
    "wwwproteomicdatacommonscancergov": "PDC",
    "databroadinstituteorg": "Broad",
    "broadinstitute": "Broad",
    "datafromthebroadinstitute": "Broad",
    "broad": "Broad",
    "depmaporg": "DepMap",
    "doiorg": "DOI",
    "figsharecom": "Figshare",
    "zenodoorg": "Zenodo",
    "datamendeleycom": "Mendeley",
    "dryadorg": "Dryad",
    "ngdccncbacn": "NGDC",
    "ionpath": "IONpath",
    "na": "",  # 'n/a' predictions — drop
}


def normalize_repo(name) -> str:
    if name is None:
        return ""
    if not isinstance(name, str):
        try:
            import math
            if isinstance(name, float) and math.isnan(name):
                return ""
        except Exception:
            pass
        name = str(name)
    if not name.strip():
        return ""
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return REPO_ALIASES.get(s, name.strip())


_NA_SENTINELS = {"", "n/a", "na", "none", "null", "nan", "n.a.", "-"}


def normalize_identifier(ident) -> str:
    """Lowercase, strip hash/version suffix, strip punctuation.

    phs001049.v1.p1 -> phs001049
    PRJNA306801     -> prjna306801
    GSE12345        -> gse12345
    "n/a" / "na" / "" / NaN -> ""  (sentinel placeholders count as empty)
    """
    if ident is None:
        return ""
    if not isinstance(ident, str):
        # pandas NaN floats, ints from some repositories, etc.
        try:
            import math
            if isinstance(ident, float) and math.isnan(ident):
                return ""
        except Exception:
            pass
        ident = str(ident)
    s = ident.strip()
    if not s:
        return ""
    # Strip URL prefixes (systems sometimes output DOIs as full URLs).
    s = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[#\s]+", "", s)
    # Strip version suffixes like .v1, .v1.p2 (common in dbGaP).
    s = re.sub(r"\.v\d+(\.p\d+)?$", "", s, flags=re.IGNORECASE)
    s = s.rstrip("/")
    s_lower = s.lower()
    # Treat n/a-style placeholders as empty.
    if s_lower in _NA_SENTINELS:
        return ""
    return s_lower


def record_signatures(
    ident,
    repository,
    *url_fields,
) -> frozenset[tuple[str, str]]:
    """Return ALL (id_key, repo_key) tuples a record can match against.

    A record can match by its identifier OR by any of its URL/repo-link
    fields. This avoids the round-1 asymmetry where DG got credit on a row
    by emitting "n/a"+URL while DocETL emitted "<label>"+same URL and was
    scored as wrong.
    """
    repo = normalize_repo(repository)
    sigs: set[tuple[str, str]] = set()
    nid = normalize_identifier(ident)
    if nid:
        sigs.add((nid, repo))
    for u in url_fields:
        if u is None:
            continue
        nu = normalize_identifier(u)
        if nu:
            sigs.add((nu, repo))
    return frozenset(sigs)


# ---------- Data loading ---------------------------------------------------


def load_ground_truth(csv_path: Path = GT_CSV) -> dict[str, list[frozenset[tuple[str, str]]]]:
    """Return {PMCID: [record_signatures, ...]}.

    Each ground-truth row becomes a frozenset of all (id_key, repo_key)
    tuples it can match against — derived from `identifier`,
    `dataset_webpage`, AND `repo_link` so that even rows with only a portal
    URL (e.g. AstraZeneca) can be scored.
    """
    df = pd.read_csv(csv_path)
    gt: dict[str, list[frozenset[tuple[str, str]]]] = defaultdict(list)
    for _, row in df.iterrows():
        url = str(row["citing_publication_link"])
        m = re.search(r"PMC\d+", url)
        if not m:
            continue
        pmcid = m.group(0)
        sigs = record_signatures(
            row.get("identifier"),
            row.get("repository"),
            row.get("dataset_webpage"),
            row.get("repo_link"),
        )
        if sigs:
            gt[pmcid].append(sigs)
    return dict(gt)


def load_predictions(jsonl_path: Path) -> dict[str, list[frozenset[tuple[str, str]]]]:
    """Load system output. Returns {PMCID: [record_signatures, ...]}.

    Each prediction record is represented by its full set of possible
    matching keys (identifier + URL + dataset_webpage), so any URL match is
    credited regardless of how the system labeled the identifier.
    """
    preds: dict[str, list[frozenset[tuple[str, str]]]] = defaultdict(list)
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            pmcid = record["pmcid"]
            for pred in record.get("predictions", []):
                sigs = record_signatures(
                    pred.get("dataset_identifier"),
                    pred.get("repository"),
                    pred.get("url"),
                    pred.get("dataset_webpage"),
                )
                if sigs:
                    preds[pmcid].append(sigs)
    return dict(preds)


# ---------- Metrics --------------------------------------------------------


def _project(sigs: frozenset[tuple[str, str]], mode: str) -> frozenset:
    """Project a record's signatures down to the matching unit for the mode.

    strict = (id, repo) pair must match
    loose  = id alone must match
    """
    if mode == "loose":
        return frozenset(s[0] for s in sigs)
    return sigs


def _match_records(gt_records, pred_records, mode):
    """Greedy bipartite matching between gt and pred records.

    Two records match if their projected signature sets intersect at all.
    Returns (tp, fp, fn) plus the set of matched pred indices for visibility.
    """
    gt_sigs = [_project(r, mode) for r in gt_records]
    pred_sigs = [_project(r, mode) for r in pred_records]
    used_pred = set()
    tp = 0
    for g in gt_sigs:
        for i, p in enumerate(pred_sigs):
            if i in used_pred:
                continue
            if g & p:
                tp += 1
                used_pred.add(i)
                break
    fn = len(gt_sigs) - tp
    fp = len(pred_sigs) - len(used_pred)
    return tp, fp, fn, used_pred


def compute_metrics(
    gt: dict[str, list[frozenset[tuple[str, str]]]],
    pred: dict[str, list[frozenset[tuple[str, str]]]],
    mode: str = "strict",
) -> dict:
    """mode = 'strict' (id+repo) or 'loose' (id only).

    Uses record-level greedy matching: a gt record is a TP if any pred
    record in the same paper shares at least one (key, repo) signature
    (strict) or one key (loose). Each pred record can match at most one
    gt record to avoid double-counting.
    """
    all_papers = set(gt.keys()) | set(pred.keys())

    tp_total = fp_total = fn_total = 0
    per_paper = []
    for pmcid in sorted(all_papers):
        gs = gt.get(pmcid, [])
        ps = pred.get(pmcid, [])
        tp, fp, fn, _ = _match_records(gs, ps, mode)
        tp_total += tp
        fp_total += fp
        fn_total += fn
        precision_p = tp / (tp + fp) if (tp + fp) else 0.0
        recall_p = tp / (tp + fn) if (tp + fn) else 0.0
        f1_p = (
            2 * precision_p * recall_p / (precision_p + recall_p)
            if (precision_p + recall_p)
            else 0.0
        )
        per_paper.append(
            {
                "pmcid": pmcid,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(precision_p, 3),
                "recall": round(recall_p, 3),
                "f1": round(f1_p, 3),
                "ground_truth": [sorted(_project(r, mode)) for r in gs],
                "predictions": [sorted(_project(r, mode)) for r in ps],
            }
        )

    precision = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    recall = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "mode": mode,
        "micro": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp_total,
            "fp": fp_total,
            "fn": fn_total,
        },
        "per_paper": per_paper,
    }


def per_repo_recall(
    gt: dict[str, list[frozenset[tuple[str, str]]]],
    pred: dict[str, list[frozenset[tuple[str, str]]]],
) -> dict[str, dict[str, float]]:
    """Recall broken down by ground truth repository (loose match).

    A gt record is "hit" if any of its (id) keys appear among any of the
    pred records' loose-projected keys (id alone, ignoring repo).
    """
    by_repo_gt: Counter[str] = Counter()
    by_repo_hit: Counter[str] = Counter()
    for pmcid, gt_records in gt.items():
        pred_keys = set()
        for r in pred.get(pmcid, []):
            for k in _project(r, "loose"):
                pred_keys.add(k)
        for r in gt_records:
            # Each gt record has 1+ signatures; the "repo" of the record is
            # whichever non-empty repo string is in those signatures.
            repo = ""
            for _ident, _repo in r:
                if _repo:
                    repo = _repo
                    break
            by_repo_gt[repo] += 1
            loose_keys = _project(r, "loose")
            if loose_keys & pred_keys:
                by_repo_hit[repo] += 1
    out = {}
    for repo, total in sorted(by_repo_gt.items(), key=lambda x: -x[1]):
        out[repo] = {
            "gt_count": total,
            "hit_count": by_repo_hit[repo],
            "recall": round(by_repo_hit[repo] / total, 3) if total else 0.0,
        }
    return out


# ---------- CLI ------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", type=Path, help="System output jsonl")
    ap.add_argument("--name", default=None, help="System display name")
    ap.add_argument("--out", type=Path, default=None, help="Write metrics JSON")
    args = ap.parse_args()

    name = args.name or args.jsonl.stem
    gt = load_ground_truth()
    pred = load_predictions(args.jsonl)

    strict = compute_metrics(gt, pred, mode="strict")
    loose = compute_metrics(gt, pred, mode="loose")
    repo_breakdown = per_repo_recall(gt, pred)

    summary = {
        "system": name,
        "n_papers_gt": len(gt),
        "n_papers_pred": len(pred),
        "strict": strict["micro"],
        "loose": loose["micro"],
        "per_repo_recall": repo_breakdown,
    }

    print(f"=== {name} ===")
    print(f"GT papers: {len(gt)}   Pred papers: {len(pred)}")
    print(
        f"STRICT  P={strict['micro']['precision']:.3f}  "
        f"R={strict['micro']['recall']:.3f}  "
        f"F1={strict['micro']['f1']:.3f}  "
        f"TP={strict['micro']['tp']} FP={strict['micro']['fp']} FN={strict['micro']['fn']}"
    )
    print(
        f"LOOSE   P={loose['micro']['precision']:.3f}  "
        f"R={loose['micro']['recall']:.3f}  "
        f"F1={loose['micro']['f1']:.3f}  "
        f"TP={loose['micro']['tp']} FP={loose['micro']['fp']} FN={loose['micro']['fn']}"
    )
    print("Per-repo recall:")
    for repo, stats in repo_breakdown.items():
        print(f"  {repo:<20} {stats['hit_count']:>2}/{stats['gt_count']:<2}  R={stats['recall']:.2f}")

    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "strict_per_paper": strict["per_paper"],
                    "loose_per_paper": loose["per_paper"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
