# Project 8 — Data Discovery in Scientific Publications

**Course**: NYU CS-GY 3001 Data Engineering (Spring 2026)
**Team `rwadata`**: Mengqi Liu (ml9543) · Jintong Li (jl13640) · Bo Yu (by2566)

We compare two systems for extracting dataset references from scientific papers
on the [DataRef-EXP benchmark](https://doi.org/10.5281/zenodo.15549086):

- **DataGatherer** — a specialized, paper-published tool by the VIDA-NYU group.
  Two strategies: Retrieve-Then-Read (RTR) and Full-Document Read (FDR).
- **DocETL** — a general-purpose declarative LLM document-processing framework.
  We test a baseline pipeline (v0) and an iterated version with a hand-tuned
  repository catalog prompt (v1).

Both systems use the same LLM backend: **Kimi `kimi-k2-0905-preview`** (non-reasoning, 128k context).

---

## Headline Results (DataRef-EXP, 21 papers / 47 ground-truth records)

| System | Strict F1 | Loose F1 | Loose Recall | Loose Precision | Cost |
|---|---|---|---|---|---|
| **DataGatherer RTR** | **74.7%** | **84.3%** | 74.5% | **97.2%** | **$0.012** |
| DataGatherer FDR    | 61.4% | 79.5% | 74.5% | 85.4% | $0.621 |
| DocETL v0 (base)    | 52.5% | 72.5% | 61.7% | 87.9% | ~$0.26 |
| **DocETL v1 (iterated)** | **74.0%** | **84.0%** | **89.4%** | 79.2% | ~$0.28 |

**Plain reading**: DataGatherer RTR and DocETL v1 are within **0.7 F1 points**
on both strict and loose metrics — statistically indistinguishable accuracy.
The two systems represent **different tradeoffs** rather than one dominating
the other:

- DG RTR is **24× cheaper** per run because it only sends the data availability
  section to the LLM (~600 tokens/paper vs ~22k tokens/paper).
- DocETL v1 has **+15 points higher recall** and catches dataset types DG misses
  (Mendeley DOIs, supplementary EGA accessions) — at the cost of more false
  positives.
- DG bundles a biomedical repository ontology that gives it strong priors;
  DocETL has to learn this from prompt examples.

See `outputs/summary.md` and `outputs/failure_cases.md` for the full breakdown.

---

## Repository Layout

```
3001de-project/
├── README.md                ← this file
├── proposal.md / proposal.pdf  ← original project proposal
├── .env.example             ← copy to .env, fill in your Kimi API key
├── .gitignore
├── scripts/
│   ├── fetch_papers.py        ← download PMC papers via NCBI efetch
│   ├── run_datagatherer.py    ← batch DG runner (RTR or FDR)
│   ├── run_docetl.py          ← DocETL pipeline runner
│   ├── eval.py                ← record-level P/R/F1 with multi-signature matching
│   ├── compare.py             ← regenerate summary.md from system outputs
│   └── failure_cases.py       ← 4-category disagreement dump
├── docetl_pipeline/
│   ├── extract.yaml           ← DocETL v0 (15-line prompt)
│   └── extract_v1.yaml        ← DocETL v1 (120-line prompt with repo catalog)
├── data/
│   └── benchmarks/            ← DataRef-EXP & REV ground truth (from Zenodo)
├── outputs/
│   ├── dg_rtr_EXP.jsonl       ← DG RTR predictions (+ .meta.json with cost/latency)
│   ├── dg_fdr_EXP.jsonl       ← DG FDR predictions
│   ├── docetl_v0_EXP.jsonl    ← DocETL v0 predictions
│   ├── docetl_v1_EXP.jsonl    ← DocETL v1 predictions
│   ├── metrics.json           ← machine-readable full metrics
│   ├── summary.md             ← human-readable comparison tables
│   └── failure_cases.md       ← 4-category disagreement analysis
└── patches/
    └── datagatherer-kimi-support.patch  ← our DG patch for Kimi compatibility
```

`data-gatherer/` (the vendored upstream repo) and `data/papers/` (cached PMC
articles) are **not** committed — they are large and you regenerate them with
the setup steps below.

---

## Reproduction

### 1. Clone

```bash
git clone https://github.com/MengqiLiu-9543/3001de-project.git
cd 3001de-project
```

### 2. Get the Kimi API key

The team uses a shared Kimi (Moonshot) account. **Ask Mengqi for the `.env`
file** (sent privately via WeChat / DM), drop it in the project root.

If you want your own key instead, sign up at <https://platform.moonshot.cn>,
then copy `.env.example` to `.env` and paste your key.

### 3. Set up the Python environment

```bash
conda create -n de3001 python=3.11 -y
conda activate de3001
pip install pandas requests lxml beautifulsoup4 python-dotenv openai \
            "pyrate-limiter>=3.7,<4" docetl
```

### 4. Clone DataGatherer and apply our Kimi-compatibility patch

```bash
git clone https://github.com/VIDA-NYU/data-gatherer.git
cd data-gatherer
git apply ../patches/datagatherer-kimi-support.patch
pip install -e .
cd ..
```

The patch adds Kimi/Moonshot support to DG (the upstream tool only ships with
GPT and Gemini routing). It modifies five files:

- `data_gatherer/env.py` — add `MOONSHOT_API_KEY`, `MOONSHOT_BASE_URL`
- `data_gatherer/data_gatherer.py` — add Kimi models to the
  `entire_document_models` allowlist
- `data_gatherer/parser/base_parser.py` — same allowlist patch and a
  token-counting branch for Kimi
- `data_gatherer/llm/llm_client.py` — add a `_call_moonshot` branch that uses
  chat completions (Kimi does not support OpenAI's Responses API), and
  normalize `developer` role messages to `system`

### 5. Fetch the EXP papers

```bash
python scripts/fetch_papers.py
```

Downloads 21 PMC articles via NCBI efetch into `data/papers/`. Takes ~30s
total with built-in 0.5s rate limiting.

### 6. Run the systems

```bash
# DataGatherer (~3 min total, two strategies)
python scripts/run_datagatherer.py --strategy rtr --out outputs/dg_rtr_EXP.jsonl
python scripts/run_datagatherer.py --strategy fdr --out outputs/dg_fdr_EXP.jsonl

# DocETL (~1 min total, two pipelines)
python scripts/run_docetl.py --yaml docetl_pipeline/extract.yaml    --out outputs/docetl_v0_EXP.jsonl
python scripts/run_docetl.py --yaml docetl_pipeline/extract_v1.yaml --out outputs/docetl_v1_EXP.jsonl
```

### 7. Compute metrics & failure cases

```bash
python scripts/compare.py        # → outputs/summary.md + metrics.json
python scripts/failure_cases.py  # → outputs/failure_cases.md
```

Total reproduction cost: ~$1.20 of Kimi credit.

---

## Evaluation Methodology

The scorer (`scripts/eval.py`) uses **record-level greedy bipartite matching**
between ground-truth and prediction records. Each record is represented as a
**frozenset of (id_key, repo_key) signatures** derived from the row's
identifier, dataset_webpage, and repo_link fields, so a system gets credit for
matching by either accession ID or canonical URL.

We report two matching modes:

- **Strict F1**: requires both identifier and repository label to match.
- **Loose F1**: only requires the identifier (or URL fallback) to match.
  Loose is the headline metric because the benchmark labels different
  repository conventions inconsistently (e.g., `BioProject` vs `SRA`,
  `PRIDE` vs `ProteomeXchange`).

---

## Limitations

The eval and the experimental setup have several documented biases. The most
important ones:

1. **Strict F1 encodes our repository canon, not equivalence.** "PRIDE" and
   "ProteomeXchange" are different labels for the same consortium; a system
   using one label is penalized when ground truth uses the other. We report
   loose F1 as the headline.
2. **Ground truth completeness is incomplete.** Several "false positives"
   produced by both systems are real datasets cited in the paper but absent
   from the benchmark CSV (e.g., DG RTR's `JPST002506` is the same dataset as
   the gt's `PXD049309`). A manual gold-truth audit on the disagreement set
   would likely raise both systems' precision.
3. **Prompt engineering effort is asymmetric.** DocETL v1 uses a hand-tuned
   120-line prompt with a repository catalog. DataGatherer is run with its
   stock few-shot template. If we gave DG the same effort, it would likely
   close the recall gap.
4. **Input surface is not held constant.** DocETL receives plain text we
   stripped from PMC JATS XML using lxml. DataGatherer reads the same XML
   through its own internal fetch + parser stack. This is a **pipeline
   comparison**, not a controlled extractor comparison.
5. **DG's long-document FDR fallback has an upstream typo bug.** None of our
   21 EXP papers triggered it (each is <130k tokens), so our numbers are
   valid; but extending to DataRef-REV (longer papers) requires fixing this
   first.

The full discussion is in `outputs/summary.md` and `outputs/failure_cases.md`.

---

## References

- Marini et al., "Data Gatherer: LLM-powered Dataset Reference Extraction from
  Scientific Literature." *SDP 2025*. <https://github.com/VIDA-NYU/data-gatherer>
- Shankar et al., "DocETL: Agentic Query Rewriting and Evaluation for Complex
  Document Processing." *VLDB 2025*. <https://ucbepic.github.io/docetl/>
- DataRef-EXP / DataRef-REV benchmark: <https://doi.org/10.5281/zenodo.15549086>
