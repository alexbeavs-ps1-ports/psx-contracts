# `project-manifest.toml` — schema v2

The canonical schema for a PSX static-recompilation title workspace.

**Status:** stable. `schema_version = 2`.

A manifest is the portable, git-versioned description of one title. It is a Git file
first: a checkout is self-describing, a change is reviewable as a pull request, and the
history is versioned for free. The database projections described elsewhere are derived
from manifests, not a replacement for them.

## Why v2 exists

Three incompatible producer shapes reached production with no version field, so a
consumer could not tell which it was reading:

| Shape | Sections | Producers observed |
|---|---|---|
| A | `project, release, framework, bios, validation` | wave-3 publication receipt |
| B | `project, retail_identity, framework, release, release_binding, limits, paths` | `baseline_workflow.py` |
| B2 | `project, retail_identity, framework, limits, paths` | not identified |
| M | `project, retail_identity, framework, reference, limits, paths` | not identified |

v2 is the union, reconciled. `schema_version` exists so this cannot recur silently.

## Document shape

```toml
schema_version = 2

[platform]
id = "ps1"
variant = "retail"

[title]
name = "Apocalypse"
slug = "apocalypse"
region = "Europe"
revision = "SLES-00460"
track = "recompilation"
intended_audience = "research"
commercial_use_possible = false
representative_level = "what was actually demonstrated"

[retail_identity]
disc_count = 2
serials = ["SLES-00460"]
executable_paths = ["SLES_004.60"]
executable_sha256 = "a7b5add7...c4c2"
identity_state = "verified"
load_address = "0x80010000"
entry_point = "0x80086808"

[framework]
name = "PSXRecomp"
repository = "https://github.com/RetroPortingToolKit/psxrecomp"
commit = "5952a72950fa27fe94eb665678614514a13a1d25"
tree = "a328ebc526245a60c1c953d1599c3b1ff2990e22"
license = "PolyForm Noncommercial 1.0.0"
pin_status = "accepted"

[bios]
required = true
profile = "SCPH5552"
size = 524288
sha256 = "1faaa18f...352c09"

[validation]
windows_package = "not_run"
linux_gameplay = "not_run"
macos_gameplay = "not_run"

[release_binding]
source_commit = "36621ddf8eebdc55bb3dd61704ca85d7c06d5339"
title_version = "0.1.0"
public_topology = "owned-input-kit-only"
public_release = "none"
package_platform = "none-promoted"
publication = "published"
retcomm_submission = "not-authorized"

[release]
graduation_state = "release_candidate_prepared"
platform_scope = "multi-platform"
supported_platforms = ["windows-x64", "linux-x64", "macos-arm64", "macos-x64"]
public_package_status = "not-published"

[limits]
maximum_local_generated_gib = 20
maximum_single_trace_gib = 8

[paths]
local_context = ".local-context"
generated = "generated"
captures = "out/captures"
traces = "out/traces"
packages = "dist"

[[references]]
name = "hueponik/wip3out-patches"
repository = "https://codeberg.org/hueponik/wip3out-patches"
commit = "ac46a5dc500a9581ea55b8efb5c1a0d4be944aba"
license = "No license file found"
purpose = "why this reference is relevant"
```

## Required

`[platform].id`, `[title].name`, `[title].slug`, `[title].region`,
`[title].track`, `[title].intended_audience`, `[retail_identity].serials`,
`[retail_identity].identity_state`, `[framework].commit`.

All other sections are optional. Omit a section rather than populating it with a
placeholder — a present section is a claim.


## Rules

**`title.slug` must equal the workspace directory name.** This is enforced. It makes the
manifest locatable without reading it, and it prevents the case divergence found in the
fleet (`wipeout-3-special-edition-recomp` in a directory named
`Wipeout-3-Special-Edition-Recomp`).

**`identity_state` is required whenever the section is present.** 53 of 56 workspaces in
the source estate carried an empty `executable_sha256`, and nothing distinguished "not
yet measured" from "deliberately withheld". A manifest declaring
`identity_state = "verified"` with an empty hash is rejected.

**Disc hashes live in `game.toml`, not here.** `known_md5`, `known_sha1` and
`known_crc32` are recompiler inputs and are deliberately not duplicated into the
manifest, so there is no second copy to drift. Tooling reads them from `game.toml`
where they are needed.

**`release_binding.source_commit` is derived, with one exception.** It must equal
`framework.commit`. It may differ only when a build receipt (`BUILDINFO.json`) names the
divergent value, which is the normal case for a release built at an older pin than the
workspace now carries. The validator checks the receipt before reporting a conflict.

**Addresses are `0x`-prefixed hex strings.** `load_address` and `entry_point`.

**Timestamps are ISO 8601.** `validation.validated_at` is required once any validation
value is not `not_run`.

## Platform extensions

Console-specific detail goes in optional extensions, so adding a console adds a section
rather than a new shape:

```toml
[platform.ps1]
bios_required = true

[platform.xbox360]
title_id = ""
xex_sha256 = ""
```

## Deprecated

| Key | Replacement |
|---|---|
| `[release].version` | `[release_binding].title_version` |
| `[reference]` (singular) | `[[references]]` |
| `[release_binding].current_*` names | bare names (`title_version`, `public_release`, …) |
| `framework.accepted_private_commit` | consumed into `release_binding.source_commit` |

## Migration

```bash
python -m psx_contracts.manifest migrate <workspace>... --write
```

Dry run by default. `--write` preserves the previous file as
`project-manifest.toml.v1`.

## Compatibility policy

- Adding a required key, or narrowing an accepted value, is a **major** change to the
  reusable workflow tag.
- Rejecting input that was previously accepted is a **minor** bump.
- Adding an optional key or extending an enumeration is a **minor** bump.

## What this schema deliberately does not do

- **It does not merge `game.toml`.** That file is a recompiler input and holds fields
  with no manifest home (`players`, `text_size`, `stack_base`, `known_sizes`). The
  relationship between the two is a separate decision.
- **It does not reject unknown keys.** The estate carries fields no shape declares
  (`renderer_sha256`, `accepted_portfolio_tree`); a hard reject would fail valid work.
  The validator reports what it does not recognise.
- **It does not model release publications.** Where a release was published, and under
  what authority, is `BUILDINFO.json` and the wave receipts.

## Enumerations

| Field | Values |
|---|---|
| `platform.id` | `ps1`, `ps2`, `xbox360`, `n64`, … |
| `platform.variant` | `retail`, `demo`, `prototype`, `unknown` |
| `title.track` | `recompilation`, `enhanced-recompilation`, `research`, `decompilation` |
| `title.intended_audience` | `rights-holder`, `player`, `modder`, `research` |
| `retail_identity.identity_state` | `verified`, `unrecorded`, `inherited` |
| `framework.pin_status` | `accepted`, `candidate`, `diverged` |
| `validation.*` | `not_run`, `pass`, `fail` |
| `release_binding.publication` | `preparatory`, `authorized`, `published`, `withdrawn` |
| `release.graduation_state` | `bootstrap_verified`, `release_candidate_prepared`, `release_published` |
