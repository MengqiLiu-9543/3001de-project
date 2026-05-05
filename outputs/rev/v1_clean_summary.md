# DocETL v1 REV — Clean Prompt Auto-Report

**Generated**: 2026-05-05 00:25:36
**Benchmark**: DataRef-REV (1,242 papers, 1,883 ground-truth records)

## Headline (loose-match)

| | Old v1 (with Rule 2/3) | **New v1 (clean)** | Δ |
|---|---|---|---|
| Predictions | 2802 | 2612 | -190 |
| Precision | 66.35% | **71.13%** | +4.78 pt |
| Recall | 98.73% | **98.67%** | -0.06 pt |
| **F1** | **79.36%** | **82.67%** | **+3.31 pt** |
| Cost (USD) | ~$18.00 (partly cached) | **$17.67** (fresh) | — |

## Strict-match (for completeness)

| | New v1 (clean) |
|---|---|
| Precision | 64.62% |
| Recall    | 89.64% |
| F1        | 75.11% |
| TP / FP / FN | 1688 / 924 / 195 |

## Run telemetry

| Field | Value |
|---|---|
| Wall time (s) | 699.5 |
| LLM calls | 1240 |
| Prompt tokens | 28,370,510 |
| Completion tokens | 260,088 |
| Pipeline yaml | `docetl_pipeline/extract_rev_v1.yaml` |

## Comparison summary

- F1 changed by **+3.31 pt**, recall by **-0.06 pt**, precision by **+4.78 pt**.
- Old REV outputs preserved at `outputs/rev/v1_with_rule3/`.
- New outputs: `outputs/rev/docetl_v1_REV.{jsonl, meta.json}`
