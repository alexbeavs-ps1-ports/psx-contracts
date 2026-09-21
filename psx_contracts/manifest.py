#!/usr/bin/env python3
"""Validate and migrate PSX title `project-manifest.toml` files.

The canonical schema is specified in `schemas/manifest-v2.md`. Three producer
shapes are in the wild (A, B, B2) plus one schema divergence (M). This tool reads
any of them, reports what does not conform, and converts them to schema v2.

Usage:
  python -m psx_contracts.manifest validate <workspace>...
  python -m psx_contracts.manifest migrate  <workspace>... [--write]
  python -m psx_contracts.manifest inspect  <workspace>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
MANIFEST_NAME = "project-manifest.toml"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]+$")

SHAPES = {
    "A": ("project", "release", "framework", "bios", "validation"),
    "B": ("project", "retail_identity", "framework", "release", "release_binding",
          "limits", "paths"),
    "B2": ("project", "retail_identity", "framework", "limits", "paths"),
    "M": ("project", "retail_identity", "framework", "reference", "limits", "paths"),
}

# The canonical section-set. `schema_version` and `bios`/`validation`/`release`
# are optional, so this is matched as a required subset rather than an equality.
V2_REQUIRED = ("platform", "title", "retail_identity", "framework")

IDENTITY_STATES = ("verified", "unrecorded", "inherited")
VALIDATION_STATES = ("not_run", "pass", "fail")
PIN_STATES = ("accepted", "candidate", "diverged")
PUBLICATION_STATES = ("preparatory", "authorized", "published", "withdrawn")

# Shape A recorded `release_candidate_prepared`; shape B's ladder did not have
# it. Adding it as a value is the least-lossy reconciliation. See spec section 4.
GRADUATION_STATES = (
    "bootstrap_verified", "release_candidate_prepared", "release_published",
)

TRACKS = ("recompilation", "enhanced-recompilation", "research", "decompilation")
AUDIENCES = ("rights-holder", "player", "modder", "research")


class ManifestError(ValueError):
    """The manifest is absent, unreadable, or not valid TOML."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_shape(document: dict[str, Any]) -> str:
    """Return the declared section-set name, or 'unknown'."""
    present = {
        key for key, value in document.items()
        if isinstance(value, (dict, list))
    }
    if document.get("schema_version") == SCHEMA_VERSION:
        return f"v{SCHEMA_VERSION}"
    for name, sections in SHAPES.items():
        if present == set(sections):
            return name
    return "unknown"


def load(workspace: Path) -> tuple[dict[str, Any], str]:
    path = workspace / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"{workspace}: no {MANIFEST_NAME}")
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        raise ManifestError(f"{workspace}: {error}") from error
    return document, detect_shape(document)


def _require(document: dict[str, Any], section: str, key: str, problems: list[str]) -> Any:
    table = document.get(section)
    if not isinstance(table, dict) or key not in table:
        problems.append(f"missing {section}.{key}")
        return None
    return table[key]


def _check_hash(value: Any, label: str, problems: list[str]) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str) or not HEX64.match(value):
        problems.append(f"{label}: expected 64 lowercase hex characters")


def _check_address(value: Any, label: str, problems: list[str]) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str) or not ADDRESS.match(value):
        problems.append(f"{label}: expected 0x-prefixed hex")


def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name)
    return value if isinstance(value, dict) else {}


