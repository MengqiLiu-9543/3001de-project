# Vendored DataGatherer

This directory is a **trimmed, in-repo copy** of [VIDA-NYU/data-gatherer](https://github.com/VIDA-NYU/data-gatherer)
with our Kimi (Moonshot) compatibility patch already applied.

- **Upstream**: <https://github.com/VIDA-NYU/data-gatherer>
- **Pinned commit**: `d6a0c374bd6fc30f72405f041daa68aa5cf5be2b` (`v0.1.8`)
- **License**: MIT — see upstream `LICENSE` and `pyproject.toml`
- **Authors**: Pietro Marini et al., VIDA-NYU
- **Cited as**: Marini, P. et al., "Data Gatherer: LLM-powered Dataset Reference
  Extraction from Scientific Literature." *SDP 2025*.

## Why vendored?

Pinning the upstream version into our repo makes the project reproducible:
- Teammates can `pip install -e ./data-gatherer/` immediately after cloning,
  with no separate `git clone` step.
- The Kimi compatibility patch is already applied, so there's no `git apply`
  step that could fail if upstream moves.
- Frozen at the exact commit our benchmark was run against, so future upstream
  changes don't silently break our reproduction.

## What's removed compared to upstream

To keep the vendored directory small (1.8 MB instead of 134 MB), we removed:
- `.git/` — git history
- `data_gatherer.egg-info/` — build artifacts
- `docs/`, `examples/`, `scripts/`, `ui/`, `tests/`, `Dockerfile` — not
  required to run the library
- CI/workflow configs — not relevant outside upstream

The actual Python package (`data_gatherer/`) and `pyproject.toml` are
unchanged from upstream **except for the patches in
`../patches/datagatherer-kimi-support.patch`**.

## Our patches

See `../patches/datagatherer-kimi-support.patch` for the full diff. Summary:
1. `env.py` — read `MOONSHOT_API_KEY` / `MOONSHOT_BASE_URL` env vars
2. `data_gatherer.py` — add Kimi model names to the `entire_document_models`
   allowlist (otherwise `full_document_read=True` is silently degraded to
   `False` for non-GPT/non-Gemini models)
3. `parser/base_parser.py` — same allowlist patch and a Kimi branch in the
   token-counting path
4. `llm/llm_client.py` — add a `_call_moonshot()` branch that uses chat
   completions (Kimi does not support OpenAI's Responses API), normalize
   `role: developer` messages to `role: system`, drop the JSON-object
   response_format constraint that conflicts with DG's array-format prompt
   templates
