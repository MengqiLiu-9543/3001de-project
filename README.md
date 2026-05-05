# Project 8 — Data Discovery in Scientific Publications

**Course**: NYU CS-GY 3001 Data Engineering (Spring 2026)
**Team `rwadata`**: Mengqi Liu (ml9543) · Jintong Li (jl13640) · Bo Yu (by2566)

We compare two systems for extracting dataset references from scientific
papers, evaluating on **DataRef-EXP** (21 curated papers, 47 records) and
**DataRef-REV** (1,242 representative papers, 1,883 records).

- **DataGatherer** — a specialized, paper-published tool by VIDA-NYU.
  Two strategies:
  - **RTR** (Retrieve-Then-Read): XPath rules extract data-availability
    sections, only those snippets are sent to the LLM.
  - **FDR** (Full-Document Read): the entire paper is sent to the LLM.
- **DocETL** — a general-purpose declarative LLM document-processing
  framework.
  - **v0** baseline (15-line prompt).
  - **v1** iterated prompt (120 lines + repository catalog + extraction
    rules).

All four configurations use the **same LLM**: Kimi
`kimi-k2-0905-preview` (non-reasoning, 128k context). This isolates
pipeline architecture from model quality.

---

## Headline Results

### DataRef-EXP (21 papers, 47 records, **N = 3 runs per system**, mean ± std)

| System | Predictions | Loose Precision | Loose Recall | **Loose F1** | **Cost (USD)** |
|---|---|---|---|---|---|
| **DG-RTR** | 36.0 ± 1.7 | 95.4% ± 1.4 | 73.1% ± 2.5 | **82.7% ± 1.1** | **$0.011** |
| **DG-FDR** | 37.7 ± 2.9 | 93.3% ± 6.8 | 74.5% ± 0.0 | **82.7% ± 2.8** | $0.621 |
| **DocETL v0** | 37.3 ± 3.1 | 85.1% ± 5.3 | 67.4% ± 2.5 | **75.1% ± 1.9** | $0.297 |
| **DocETL v1** | 47.0 ± 2.0 | 80.8% ± 0.8 | 80.9% ± 4.3 | **80.8% ± 2.5** | $0.306 |

On EXP, DG-RTR / DG-FDR / DocETL v1 are **statistically indistinguishable
on F1** (confidence intervals overlap). DG-RTR wins on cost (27× cheaper
than DocETL v1, 54× cheaper than DG-FDR).

### DataRef-REV (1,242 papers, 1,883 records, N = 1)

| System | Predictions | Loose Precision | Loose Recall | **Loose F1** | **Cost (USD)** |
|---|---|---|---|---|---|
| **DG-RTR** | 1,275 | 75.06% | 50.82% | **60.61%** | **$0.50** |
| **DG-FDR** | 2,149 | 76.17% | **86.94%** | **81.20%** ← highest F1 | $32.47 |
| **DocETL v1** | 2,802 | 66.35% | **98.73%** | **79.36%** | ~$18 |

(DocETL v1 was *not* run on REV with v0; v0 was only used for prompt
ablation on EXP.)

### Cross-benchmark picture

| | EXP | REV | Δ |
|---|---|---|---|
| DG-RTR | 82.7% / $0.011 | **60.6%** / $0.50 | F1 ↓ 22 pt |
| DG-FDR | 82.7% / $0.621 | **81.2%** / $32.47 | F1 ≈ same |
| DocETL v1 | 80.8% / $0.306 | **79.4%** / $18 | F1 ≈ same |

**Key finding.** "Specialized vs generic" is not the right axis. What
matters is whether the tool reads the whole document (DG-FDR, DocETL v1)
or relies on structural rules (DG-RTR's XPath data-availability section
detection).

DG-RTR's XPath assumes every PMC paper has a `<section>` whose `h2`/`h3`
contains "Data Availability" — but **51.6% of REV papers (641/1242) do
not** (most embed PXD/GSE accessions inside Methods sub-sections without
a dedicated DA header). Those 641 papers contain 899 ground-truth
records (47.7% of all REV GT) that DG-RTR can never see — a hard recall
ceiling.

DG-FDR and DocETL v1 don't have this limitation because they read every
section.

### Cost / accuracy trade-off (REV)

```
Cost (log)  $0.5     $18      $32
            DG-RTR   v1       FDR
F1          60.6%    79.4%    81.2%
```

- DG-RTR: only viable choice at industrial scale; 51% recall is too low
  for many use cases.
- DG-FDR: best F1 but 65× more expensive than RTR.
- DocETL v1: best recall (99%); precision suffers but failure mode is
  benign (over-extraction → manual filtering is easier than missing
  data).

---

## Discovered Failure Modes

### 1. DG-RTR's XPath section-detection brittleness (REV recall collapse)

