# PSX contracts

Canonical schemas, validators, and reusable CI gates for PSX
static-recompilation title repositories.

This repository exists so a rule is defined **once** and enforced **everywhere**.
The alternative — copying a check into each title repository — is what produced the
divergence documented in
[`KIT_WORKFLOW_DIVERGENCE_2026-09-21.md`](../../PSX-References/blob/master/corpus/reports/KIT_WORKFLOW_DIVERGENCE_2026-09-21.md):
105 release workflows, all different, with one correctness gate present in 24 and absent
in 81.

## What lives here

| Path | Purpose |
|---|---|
| `psx_contracts/manifest.py` | Validates and migrates `project-manifest.toml` |
| `schemas/manifest-v2.md` | The canonical schema specification |
| `.github/workflows/validate-manifest.yml` | Reusable gate for title repositories |
| `tests/` | Regression fixtures |

## The manifest gate

Title repositories call the gate like this:

```yaml
name: Manifest

on:
  pull_request:
  push:
    branches: [main]

jobs:
  manifest:
    uses: alexbeavs-ps1-ports/psx-contracts/.github/workflows/validate-manifest.yml@v1
```

One definition, one version tag, no per-repository copies.

### Advisory and enforcing modes

The gate ships in **advisory mode** by default: it reports problems in the job summary
and always succeeds. This lets a fleet adopt the gate without blocking releases on
pre-existing divergence.

To enforce, pass `strict`:

```yaml
jobs:
  manifest:
    uses: alexbeavs-ps1-ports/psx-contracts/.github/workflows/validate-manifest.yml@v1
    with:
      strict: true
```

Under `strict` the job fails when any manifest does not conform.

## Running the validator directly

```bash
python -m psx_contracts.manifest validate <workspace>...
python -m psx_contracts.manifest migrate  <workspace>... [--write]
python -m psx_contracts.manifest inspect  <workspace>...
```

No dependencies beyond the Python 3.11+ standard library.

## Versioning

The reusable workflow is called by tag. Use `@v1` for the current stable policy.
A breaking change to what the gate accepts requires a new major tag; additions that
only reject previously-accepted input are a minor bump.

## Scope

This repository is console-neutral by design. The manifest schema carries a
`platform.id` field, so a second console adds a schema extension rather than a new
contract repository.

The schema and validator were developed in `PSX-References` and are published here so
that public title repositories can reach them. `PSX-References` is private, and a
private repository cannot host a reusable workflow for public callers.
