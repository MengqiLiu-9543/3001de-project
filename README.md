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
  - **v0** baseline (27-line prompt).
  - **v1** iterated prompt (78 lines + repository catalog + extraction
    rules).

All four configurations use the **same LLM**: Kimi
`kimi-k2-0905-preview` (non-reasoning, 128k context). This isolates
pipeline architecture from model quality.

---

## Headline Results

### DataRef-EXP (21 papers, 47 records, **N = 3 runs per system**, mean ± std)

| System | Preds | Loose P | Loose R | **Loose F1** | Strict P | Strict R | **Strict F1** | **Cost (USD)** |
|---|---|---|---|---|---|---|---|---|
| **DG-RTR** | 36.0 ± 1.7 | 95.4% ± 1.4 | 73.1% ± 2.5 | **82.7% ± 1.1** | 79.9% ± 7.3 | 61.0% ± 2.5 | 69.1% ± 4.3 | **$0.011** |
| **DG-FDR** | 37.7 ± 2.9 | 93.3% ± 6.8 | 74.5% ± 0.0 | **82.7% ± 2.8** | 72.9% ± 6.2 | 58.2% ± 1.2 | 64.6% ± 3.1 | $0.621 |
| **DocETL v0** | 37.3 ± 3.1 | 85.1% ± 5.3 | 67.4% ± 2.5 | **75.1% ± 1.9** | 63.8% ± 8.5 | 50.4% ± 3.3 | 56.2% ± 5.1 | $0.297 |
| **DocETL v1** | 47.0 ± 2.0 | 80.8% ± 0.8 | 80.9% ± 4.3 | **80.8% ± 2.5** | 70.2% ± 1.3 | 70.2% ± 4.3 | 70.2% ± 2.8 | $0.306 |

On EXP, DG-RTR / DG-FDR / DocETL v1 are **statistically indistinguishable
on Loose F1** (confidence intervals overlap). DG-RTR wins on cost (27×
cheaper than DocETL v1, 54× cheaper than DG-FDR). All four systems drop
under Strict scoring; we explain why in the Evaluation Methodology section
below, and adopt Loose F1 as the primary comparison metric.

### DataRef-REV (1,242 papers, 1,883 records, N = 1)

| System | Preds | Loose P | Loose R | **Loose F1** | Strict P | Strict R | **Strict F1** | **Cost (USD)** |
|---|---|---|---|---|---|---|---|---|
| **DG-RTR** | 1,275 | 75.06% | 50.82% | **60.61%** | 66.04% | 44.72% | 53.32% | **$0.50** |
| **DG-FDR** | 2,149 | **76.17%** | 86.94% | 81.20% | 69.47% | 79.29% | 74.06% | $32.47 |
| **DocETL v1** | 2,612 | 71.13% | **98.67%** | **82.67%** ← highest | 64.62% | **89.64%** | **75.11%** ← highest | $17.67 |

(DocETL v1 was *not* run on REV with v0; v0 was only used for prompt
ablation on EXP.)

### Cross-benchmark picture

| | EXP | REV | Δ |
|---|---|---|---|
| DG-RTR | 82.7% / $0.011 | **60.6%** / $0.50 | F1 ↓ 22 pt |
| DG-FDR | 82.7% / $0.621 | **81.2%** / $32.47 | F1 ≈ same |
| DocETL v1 | 80.8% / $0.306 | **82.7%** / $17.67 | F1 ↑ 2 pt |

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
Cost (log)  $0.5     $17.67   $32
            DG-RTR   v1       FDR