DG's `data-gatherer/data_gatherer/config/retrieval_patterns.json` only
matches `<section>` elements whose `h2`/`h3` text contains "Data
Availability". REV biomedical papers commonly embed accession sentences
(`"deposited to ProteomeXchange ... PXD012345"`) in Methods sub-sections
("MS Data Analysis", "Proteomics", etc.) without a dedicated DA section,
making them invisible to RTR.

### 2. Moonshot Kimi content-filter rejections (DocETL v1, DG-FDR)

When a generic pipeline sends the **entire paper text** (~25k tokens) to
the LLM, the input is more likely to contain "high-risk" keywords (HIV,
genome editing, low-Earth orbit, paediatric trials...) that trigger
Moonshot's commercial content moderation. We confirmed this is upstream
of any pipeline code: a direct `requests` call to Moonshot's API with
the paper text returns the same `BadRequestError(content_filter)`.

We worked around this in DocETL v1 by wrapping `litellm.completion` to
convert content-filter rejections into empty-references responses, so a
single rejected paper doesn't kill the whole pipeline. DG-FDR's internal
exception handling already does this.

In our REV run, **2 of 1,241 papers** triggered the filter:
`PMC6434046` (genome editing) and `PMC6501615` (Deinococcus radiodurans
exposed to low-Earth-orbit vacuum).

### 3. GT-incomplete vs. system-FP conflation

Inspection of DocETL v1's 9 EXP false positives revealed:
- 6 are reused datasets (e.g., GSE10327 in PMC11066909) that exist in
  the paper but the GT annotator excluded.
- 2 are field-mapping errors (URL placed in `dataset_identifier`).
- 1 is a synonymous mirror (jPOST `JPST002506` ≡ ProteomeXchange
  `PXD049309`).

**0 hallucinations**. The 82.7% precision number underestimates v1's
extraction quality.

### 4. v2 data_role experiment (failed hypothesis, kept as documentation)

We tested whether labeling each prediction as "primary" (deposited by
this paper) vs "reused" (cited from prior work) and filtering to
primary-only could raise precision. **Falsified**: GT contains many
reused datasets (PMC11129317 is a meta-analysis whose 8 reused PDC
datasets ARE the research subject). Primary-only filtering dropped F1
from 86.9% to 65.8%. The GT annotation philosophy is paper-level, not
record-level.

See `docetl_pipeline/extract_v2.yaml` for the experiment.

---

## Repository Layout

```
3001de-project/
├── README.md                  ← this file
├── proposal.md / proposal.pdf
├── .env.example               ← copy to .env, fill in your Kimi API key
├── .gitignore
├── scripts/
│   ├── fetch_papers.py        ← download PMC HTML
│   ├── run_datagatherer.py    ← DG runner (RTR or FDR), with --resume + DG_MAX_USD
│   ├── run_docetl.py          ← DocETL runner (in-process, with content-filter
│   │                            workaround and LiteLLM token tracking)
│   ├── eval.py                ← record-level P/R/F1 with multi-signature matching
│   ├── compare.py             ← regenerate summary.md from system outputs
│   └── failure_cases.py       ← 4-category disagreement dump
├── docetl_pipeline/
│   ├── extract.yaml           ← v0 (15-line prompt)
│   ├── extract_v1.yaml        ← v1 (120-line prompt with repo catalog) — final
│   ├── extract_v2.yaml        ← v2 (v1 + data_role classification, falsified)
│   ├── extract_rev_v0.yaml    ← v0 retargeted at REV corpus
│   └── extract_rev_v1.yaml    ← v1 retargeted at REV corpus
├── data/
│   └── benchmarks/
│       ├── EXP_groundtruth.csv          ← 47 records over 21 papers
│       ├── REV_sample_groundtruth.csv   ← 1,883 records over 1,242 papers
│       └── Full_REV_dataset_citation_records_Table.parquet
├── outputs/
│   │ ── EXP results ──
│   ├── dg_rtr_EXP.jsonl + .meta.json    (last single run; superseded by run1-3)
│   ├── dg_fdr_EXP.jsonl + .meta.json
│   ├── docetl_v0_EXP.jsonl + .meta.json
│   ├── docetl_v1_EXP.jsonl + .meta.json
│   ├── docetl_v2_EXP.jsonl + .meta.json
│   ├── *_EXP_run{1,2,3}.jsonl + .meta.json   (12 N=3 reproducibility runs)
│   ├── metrics.json                     ← single-run EXP metrics
│   ├── metrics_3runs.json               ← N=3 EXP aggregate (mean/std)
│   ├── summary.md                       ← human-readable EXP comparison
│   ├── failure_cases.md / .json         ← 4-category disagreement
│   └── rev/
│       ├── dg_rtr_REV.jsonl + .meta.json    (1242 papers, $0.50)
│       ├── dg_fdr_REV.jsonl + .meta.json    (1242 papers, $32.47)
│       └── docetl_v1_REV.jsonl + .meta.json (1241 papers; 2 filter-blocked)
├── data-gatherer/             ← vendored upstream (with Kimi compat patch)
└── patches/
    └── datagatherer-kimi-support.patch  ← our DG patch
```

