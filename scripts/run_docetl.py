"""Run the DocETL pipeline on all EXP papers and normalize the output.

DocETL writes a single JSON file containing all records. We convert that to
jsonl matching the shape used by run_datagatherer.py:

    {"pmcid": "PMC6141466", "predictions": [...], "latency_s": ..., "error": null}

Latency and cost come from the DocETL intermediate dir + a litellm callback.

Usage:
    python scripts/run_docetl.py \
        --yaml docetl_pipeline/extract.yaml \
        --out outputs/docetl_v0_EXP.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict:
    env = os.environ.copy()
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    env = load_env()

    # Figure out where DocETL will write its output file (from the YAML's
    # `pipeline.output.path` key) so we can read it back afterwards.
    import yaml

    cfg = yaml.safe_load(args.yaml.read_text())
    raw_out_path = Path(cfg["pipeline"]["output"]["path"])
    intermediate_dir = Path(cfg["pipeline"]["output"].get("intermediate_dir", ""))

    print(f"Running DocETL pipeline: {args.yaml}")
    print(f"DocETL raw output -> {raw_out_path}")

    t0 = time.time()
    result = subprocess.run(
        ["docetl", "run", str(args.yaml)],
        env=env,
        capture_output=True,
        text=True,
    )
    wall = time.time() - t0
    print(result.stdout.splitlines()[-1] if result.stdout else "(no stdout)")
    if result.returncode != 0:
        print("docetl run failed:")
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        return 1

    raw = json.loads(raw_out_path.read_text())
    print(f"DocETL produced {len(raw)} records in {wall:.1f}s")

    # Normalize to jsonl: one record per PMCID with a predictions list.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_preds = 0
    with args.out.open("w") as f:
        for rec in raw:
            pmcid = rec.get("id") or rec.get("pmcid") or ""
            refs = rec.get("references") or []
            preds = []
            for r in refs:
                ident = r.get("dataset_identifier") or ""
                repo = r.get("repository") or ""
                url = r.get("url") or ""
                if ident:
                    preds.append(
                        {
                            "dataset_identifier": ident,
                            "repository": repo,
                            "url": url,
                            "source_section": r.get("source_section", ""),
                            "evidence": r.get("evidence", ""),
                        }
                    )
            n_preds += len(preds)
            f.write(
                json.dumps(
                    {
                        "pmcid": pmcid,
                        "url": rec.get("url", ""),
                        "predictions": preds,
                        "latency_s": None,
                        "error": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    # Try to extract cost from intermediate dir if present.
    cost_info = {}
    if intermediate_dir and intermediate_dir.exists():
        # DocETL dumps per-op intermediate json with cost info embedded.
        pass  # best-effort, we still report wall-clock + char count

    meta = {
        "pipeline_yaml": str(args.yaml),
        "n_papers": len(raw),
        "total_predictions": n_preds,
        "wall_time_s": round(wall, 1),
    }
    meta_path = args.out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))
    print("\n=== docetl run summary ===")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
