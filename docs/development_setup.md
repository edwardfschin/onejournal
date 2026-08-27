# OneJournal Development Setup

## Purpose

This document defines the reproducible local Python setup for the current
OneJournal prototype.

The package contract lives in `pyproject.toml`. `requirements.lock` records the
exact runtime environment validated by the project. The lock is intentionally a
plain pip requirements file so the early project does not depend on an
additional package-management tool.

## Supported Python

OneJournal declares Python 3.11 through 3.13 support.

The exact locked environment has been validated locally on Python 3.13.9. The
continuous-integration workflow is configured to exercise the declared Python
3.11, 3.12, and 3.13 source contract once the repository is connected to
GitHub.

## Clean local installation

From the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
python -c "import duckdb, streamlit, yaml; import onejournal; print(onejournal.__version__)"
```

Why the editable install uses `--no-deps --no-build-isolation`:

- `requirements.lock` has already installed the exact application and build
  dependencies.
- pip cannot silently resolve a different dependency set.
- the local OneJournal source remains editable.

For ordinary dependency resolution without the exact lock, use:

```bash
python -m pip install -e .
```

That command follows the compatible direct-dependency ranges in
`pyproject.toml`, but it is not the exact reproducible path.

## Private runtime prerequisites

The full baseline also expects the user's private local OneJournal environment
and operational data paths:

- `~/.onejournal/env/`
- `data/journal/onejournal.duckdb`
- generated dashboard validation inputs under `output/`

Private environment files, tokens, raw broker evidence, runtime databases, and
generated output must not be committed.

### Broker credential boundary

The current OneJournal runtime has no active broker credential, token, OAuth
refresh, or provider-call operator. During the bounded PNL-02 evidence step,
OneBot/VPS is only a temporary single-owner Schwab capture bridge. OneJournal
may currently consume only separately approved private evidence bundles through
credential-free validators, adapters, reconciliation, and import operators.

Do not configure `ONEJOURNAL_SCHWAB_*` variables or a OneJournal Schwab token
path in the current runtime. The target architecture places approved Schwab,
IBKR, Moomoo, and later provider connections in an isolated OneJournal
integration service. Its credential storage, authentication, tenancy,
deployment, and cutover contracts require separate approval before
implementation; the current evidence bridge does not define those contracts.

The installation and import smoke check can run without broker access. The full
baseline uses the local runtime prerequisites but does not place, cancel,
replace, or modify orders.

## Validation

With the private local prerequisites present, run:

```bash
./bin/onejournal_check.sh
```

The checker uses the currently active virtual environment. If no virtual
environment is active, it retains the established Mac default at
`/Users/edward/python-envs/onejournal-env`. For explicit automation, set
`ONEJOURNAL_VENV_DIR` or `ONEJOURNAL_PYTHON`.

Expected final line:

```text
PASS OneJournal baseline looks good.
```

Also confirm that validation did not introduce unexpected tracked changes:

```bash
git status --short
```

## Dependency ownership

Direct runtime dependencies:

- `duckdb` - DuckDB journal reads, writes, contracts, and validation
- `pyyaml` - safe YAML configuration support
- `streamlit` - current internal prototype UI

The standard library covers the remaining current journal and adapter code.
`requests` remains pinned in `requirements.lock` only because Streamlit depends
on it transitively; it is not a direct OneJournal dependency or provider-call
capability. A future provider connector may add an approved HTTP client or
provider SDK as its own reviewed dependency.

The automated test suite uses Python's standard-library `unittest` runner, so it
adds no development-only dependency. Add formatting, analysis, or alternative
test tools only when their workflow provides a demonstrated benefit and is
validated.

Run the focused automated suite with:

```bash
PYTHONPATH=.:src python3 -m unittest discover -s tests -p "test_*.py" -v
```

Run the provider-neutral clean-checkout validation with:

```bash
./bin/onejournal_ci.sh
```

This command does not require private broker evidence, runtime databases,
credentials, or generated output. See `docs/continuous_integration.md` for the
exact CI boundary and guard behavior.

## Updating dependencies

Do not edit only the lock or only `pyproject.toml`.

For a dependency change:

1. Explain why the direct dependency or version range must change.
2. Update `pyproject.toml`.
3. Build a fresh temporary environment.
4. Install and validate the compatible dependency set.
5. Regenerate `requirements.lock` from that clean validated environment.
6. Review the complete lock diff for unexpected packages or versions.
7. Run `python -m pip check`, import smoke checks, and the full baseline.
8. Confirm Git contains no runtime, broker, token, or generated artifacts.

Do not upgrade dependencies only because a newer version exists. Upgrade for a
clear compatibility, security, correctness, or maintainability reason, and
validate the affected contracts.