def validate(document: dict[str, Any], shape: str, workspace: Path) -> list[str]:
    """Return a list of human-readable problems. Empty means conforms."""
    problems: list[str] = []

    if document.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version: expected {SCHEMA_VERSION}, found "
            f"{document.get('schema_version', 'absent')} (shape {shape})"
        )

    platform = _table(document, "platform")
    if not platform.get("id"):
        problems.append("missing platform.id")

    slug = _require(document, "title", "slug", problems)
    if isinstance(slug, str) and slug and slug != workspace.name:
        problems.append(f"title.slug '{slug}' does not match directory '{workspace.name}'")

    _require(document, "title", "name", problems)
    _require(document, "title", "region", problems)

    track = _require(document, "title", "track", problems)
    if isinstance(track, str) and track not in TRACKS:
        problems.append(f"title.track '{track}' not in {TRACKS}")

    audience = _require(document, "title", "intended_audience", problems)
    if isinstance(audience, str) and audience not in AUDIENCES:
        problems.append(f"title.intended_audience '{audience}' not in {AUDIENCES}")

    # Retail identity. identity_state is required so that an empty hash is a
    # declaration rather than an omission.
    identity = _table(document, "retail_identity")
    _require(document, "retail_identity", "serials", problems)
    _check_address(identity.get("load_address"),
                   "retail_identity.load_address", problems)
    _check_address(identity.get("entry_point"),
                   "retail_identity.entry_point", problems)

    state = _require(document, "retail_identity", "identity_state", problems)
    if isinstance(state, str) and state not in IDENTITY_STATES:
        problems.append(f"retail_identity.identity_state '{state}' not in {IDENTITY_STATES}")

    digest = identity.get("executable_sha256", "")
    _check_hash(digest, "retail_identity.executable_sha256", problems)
    if state == "verified" and not digest:
        problems.append(
            "retail_identity.identity_state is 'verified' but executable_sha256 is empty"
        )
    if state == "unrecorded" and digest:
        problems.append(
            "retail_identity.identity_state is 'unrecorded' but executable_sha256 is populated"
        )

    # Framework pin. commit is the authority; source_commit is derived from it.
    framework = _table(document, "framework")
    commit = _require(document, "framework", "commit", problems)
    if isinstance(commit, str) and commit and not HEX40.match(commit):
        problems.append("framework.commit: expected 40 lowercase hex characters")
    tree = framework.get("tree")
    if isinstance(tree, str) and tree and not HEX40.match(tree):
        problems.append("framework.tree: expected 40 lowercase hex characters")
    pin = framework.get("pin_status")
    if isinstance(pin, str) and pin not in PIN_STATES:
        problems.append(f"framework.pin_status '{pin}' not in {PIN_STATES}")

    binding = _table(document, "release_binding")
    if binding:
        source = binding.get("source_commit", "")
        if isinstance(source, str) and source and source != commit:
            # A divergence is legitimate when the build receipt names the commit
            # that actually produced the release. Validate against that rather
            # than assuming the derived rule.
            build_commit = _buildinfo_source_commit(workspace)
            if build_commit and source == build_commit:
                pass
            else:
                problems.append(
                    "release_binding.source_commit differs from framework.commit "
                    f"({source[:8]} vs {str(commit)[:8]}) and no build receipt "
                    "confirms it"
                )
        publication = binding.get("publication")
        if isinstance(publication, str):
            head = publication.split(";")[0].strip()
            if head and head not in PUBLICATION_STATES:
                problems.append(
                    f"release_binding.publication '{head}' not in {PUBLICATION_STATES}"
                )

    release = _table(document, "release")
    if release:
        graduation = release.get("graduation_state")
        if isinstance(graduation, str) and graduation not in GRADUATION_STATES:
            problems.append(
                f"release.graduation_state '{graduation}' not in {GRADUATION_STATES}"
            )
        if "version" in release:
            problems.append(
                "release.version is deprecated; use release_binding.title_version"
            )

    validation = _table(document, "validation")
    if validation:
        checks = ("windows_package", "linux_gameplay", "macos_gameplay")
        for key in checks:
            value = validation.get(key)
            if isinstance(value, str) and value not in VALIDATION_STATES:
                problems.append(f"validation.{key} '{value}' not in {VALIDATION_STATES}")
        ran = any(
            isinstance(validation.get(k), str) and validation[k] != "not_run"
            for k in checks
        )
        if ran and not validation.get("validated_at"):
            problems.append(
                "validation.validated_at is required when any check is not 'not_run'"
            )

    if "reference" in document:
        problems.append(
            "[reference] is deprecated; use [[references]]. This is the shape M "
            "schema divergence."
        )

    return problems




# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

