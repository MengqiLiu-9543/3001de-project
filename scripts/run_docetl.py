"""Run the DocETL pipeline on all EXP papers and normalize the output.

Runs DocETL in-process (not via subprocess) so we can capture LiteLLM
token usage and DocETL's built-in `total_cost` for the cost table.

DocETL writes a single JSON file containing all records. We convert that to
jsonl matching the shape used by run_datagatherer.py:

    {"pmcid": "PMC6141466", "predictions": [...], "latency_s": ..., "error": null}

Usage:
    python scripts/run_docetl.py \
        --yaml docetl_pipeline/extract.yaml \
        --out outputs/docetl_v0_EXP.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---- Kimi pricing (USD per 1M tokens) — same constants as run_datagatherer.py
KIMI_INPUT_PRICE_PER_M = 0.60
KIMI_OUTPUT_PRICE_PER_M = 2.50


def load_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def install_content_filter_workaround():
    """Wrap litellm.completion so Moonshot 'high risk' rejections return an
    empty references response instead of crashing the pipeline.

    Some REV biomedical papers (HIV, paediatric trials, etc.) trigger
    Moonshot's content moderation. We don't want a single rejection to abort
    the whole 1242-paper run — record it as 'no extracted references' and
    continue.
    """
    import litellm
    from litellm.exceptions import BadRequestError
    from litellm.types.utils import ModelResponse, Choices, Message
    from litellm.types.utils import ChatCompletionMessageToolCall, Function
    import json as _json

    _orig_completion = litellm.completion

    def _safe_completion(*args, **kwargs):
        try:
            return _orig_completion(*args, **kwargs)
        except BadRequestError as exc:
            err = str(exc)
            if "high risk" in err or "content_filter" in err or "rejected because" in err:
                # Synthesize an empty tool-call response so DocETL accepts it.
                empty_args = _json.dumps({"references": []})
                fake = ModelResponse(
                    id="content-filter-skipped",
                    choices=[
                        Choices(
                            finish_reason="tool_calls",
                            index=0,
                            message=Message(
                                content="",
                                role="assistant",
                                tool_calls=[
                                    ChatCompletionMessageToolCall(
                                        index=0,
                                        function=Function(arguments=empty_args, name="send_output"),
                                        id="send_output:0",
                                        type="function",
                                    )
                                ],
                            ),
                        )
                    ],
                    model=kwargs.get("model", "kimi-k2-0905-preview"),
                    object="chat.completion",
                    created=0,
                )
                return fake
            raise

    litellm.completion = _safe_completion


def install_litellm_usage_callback() -> dict:
    """Attach a litellm success_callback that accumulates per-call usage.

    Returns the dict that the callback populates so the caller can read it
    after the pipeline finishes.
    """
    counter = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    import litellm  # imported lazily so PYTHONPATH is set up first

    def _on_success(kwargs, response, start_time, end_time):
        try:
            usage = getattr(response, "usage", None)
            if usage is None and isinstance(response, dict):
                usage = response.get("usage")
            if usage is None:
                return
            pt = getattr(usage, "prompt_tokens", None)
            ct = getattr(usage, "completion_tokens", None)
            if pt is None and isinstance(usage, dict):
                pt = usage.get("prompt_tokens")
                ct = usage.get("completion_tokens")
            counter["calls"] += 1
            counter["prompt_tokens"] += int(pt or 0)
            counter["completion_tokens"] += int(ct or 0)
        except Exception:
            pass  # never let telemetry break the pipeline

    # Attach via the official litellm hook list.
    if not hasattr(litellm, "success_callback") or litellm.success_callback is None:
        litellm.success_callback = []
    litellm.success_callback.append(_on_success)
    return counter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    load_env()

    # Install usage callback BEFORE we import docetl so it sees the hook.
    usage = install_litellm_usage_callback()
    # Also wrap litellm.completion to survive Moonshot content-filter rejections.
    install_content_filter_workaround()

    # Run DocETL in-process. DocETL exposes DSLRunner.from_yaml + load_run_save
    # which returns the total cost (USD) it computed via its own LiteLLM
    # accounting.
    from docetl.runner import DSLRunner
    import yaml as _yaml

    cfg = _yaml.safe_load(args.yaml.read_text())
    raw_out_path = Path(cfg["pipeline"]["output"]["path"])

    print(f"Running DocETL pipeline: {args.yaml}")
    print(f"DocETL raw output -> {raw_out_path}")

    runner = DSLRunner.from_yaml(str(args.yaml))
    t0 = time.time()
    docetl_total_cost = runner.load_run_save()
    wall = time.time() - t0

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
                            "data_role": r.get("data_role", ""),
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

    # Compute USD from the LiteLLM callback (more granular than DocETL's
    # built-in total_cost — gives us prompt vs completion split).
    cost_usd_from_tokens = (
        usage["prompt_tokens"] / 1_000_000 * KIMI_INPUT_PRICE_PER_M
        + usage["completion_tokens"] / 1_000_000 * KIMI_OUTPUT_PRICE_PER_M
    )

    meta = {
        "pipeline_yaml": str(args.yaml),
        "model": "kimi-k2-0905-preview",
        "n_papers": len(raw),
        "total_predictions": n_preds,
        "wall_time_s": round(wall, 1),
        "llm_calls": usage["calls"],
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "approx_cost_usd": round(cost_usd_from_tokens, 4),
        "docetl_reported_cost_usd": round(docetl_total_cost, 4),
    }
    meta_path = args.out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))
    print("\n=== docetl run summary ===")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
