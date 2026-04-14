# Project Proposal: Data Discovery in Scientific Publications

**Course:** Data Engineering — Spring 2026

**Project:** Project 8 — Data Discovery in Scientific Publications

**Team:** rwadata

**Team Members:**
- Mengqi Liu (ml9543)
- Jintong Li (jl13640)
- Bo Yu (by2566)

---

## 1. Problem Statement

Researchers, librarians, and data curators spend significant time manually identifying dataset references embedded in scientific publications. These references are scattered across data availability statements, figure captions, inline text, and supplementary materials, making manual extraction labor-intensive and error-prone. Automating this process is essential for improving dataset discoverability and supporting reproducible research.

This project aims to build an automated dataset reference extraction pipeline using **DocETL**, a general-purpose declarative LLM-powered data processing framework, and rigorously compare it against **DataGatherer**, a purpose-built tool designed specifically for this task.

## 2. Approach

Our approach consists of four phases:

### Phase 1: Understanding the Baseline (DataGatherer)

We will first study and run DataGatherer on the provided benchmarks to establish a baseline. DataGatherer supports two extraction strategies:

- **Full-Document Read (FDR):** Feeds the entire preprocessed HTML of a paper to an LLM for extraction.
- **Retrieve-Then-Read (RTR):** Uses rule-based CSS/XPath selectors to locate relevant sections (e.g., Data Availability Statements), then extracts references from those sections only.

We will run both strategies on the **DataRef-EXP** and **DataRef-REV** benchmarks and record accuracy, coverage, and cost metrics.

### Phase 2: Building the DocETL Pipeline

We will design and implement a DocETL pipeline that replicates the extraction task. The pipeline will consist of the following operators:

1. **Document Ingestion:** Parse scientific papers (PDF/HTML) into text.
2. **Split / Gather:** Chunk long documents into manageable segments while preserving context across chunks (e.g., a dataset mention in the text may refer to a URL in the references section).
3. **Map (Extraction):** Apply LLM prompts to each chunk to extract structured dataset references in the format `{dataset_identifier, repository, url}`.
4. **Resolve (Deduplication):** Merge duplicate or overlapping references across chunks and across documents.
5. **Filter:** Remove low-confidence or invalid extractions.

We will iteratively refine the pipeline prompts and operator configurations to maximize extraction quality.

### Phase 3: Evaluation and Comparison

We will evaluate both systems on the same benchmarks using the following dimensions:

| Dimension | Metrics |
|-----------|---------|
| **Accuracy** | Precision, Recall, F1-score |
| **Coverage** | Number of unique datasets discovered per paper |
| **Cost** | Total LLM tokens consumed, estimated API cost ($) |
| **Engineering Effort** | Lines of code, configuration complexity, development time |
| **Robustness** | Performance across different paper formats (HTML vs. PDF) and disciplines |

We will also perform a detailed **failure case analysis** to identify where each method succeeds and fails.

### Phase 4: Critical Analysis and Report

We will write a comprehensive report discussing:

- The tradeoffs between general-purpose declarative pipelines (DocETL) and specialized tools (DataGatherer).
- Strengths and limitations of each approach.
- Recommendations for practitioners choosing between the two paradigms.
- Potential improvements and future directions.

## 3. Data Sources

- **DataRef-EXP Benchmark:** A curated set of scientific papers with ground-truth dataset references, provided by the DataGatherer authors (available on Zenodo: https://doi.org/10.5281/zenodo.15549086).
- **DataRef-REV Benchmark:** A second benchmark dataset from the same source, covering a different set of publications.
- Both benchmarks contain scientific papers from multiple disciplines with annotated dataset identifiers, repositories, and URLs.

## 4. Tools and Technologies

| Tool | Role |
|------|------|
| **DataGatherer** | Baseline extraction system (github.com/VIDA-NYU/data-gatherer) |
| **DocETL** | Declarative pipeline framework (ucbepic.github.io/docetl/) |
| **LLM API** | GPT-4o or Gemini for both systems |
| **Python** | Implementation language |
| **Pandas** | Data manipulation and evaluation |

## 5. Milestones

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| **Mar 9 – Mar 22** | Environment setup and data acquisition | DataGatherer and DocETL installed; benchmark datasets downloaded and explored |
| **Mar 23 – Apr 1** | Run DataGatherer baseline | Baseline results (FDR and RTR) on both benchmarks with metrics recorded |
| **Apr 2 – Apr 10** | Design and implement DocETL pipeline v1 | Working DocETL pipeline that can process papers and output structured references |
| **Apr 11 – Apr 17** | Iterate and optimize DocETL pipeline | Refined prompts and operator configurations; improved extraction quality |
| **Apr 18 – Apr 23** | Full evaluation and comparison | Complete evaluation results across all dimensions; failure case analysis |
| **Apr 24 – Apr 30** | Report writing and presentation preparation | Final report, code repository with reproducibility instructions, presentation slides |

## 6. Expected Outcomes

1. A **working DocETL pipeline** for dataset reference extraction from scientific publications.
2. A **quantitative comparison** between DocETL and DataGatherer on standard benchmarks.
3. A **detailed report** with insights on the tradeoffs between general-purpose and specialized extraction tools.
4. A **reproducible code repository** containing all pipeline code, evaluation scripts, and instructions.

## 7. References

1. Shankar, S., et al. "DocETL: Agentic Query Rewriting and Evaluation for Complex Document Processing." *Proceedings of the VLDB Endowment* 18.9 (2025): 3035-3048.
2. Marini, P., et al. "Data Gatherer: LLM-powered Dataset Reference Extraction from Scientific Literature." *Proceedings of the Fifth Workshop on Scholarly Document Processing (SDP 2025)*. 2025.