# Emission order of the canonical manifest.
CANONICAL_ORDER = (
    "schema_version", "platform", "title", "retail_identity", "framework",
    "bios", "validation", "release_binding", "release", "limits", "paths",
    "references",
)


def _quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        inner = ", ".join(_quote(item) for item in value)
        return f"[{inner}]"
    text = "" if value is None else str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit(table: dict[str, Any], header: str, lines: list[str]) -> None:
    """Append one table: arrays first, then scalars, in declared order."""
    if not table:
        return
    lines.append(f"[{header}]")
    arrays = {k: v for k, v in table.items() if isinstance(v, list)}
    scalars = {k: v for k, v in table.items() if not isinstance(v, list)}
    for key, value in {**arrays, **scalars}.items():
        lines.append(f"{key} = {_quote(value)}")
    lines.append("")


def _emit_references(rows: list[dict[str, Any]], lines: list[str]) -> None:
    for row in rows:
        lines.append("[[references]]")
        for key, value in row.items():
            lines.append(f"{key} = {_quote(value)}")
        lines.append("")


def render(canonical: dict[str, Any], references: list[dict[str, Any]]) -> str:
    """Render a canonical document to TOML text, in canonical order."""
    lines: list[str] = ["# Canonical title manifest. Schema v2.", ""]
    for name in CANONICAL_ORDER:
        if name == "schema_version":
            lines.append(f"schema_version = {canonical['schema_version']}")
            lines.append("")
        elif name == "references":
            _emit_references(references, lines)
        elif name in canonical:
            _emit(canonical[name], name, lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def _game_toml(workspace: Path | None) -> dict[str, Any]:
    """Read `game.toml`, the recompiler input that carries disc identity.

    The census found this is the only file holding disc hashes for most titles:
    `known_md5`, `known_sha1`, `known_crc32` and `known_sizes`. The manifest has
    fields for none of them, so the migration copies what it can.
    """
    if workspace is None:
        return {}
    path = workspace / "game.toml"
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _buildinfo(workspace: Path | None) -> dict[str, Any]:
    """Read the build receipt written at package time, if present."""
    if workspace is None:
        return {}
    path = workspace / "BUILDINFO.json"
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return document if isinstance(document, dict) else {}


def _buildinfo_source_commit(workspace: Path | None) -> str:
    """Read the release binding recorded by the build itself.

    `BUILDINFO.json` is written at package time and names both the framework
    commit built into the release (`source_commit`) and the runtime pin
    (`runtime_commit`). It is authoritative over any manifest field, and it
    agrees with the wave receipt in all 26 wave-3 titles.
    """
    if workspace is None:
        return ""
    path = workspace / "BUILDINFO.json"
    if not path.is_file():
        return ""
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return ""
    value = document.get("source_commit")
    return value if isinstance(value, str) else ""


def _normalise_track(value: Any) -> str:
    """Collapse 'enhanced recompilation' to the enum form."""
    text = str(value or "").strip().lower().replace(" ", "-")
    return text.replace("--", "-")


def _normalise_pin(value: Any) -> str:
    """Reduce a prose pin status to its enum value.

    Shape M records `pin_status = "candidate diverges from the accepted
    portfolio runtime"`, which is a sentence. The leading word is the state.
    """
    text = str(value or "").strip().lower()
    if not text:
        return "accepted"
    head = text.split()[0]
    return head if head in PIN_STATES else "accepted"


def _normalise_region(value: Any) -> str:
    """Collapse 'USA NTSC-U' and 'Europe PAL' to the bare region."""
    text = str(value or "")
    for marker in ("PAL", "NTSC-U", "NTSC-J", "NTSC"):
        if marker in text:
            return marker
    return text


def migrate(
    document: dict[str, Any], shape: str, workspace: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Convert any known shape to schema v2.

    Returns the canonical document, its reference rows, and notes describing
    every interpretive or lossy decision so nothing changes silently.
    """
    notes: list[str] = []
    project = _table(document, "project")
    identity = _table(document, "retail_identity")
    framework = _table(document, "framework")
    release = _table(document, "release")
    binding = _table(document, "release_binding")

    region = project.get("region", "")
    normalised = _normalise_region(region)
    if normalised != region:
        notes.append(f"region '{region}' normalised to '{normalised}'")

    track_raw = project.get("track")
    track = _normalise_track(track_raw or "research")
    if track_raw is not None and track != track_raw:
        notes.append(f"track '{track_raw}' normalised to '{track}'")

    title: dict[str, Any] = {
        "name": project.get("name") or project.get("title") or "",
        "slug": project.get("slug") or "",
        "region": normalised,
        "revision": project.get("revision") or project.get("retail_id", ""),
        "track": track,
        "intended_audience": project.get("intended_audience", "research"),
        "commercial_use_possible": bool(project.get("commercial_use_possible", False)),
        "representative_level": project.get("representative_level", ""),
    }

    if workspace is not None:
        declared = title["slug"]
        if declared and declared != workspace.name:
            title["slug"] = workspace.name
            notes.append(
                f"slug '{declared}' corrected to match the directory "
                f"'{workspace.name}'"
            )
        elif not declared:
            title["slug"] = workspace.name
            notes.append(f"slug set from the directory name '{workspace.name}'")

    serials = identity.get("serials") or []
    if not serials and project.get("retail_id"):
        serials = [project["retail_id"]]
        notes.append("project.retail_id moved to retail_identity.serials[0]")

    # Enrich from game.toml and the build receipt. The manifest alone carries no
    # disc hash for 53 of 56 titles, so without this the migrated manifest would
    # declare every title unidentified.
    game_toml = _game_toml(workspace)
    game = _table(game_toml, "game")
    prepare = _table(game_toml, "prepare_disc")
    build = _buildinfo(workspace)

    digest = identity.get("executable_sha256") or ""
    if not digest and build.get("executable_sha256"):
        digest = str(build["executable_sha256"])
        notes.append(
            "executable_sha256 taken from BUILDINFO.json (absent from the manifest)"
        )

    disc_count = identity.get("disc_count") or 0
    known_sizes = prepare.get("known_sizes") or []
    if not disc_count and isinstance(known_sizes, list) and known_sizes:
        disc_count = len(known_sizes)
        notes.append(f"disc_count {disc_count} inferred from game.toml known_sizes")

    executable_paths = identity.get("executable_paths") or []
    if not executable_paths:
        boot = _first(prepare.get("boot_exe")) or game.get("exe")
        boot = str(boot or "")
        if boot:
            executable_paths = [boot.rsplit("/", 1)[-1]]
            notes.append("executable_paths taken from game.toml boot executable")

    load_address = identity.get("load_address") or game.get("load_address") or ""
    entry_point = identity.get("entry_point") or game.get("entry_pc") or ""

    new_identity: dict[str, Any] = {
        "disc_count": disc_count,
        "serials": serials,
        "executable_paths": executable_paths,
        "executable_sha256": digest,
        "identity_state": "verified" if digest else "unrecorded",
    }
    if not digest:
        notes.append(
            "executable_sha256 empty; recorded identity_state = 'unrecorded' "
            "(previously implicit)"
        )
    for key, value in (
        ("data_track_sha256", identity.get("data_track_sha256")),
        ("load_address", load_address),
        ("entry_point", entry_point),
    ):
        if value:
            new_identity[key] = value

    # Disc hashes have no manifest home. `game.toml` stays the authority and the
    # migrated manifest does not copy them, so there is no second source to
    # drift. Recorded here so the decision is visible rather than silent.
    if prepare.get("known_md5") or game.get("known_md5"):
        notes.append(
            "disc hashes live in game.toml only; not duplicated into the manifest"
        )


    pin_raw = framework.get("pin_status")
    pin = _normalise_pin(pin_raw)
    new_framework: dict[str, Any] = {
        "name": framework.get("name", ""),
        "repository": framework.get("repository", ""),
        "commit": framework.get("commit", ""),
        "tree": framework.get("tree", ""),
        "license": framework.get("license", ""),
        "pin_status": pin,
    }
    if pin_raw is not None and pin != pin_raw:
        notes.append(f"pin_status '{pin_raw}' reduced to '{pin}'")
    for key in ("recomp_ui_commit", "renderer_sha256"):
        if framework.get(key):
            new_framework[key] = framework[key]

    accepted = framework.get("accepted_private_commit") or framework.get(
        "accepted_portfolio_commit")
    build_commit = _buildinfo_source_commit(workspace)

    # Resolution order for the release binding. BUILDINFO.json is written by the
    # build itself and is authoritative; a manifest copy of the accepted commit
    # is a fallback because it is shared across 22 wave-3 titles and so cannot
    # distinguish per-title builds.
    if build_commit:
        source_commit = build_commit
        if accepted and accepted != build_commit:
            notes.append(
                f"BUILDINFO.json source_commit {build_commit[:8]} wins over "
                f"accepted commit {str(accepted)[:8]}"
            )
    elif binding.get("source_commit"):
        source_commit = binding["source_commit"]
    else:
        # No build receipt. Shape A and M carry an `accepted_*` commit, but it
        # cannot be trusted here: in shape A it is one value shared by 22 titles,
        # and in shape M it contradicts framework_pins.txt. Without independent
        # evidence the declared pin is the only supportable claim.
        source_commit = framework.get("commit", "")
        if accepted and accepted != source_commit:
            notes.append(
                f"accepted commit {str(accepted)[:8]} contradicts framework.commit "
                f"{str(source_commit)[:8]} with no build receipt to arbitrate; "
                "framework.commit retained"
            )

    if framework.get("accepted_private_commit") or framework.get(
            "accepted_portfolio_commit"):
        notes.append(
            "accepted_* key does not survive as a separate key; its meaning is "
            "carried by release_binding.source_commit and framework.commit"
        )
    if framework.get("accepted_portfolio_tree"):
        notes.append(
            "framework.accepted_portfolio_tree has no canonical home and is dropped"
        )



    publication = binding.get("publication")
    if not publication:
        status = str(release.get("status", ""))
        publication = "preparatory" if status == "candidate" else (status or "preparatory")
        if status == "candidate":
            notes.append(
                "release.status 'candidate' -> publication 'preparatory'; "
                "CONFIRM, wave-3 candidates did publish"
            )
    new_binding: dict[str, Any] = {
        "source_commit": source_commit,
        "title_version": (binding.get("current_title_version")
                          or release.get("version") or ""),
        "public_topology": binding.get("current_public_topology", ""),
        "public_release": binding.get("current_public_release", ""),
        "package_platform": binding.get("current_package_platform", ""),
        "manual_test": binding.get("manual_test", ""),
        "linux_qualification": binding.get("linux_qualification", ""),
        "macos_qualification": binding.get("macos_qualification", ""),
        "publication": publication,
        "retcomm_submission": binding.get("retcomm_submission", ""),
    }
    if release.get("target_date"):
        new_binding["target_date"] = release["target_date"]
        notes.append(
            "release.target_date moved to release_binding.target_date "
            "(not in the spec's mapping table)"
        )

    new_release: dict[str, Any] = {}
    if release.get("graduation_state"):
        new_release["graduation_state"] = release["graduation_state"]
    elif project.get("implementation_state"):
        new_release["graduation_state"] = project["implementation_state"]
        notes.append(
            "project.implementation_state -> release.graduation_state "
            "(value added to the ladder)"
        )
    if release.get("platform"):
        new_release["platform_scope"] = release["platform"]
    for key in ("supported_platforms", "public_package_status"):
        if release.get(key):
            new_release[key] = release[key]

    references: list[dict[str, Any]] = []
    for row in document.get("references") or []:
        if isinstance(row, dict):
            references.append(dict(row))
    for row in document.get("reference") or []:
        if isinstance(row, dict):
            references.append(dict(row))
            notes.append("[reference] converted to [[references]]")

    canonical: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "platform": {"id": "ps1", "variant": "retail"},
        "title": title,
        "retail_identity": new_identity,
        "framework": new_framework,
    }
    if _table(document, "bios"):
        canonical["bios"] = dict(_table(document, "bios"))
    if _table(document, "validation"):
        canonical["validation"] = dict(_table(document, "validation"))
    if any(str(v) for v in new_binding.values()):
        canonical["release_binding"] = new_binding
    if new_release:
        canonical["release"] = new_release
    for key in ("limits", "paths"):
        if _table(document, key):
            canonical[key] = dict(_table(document, key))

    return canonical, references, notes


def _iter_workspaces(targets: list[str]) -> list[Path]:
    """Expand each target to the workspace directory that holds a manifest."""
    found: list[Path] = []
    for raw in targets:
        path = Path(raw)
        if path.is_dir() and (path / MANIFEST_NAME).is_file():
            found.append(path)
        elif path.is_dir():
            children = sorted(
                child for child in path.iterdir()
                if child.is_dir() and (child / MANIFEST_NAME).is_file()
            )
            found.extend(children)
        else:
            raise ManifestError(f"{raw}: not a directory")
    return found



def _cmd_inspect(args: argparse.Namespace) -> int:
    for workspace in _iter_workspaces(args.targets):
        document, shape = load(workspace)
        digest = _sha256(workspace / MANIFEST_NAME)
        print(f"{workspace.name}: shape {shape}, sha256 {digest[:16]}")
        print(f"  sections: {', '.join(sorted(k for k, v in document.items() if isinstance(v, dict)))}")
        print(f"  top-level keys: {', '.join(sorted(k for k in document if not isinstance(document[k], dict)))}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    workspaces = _iter_workspaces(args.targets)
    failed = 0
    for workspace in workspaces:
        try:
            document, shape = load(workspace)
        except ManifestError as error:
            print(f"FAIL {error}")
            failed += 1
            continue
        problems = validate(document, shape, workspace)
        if problems:
            failed += 1
            print(f"FAIL {workspace.name} (shape {shape})")
            for problem in problems:
                print(f"     - {problem}")
        elif args.verbose:
            print(f"ok   {workspace.name} (shape {shape})")
    print(f"\n{len(workspaces) - failed} of {len(workspaces)} conform to schema v{SCHEMA_VERSION}")
    return 1 if failed else 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    workspaces = _iter_workspaces(args.targets)
    for workspace in workspaces:
        document, shape = load(workspace)
        canonical, references, notes = migrate(document, shape, workspace)
        text = render(canonical, references)
        parsed = tomllib.loads(text)
        problems = validate(parsed, detect_shape(parsed), workspace)
        if problems:
            print(f"FAIL {workspace.name}: migrated output does not validate")
            for problem in problems:
                print(f"     - {problem}")
            return 1
        print(f"ok   {workspace.name}: shape {shape} -> v{SCHEMA_VERSION}")
        for note in notes:
            print(f"     note: {note}")
        if args.write:
            target = workspace / MANIFEST_NAME
            backup = workspace / (MANIFEST_NAME + ".v1")
            if not backup.exists():
                backup.write_bytes(target.read_bytes())
            target.write_text(text, encoding="utf-8")
            print(f"     wrote {target.name} (previous saved as {backup.name})")
    if not args.write:
        print("\ndry run; pass --write to apply")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Report a manifest's shape and hash")
    inspect.add_argument("targets", nargs="+")
    inspect.set_defaults(func=_cmd_inspect)

    validate_cmd = sub.add_parser("validate", help="Check conformance to schema v2")
    validate_cmd.add_argument("targets", nargs="+")
    validate_cmd.add_argument("-v", "--verbose", action="store_true",
                              help="Also print conforming workspaces")
    validate_cmd.set_defaults(func=_cmd_validate)

    migrate_cmd = sub.add_parser("migrate", help="Convert a manifest to schema v2")
    migrate_cmd.add_argument("targets", nargs="+")
    migrate_cmd.add_argument("--write", action="store_true",
                             help="Apply the change, keeping a .v1 backup")
    migrate_cmd.set_defaults(func=_cmd_migrate)

    args = parser.parse_args()
    try:
        return args.func(args)
    except ManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