`data/papers/` (cached EXP HTML, ~10 MB) and `data/papers_rev/` (cached
REV HTML, ~516 MB) are regenerated by `scripts/fetch_papers.py` and not
committed. Likewise `outputs/*_raw.json` (DocETL intermediate JSON,
~108 MB for REV) and `outputs/**/docetl_intermediates_*/` (LLM
per-call cache).

---

## Reproduction

### 1. Clone

```bash
git clone https://github.com/MengqiLiu-9543/3001de-project.git
cd 3001de-project
```

### 2. Get the Kimi API key

We share a Kimi (Moonshot) account. **Ask Mengqi** for the `.env` file
(WeChat / DM), drop it in the project root.

If you want your own key, sign up at <https://platform.moonshot.cn>,
copy `.env.example` to `.env`, paste your key.

### 3. Python environment

```bash
conda create -n de3001 python=3.11 -y
conda activate de3001

pip install pandas requests lxml beautifulsoup4 python-dotenv openai \
            "pyrate-limiter>=3.7,<4" docetl litellm

pip install -e ./data-gatherer
```

### 4. EXP — fetch papers and run all 4 systems

```bash
# Fetch 21 PMC papers (~30s)
python scripts/fetch_papers.py

# DataGatherer (~3 min total)
python scripts/run_datagatherer.py --strategy rtr --out outputs/dg_rtr_EXP.jsonl
python scripts/run_datagatherer.py --strategy fdr --out outputs/dg_fdr_EXP.jsonl

# DocETL (~2 min total, in-process with cost tracking)
python scripts/run_docetl.py --yaml docetl_pipeline/extract.yaml    --out outputs/docetl_v0_EXP.jsonl
python scripts/run_docetl.py --yaml docetl_pipeline/extract_v1.yaml --out outputs/docetl_v1_EXP.jsonl

# Aggregate
python scripts/compare.py        # → outputs/summary.md + metrics.json
python scripts/failure_cases.py  # → outputs/failure_cases.md
```

EXP total cost: **~$1.25** (mostly DG-FDR @ $0.62).

### 5. EXP — N=3 reproducibility runs (optional, ~$3 extra)

To regenerate the N=3 aggregated numbers in this README:

```bash
for i in 1 2 3; do
  rm -rf ~/.cache/docetl   # clear DocETL LLM cache for independence
  python scripts/run_datagatherer.py --strategy rtr --out outputs/dg_rtr_EXP_run${i}.jsonl
  python scripts/run_datagatherer.py --strategy fdr --out outputs/dg_fdr_EXP_run${i}.jsonl
  python scripts/run_docetl.py --yaml docetl_pipeline/extract.yaml    --out outputs/docetl_v0_EXP_run${i}.jsonl
  python scripts/run_docetl.py --yaml docetl_pipeline/extract_v1.yaml --out outputs/docetl_v1_EXP_run${i}.jsonl
done
```

We aggregated these runs in an analysis script (loaded each pair, ran
`compute_metrics(mode="loose")`, computed mean/std). Output:
`outputs/metrics_3runs.json`.

### 6. REV — fetch and run on the larger benchmark

```bash
# Fetch 1241 PMC papers (~60 min, NCBI rate-limited)
FETCH_GT_CSV=data/benchmarks/REV_sample_groundtruth.csv \
FETCH_PAPERS_DIR=data/papers_rev \
FETCH_CORPUS_JSON=data/papers_rev/corpus.json \
  python scripts/fetch_papers.py

# DG-RTR (~2 hours, ~$0.50)
python scripts/run_datagatherer.py --strategy rtr \
  --gt-csv data/benchmarks/REV_sample_groundtruth.csv \
  --out outputs/rev/dg_rtr_REV.jsonl --resume

# DG-FDR (~5 hours, ~$32, optional --resume to handle interrupts)
DG_MAX_USD=37 python scripts/run_datagatherer.py --strategy fdr \
  --gt-csv data/benchmarks/REV_sample_groundtruth.csv \
  --out outputs/rev/dg_fdr_REV.jsonl --resume

# DocETL v1 on REV (~50 min, ~$18)
python scripts/run_docetl.py --yaml docetl_pipeline/extract_rev_v1.yaml \
  --out outputs/rev/docetl_v1_REV.jsonl
```