F1          60.6%    82.7%    81.2%
```

- DG-RTR: only viable choice at industrial scale; 51% recall is too low
  for many use cases.
- DG-FDR: highest precision among full-document readers (76%), but ~2×
  the cost of v1 for ~1.5 pt lower F1.
- DocETL v1: highest F1 (82.7%) and recall (99%) on REV; precision is
  lower than DG-FDR (71% vs 76%) because the generic LLM consistently
  picks up reused public datasets cited in Methods sections, while
  DG-FDR's shorter and less aggressive prompt produces this behavior
  less often.

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

### 3. GT-incomplete vs. system-FP conflation

Inspection of DocETL v1's 9 EXP false positives revealed:
- 5 are reused public datasets (4 GSE accessions + 1 PDC ID in
  PMC11066909) cited from prior work; the GT for that paper credits
  only the one PXD the authors deposited themselves.
- 1 is a deposited PXD in PMC11015306 — clearly stated in the paper as
  deposited to ProteomeXchange, but the GT has no record for that paper
  at all (DG-FDR also picks up the exact same PXD every run, confirming
  this is a benchmark gap).
- 2 are field-mapping errors (URL placed in `dataset_identifier`).
- 1 is a synonymous mirror (jPOST `JPST002506` ≡ ProteomeXchange
  `PXD049309`).

**0 hallucinations**. The headline precision number on EXP underestimates
v1's actual extraction quality.

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
│   ├── extract.yaml           ← v0 (27-line prompt)
│   ├── extract_v1.yaml        ← v1 (78-line prompt with repo catalog) — final
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

### 2. Get a Kimi API key

The pipeline talks to Kimi through its OpenAI-compatible HTTP API, so
all you need is a Kimi API key.

1. Sign up at <https://platform.moonshot.ai> and create an API key in
   the dashboard.
2. Copy the example env file and paste your key into it:

   ```bash
   cp .env.example .env
   # then open .env and replace `your_kimi_key_here` with your real key
   ```

Estimated cost for the full EXP reproduction in Section 4 below is
**~$1.25 USD** (a few cents per single-paper smoke test). REV reproduction
in Section 6 is much more expensive (~$50 total) — we recommend running
EXP only unless you have a specific reason to re-run REV.

> **Why an `.env` file at all?** API keys are credentials — committing
> them to a public repo would let anyone drain the account. Our
> `.gitignore` excludes `.env`; only the `.env.example` template (no key)
> is checked in.

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
  rm -f ~/.cache/docetl/llm/cache.db   # clear LiteLLM cache for independence
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

# DocETL v1 on REV (~12 min, ~$17.67)
# Optionally clear the LiteLLM cache first to ensure fresh API calls:
#   rm -f ~/.cache/docetl/llm/cache.db
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

**Loose** mode requires only the identifier or URL to match.

### Why Strict F1 drops, and why Loose is our primary metric

Across all four systems, every strict miss we audited had the same shape:
the system extracted the right `identifier`, but tagged it with a
*different but equivalent* repository name from the one the GT used.
In other words, the system found the right dataset, but used one of two
interchangeable names for the host repository (e.g. `"PRIDE"` instead of
`"ProteomeXchange"`). Strict scoring counts these as misses even though
both names point to the same record. Concretely:

| GT canonical | Predicted canonical | Cases (EXP) |
|---|---|---|
| `ProteomeXchange` | `PRIDE` | 14 (across all 4 systems) |
| `PDB` | `DOI` / `Other` | 6 |
| `SRA` | `www.ncbi.nlm.nih.gov` | 2 |
| `dbGaP` | `www.ncbi.nlm.nih.gov` | 1 |

**The PRIDE / ProteomeXchange case is dominant.** PRIDE is a founding
member of the [ProteomeXchange](https://www.proteomexchange.org/)
Consortium; PXD accession numbers live in a *common identifier space*
shared across PRIDE, MassIVE, PeptideAtlas, and jPOST. A single PXD ID
(e.g. `PXD047284`) resolves to the same data record from either the
ProteomeXchange portal or the PRIDE archive. Treating `"PRIDE"` and
`"ProteomeXchange"` as different repositories under Strict scoring
charges the system a point for using one of two interchangeable labels.

We adopt Loose F1 as the headline metric because:
1. The strict-loose gap on EXP averages **+15.3 points** across our four
   systems (range +10.6 to +18.9), and on REV averages **+7.3 points**
   (range +7.1 to +7.6). Most of this gap is the label-equivalence noise
   above, not extraction errors.
2. The gap *varies by system*, so strict comparisons confound extraction
   quality with prompt-label conventions.
3. Identifiers are routable on their own: `PXD*` resolves to
   ProteomeXchange regardless of whether the system labelled the
   repository `PRIDE` or `ProteomeXchange`. This matches downstream user
   value (a dataset search service only needs the accession).

We report both modes; **Loose F1 is the primary comparison**, Strict F1
is provided alongside as a sanity check (and the system ranking under
Strict on REV is identical to the Loose ranking, with DocETL v1 highest).

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
4. **L3** (asymmetric prompt effort). DocETL v1 has a hand-tuned 78-line
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
