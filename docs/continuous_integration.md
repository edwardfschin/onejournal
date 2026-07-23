# OneJournal Continuous Integration

## Purpose

OneJournal CI validates a clean repository checkout without private broker
evidence, credentials, runtime databases, generated output, or access to broker
APIs.

The provider-neutral entry point is:

```bash
./bin/onejournal_ci.sh
```

The command runs:

- locked-environment dependency consistency and import checks
- Python compilation for current application, journal, CI, and test code
- tracked-file guards for secrets and private/runtime artifacts
- the automated unit, integration, contract, and regression suite
- normalized-fill, manual-fill, trade-episode, and dashboard-payload contract
  checks against committed synthetic fixtures

The command is intentionally different from `bin/onejournal_check.sh`. The full
local baseline validates the private operational environment and current
journal database. Those artifacts must never be copied into CI merely to make a
clean-checkout check pass.

## GitHub automation

`.github/workflows/ci.yml` is configured to run the provider-neutral command on
pushes and pull requests using Python 3.11, 3.12, and 3.13.

The workflow has read-only repository permission, receives no project secrets,
and sets a 15-minute job timeout. Concurrent checks for a superseded branch
revision are cancelled.

No Git remote is currently configured in this local repository. The workflow
will become active if the repository is connected to GitHub. The underlying
`bin/onejournal_ci.sh` command remains usable by another CI provider without
changing the validation contract.

## Guard behavior

`scripts/ci/check_repository.py` inspects the Git tracked-file set rather than
the local working directory or staging area. It fails when tracked content
includes:

- raw broker or manual-import evidence
- generated normalized fills or dashboard/report output
- DuckDB runtime databases or backups
- environment or token files
- operating-system metadata
- high-confidence private-key or service-token signatures

This focused guard is a prevention layer, not a guarantee that every possible
secret format can be recognized. Sensitive values must still remain in the
private environment and token locations defined by the project contracts.

## Local validation

Activate an environment installed from `requirements.lock`, install the local
package, and run:

```bash
./bin/onejournal_ci.sh
```

Expected final line:

```text
PASS OneJournal clean CI checks passed.
```