`DG_MAX_USD` is a hard kill switch we added to `run_datagatherer.py` —
it stops before starting any new paper if cumulative cost would exceed
the cap. Useful when running on a tight Moonshot quota. (Per-paper
results are flushed to disk line-by-line so a kill mid-paper still
preserves all completed papers.)

### 7. Evaluating REV

```python
import sys, json
from pathlib import Path
sys.path.insert(0, 'scripts')
from eval import load_ground_truth, load_predictions, compute_metrics
import eval as eval_mod
eval_mod.GT_CSV = Path("data/benchmarks/REV_sample_groundtruth.csv")
gt = load_ground_truth(eval_mod.GT_CSV)
for name, p in [
    ("DG-RTR",   "outputs/rev/dg_rtr_REV.jsonl"),
    ("DG-FDR",   "outputs/rev/dg_fdr_REV.jsonl"),
    ("DocETL v1","outputs/rev/docetl_v1_REV.jsonl"),
]:
    pred = load_predictions(Path(p))
    l = compute_metrics(gt, pred, mode="loose")["micro"]
    n = sum(len(v) for v in pred.values())
    print(f"{name:10s}  preds={n:5d}  P={l['precision']*100:.2f}  R={l['recall']*100:.2f}  F1={l['f1']*100:.2f}")
```

---

## Evaluation Methodology

The scorer (`scripts/eval.py`) uses **record-level greedy bipartite
matching** between ground-truth and prediction records. Each record is
a frozenset of `(id_key, repo_key)` signatures derived from
`identifier`, `dataset_webpage`, `repo_link` (and predicted equivalents),
so credit is given for matching by either accession or URL.

**Strict** mode requires both identifier and repository (after alias
canonicalization, e.g., `"GEO" / "Gene Expression Omnibus" / "NCBI GEO"`
all → `GEO`) to match.

**Loose** mode requires only the identifier or URL to match. We adopt
loose F1 as the headline because:
1. The strict-loose gap averages **+14.4 points** across our four
   systems on EXP, almost entirely attributable to label-form noise
   (e.g., `"PRIDE"` vs `"ProteomeXchange"` for the same `PXD` accession).
2. The gap *varies by system* (+9.5 to +21 points), so strict
   comparisons confound extraction quality with prompt-label conventions.
3. Identifiers are routable on their own: `PXD*` resolves to
   ProteomeXchange regardless of whether the system labelled the repo
   correctly. This matches downstream user value.

We report both modes; loose is primary.

---

## Limitations

The full discussion lives in `outputs/summary.md` and `outputs/failure_cases.md`.
Selected highlights:

1. **L0** (single benchmark family). DataRef is one source. Generalizing
   to broader corpora (e.g., bioRxiv, ICML papers) is future work.
2. **L1** (single LLM). All systems use Kimi. A different model (e.g.,
   GPT-4o) might shift relative rankings.
3. **L2** (GT incompleteness). Sec. "Discovered Failure Modes" #3 above
   shows several "FPs" are real datasets the GT missed. Manual audit
   would raise both systems' precision.
4. **L3** (asymmetric prompt effort). DocETL v1 has a hand-tuned 120-line
   prompt + repo catalog; DataGatherer is run with stock few-shot
   templates. Equivalent prompt iteration on DG would likely close the
   v1 recall gap.
5. **L4** (LLM stochasticity even at temp=0). Single-run F1 has ~3 pt
   std across our N=3 reproducibility runs. We report mean ± std for
   EXP. REV is N=1 due to cost — its absolute numbers carry similar
   ±3 pt uncertainty.
6. **L5** (commercial content moderation). Moonshot's content filter
   rejects whole prompts on safety classifier hits. Affects 2/1241 REV
   papers in our run. Generic full-document pipelines inherit this risk
   structurally; tools that pre-scope to small text snippets (DG-RTR)
   are immune.
7. **L6** (input format asymmetry). DocETL receives BeautifulSoup-stripped
   PMC HTML; DataGatherer fetches its own JATS XML via NCBI E-utils.
   Both ultimately read the same source content, but with different
   noise profiles.
8. **L7** (REV is N=1). Single REV run; no reproducibility variance
   bound. EXP variance suggests ±3 pt uncertainty on REV F1 numbers.

---

## References

- Marini et al., "Data Gatherer: LLM-powered Dataset Reference Extraction
  from Scientific Literature." *SDP 2025*.
  <https://github.com/VIDA-NYU/data-gatherer>
- Shankar et al., "DocETL: Agentic Query Rewriting and Evaluation for
  Complex Document Processing." *VLDB 2025*.
  <https://ucbepic.github.io/docetl/>
- DataRef-EXP / DataRef-REV benchmark:
  <https://doi.org/10.5281/zenodo.15549086>
