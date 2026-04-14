# Failure Case Analysis — DataRef-EXP

## Counts

| Category | Count |
|---|---|
| both_hit | 39 |
| docetl_only | 3 |
| dg_only | 0 |
| both_missed | 5 |

**False positives**: DG-RTR 1, DG-FDR 6, DocETL 9

## DocETL ✓ / DataGatherer ✗  (3 total, showing up to 10)

| PMCID | identifier | gt_repo | DG-RTR | DG-FDR | DocETL |
|---|---|---|---|---|---|
| PMC11129317 | `10.17632/bvdn865y9c.1` | Mendeley | ✗ | ✗ | ✓ |
| PMC11129317 | `10.17632/3wfxrz66w2.1` | Mendeley | ✗ | ✗ | ✓ |
| PMC4915822 | `ega-archive.org` | EGA | ✗ | ✗ | ✓ |

## DataGatherer ✓ / DocETL ✗  (0 total, showing up to 10)

| PMCID | identifier | gt_repo | DG-RTR | DG-FDR | DocETL |
|---|---|---|---|---|---|

## Both missed  (5 total, showing up to 10)

| PMCID | identifier | gt_repo | DG-RTR | DG-FDR | DocETL |
|---|---|---|---|---|---|
| PMC11320025 | `astrazenecagroup-dt.pharmacm.com/dt/home` | AstraZeneca | ✗ | ✗ | ✗ |
| PMC11320025 | `6077-6129` | CPTAC | ✗ | ✗ | ✗ |
| PMC11208500 | `idop_040` | OPEN | ✗ | ✗ | ✗ |
| PMC8628860 | `ega-archive.org` | EGA | ✗ | ✗ | ✗ |
| PMC11061608 | `pmc.ncbi.nlm.nih.gov/articles/instance/7339254/bin/nihms1569324-supplement-ts2.xlsx` |  | ✗ | ✗ | ✗ |

## DocETL predictions NOT in ground truth (possible hallucinations/noise)

| PMCID | identifier | pred_repo |
|---|---|---|
| PMC11015306 | `pxd042991` | PRIDE |
| PMC11066909 | `gse10327` | GEO |
| PMC11066909 | `gse122077` | GEO |
| PMC11066909 | `gse70678` | GEO |
| PMC11066909 | `gse73038` | GEO |
| PMC11066909 | `pdc.cancer.gov/pdc/browse/(pdc000180)` | PDC |
| PMC11208500 | `10.5281/zenodo.10854544` | Zenodo |
| PMC8628860 | `gse131907` | GEO |
| PMC8628860 | `phs001713` | dbGaP |
