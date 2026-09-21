from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from psx_contracts import manifest


# ---------------------------------------------------------------------------
# Fixtures. `shape_m` is the regression fixture required by the reconciliation
# spec section 6: shape M's defects must stay rejected so the class of defect
# cannot be merged again.
# ---------------------------------------------------------------------------

SHAPE_A = """
[project]
name = "Apocalypse"
slug = "apocalypse"
retail_id = "SLES-00460"
region = "Europe"
implementation_state = "release_candidate_prepared"

[release]
version = "0.1.0"
status = "candidate"
target_date = "2026-09-07"

[framework]
repository = "https://github.com/Alexbeav/psxrecomp"
commit = "5952a72950fa27fe94eb665678614514a13a1d25"
tree = "a328ebc526245a60c1c953d1599c3b1ff2990e22"
recomp_ui_commit = "be8ac1d03ee19d55394b5a5f2d9d1506edd56659"
accepted_private_commit = "63446a28111a21a0cb7e8b5106c3614c898fc4b5"

[bios]
required = true
profile = "SCPH5552"
size = 524288
sha256 = "1faaa18fa820a0225e488d9f086296b8e6c46df739666093987ff7d8fd352c09"

[validation]
windows_package = "not_run"
linux_gameplay = "not_run"
macos_gameplay = "not_run"
"""

SHAPE_B = """
[project]
title = "Azure Dreams"
region = "USA"
revision = "serial-bound source"
track = "recompilation"
intended_audience = "player"
commercial_use_possible = false
representative_level = "package startup only"

[retail_identity]
disc_count = 1
serials = ["SLUS-00614"]
executable_paths = ["disc/SLUS_006.14"]
executable_sha256 = ""
load_address = "0x8002D000"
entry_point = "0x80033930"

[framework]
name = "PSXRecomp"
repository = "https://github.com/Alexbeav/psxrecomp.git"
commit = "5420458ad90a81ca73d8128ebe719d8e1d3e9e2b"
tree = "adb5d721e3553159beb2a773c82365216d372bb5"
recomp_ui_commit = "ff92028ec86e30503694c70c532b93b8198663aa"
license = "See the pinned dependency license"

[release_binding]
source_commit = "5420458ad90a81ca73d8128ebe719d8e1d3e9e2b"
current_title_version = "0.1.0"
current_public_topology = "owned-input-kit-only"
current_public_release = "none"
current_package_platform = "none-promoted"
manual_test = "private-build-only"
linux_qualification = "pending"
macos_qualification = "waived"
publication = "preparatory"
retcomm_submission = "not-authorized"

[limits]
maximum_local_generated_gib = 20
maximum_single_trace_gib = 8

[paths]
local_context = ".local-context"
generated = "generated"

[release]
version = "0.1.0"
platform = "multi-platform"
supported_platforms = ["windows-x64", "linux-x64"]
graduation_state = "bootstrap_verified"
public_package_status = "not-published"
"""

# Shape M, verbatim from the Waveout workspace. Its four defects are what the
# validator must catch: prose pin_status, spaced track, a [[reference]] array
# with no `purpose`, and a slug whose case does not match the directory.
SHAPE_M = """
[project]
title = "WipEout 3 Special Edition"
slug = "wipeout-3-special-edition-recomp"
region = "Europe PAL"
revision = "SCES-02845"
track = "enhanced recompilation"
intended_audience = "research"
commercial_use_possible = false
representative_level = "Frontend, one race"

[retail_identity]
disc_count = 1
serials = ["SCES-02845"]
executable_paths = ["SCES_028.45"]
executable_sha256 = "0213f5292fa1d995ebe61f42d5dbdb6614e481cb3840ac5f1521c2dfdccc0a4d"
data_track_sha256 = "003bdc41068252e791ea7dd99ba1b94814dc48b967e57a7cdc4bf6e1cf4cb1e9"
load_address = "0x80010000"
entry_point = "0x80162474"

[framework]
name = "PSXRecomp candidate submodule"
repository = "https://github.com/mstan/psxrecomp"
commit = "ecf57bd971827444ff74538daedfde708844f5f3"
tree = "c90f4129aeb4be980aea7e32d167dd2eff2704d4"
license = "PolyForm Noncommercial 1.0.0"
accepted_portfolio_commit = "f23c5ba1a220fe1ca8818cc48c026d6c2f7f2c64"
pin_status = "candidate diverges from the accepted portfolio runtime"

[[reference]]
name = "hueponik/wip3out-patches"
repository = "https://codeberg.org/hueponik/wip3out-patches"
commit = "ac46a5dc500a9581ea55b8efb5c1a0d4be944aba"
license = "No license file found"

[limits]
maximum_local_generated_gib = 20

[paths]
generated = "generated"
"""


def _workspace(tmp_path: Path, name: str, text: str) -> Path:
    workspace = tmp_path / name
    workspace.mkdir()
    (workspace / manifest.MANIFEST_NAME).write_text(text, encoding="utf-8")
    return workspace


# ---------------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,text,expected", [
    ("apocalypse", SHAPE_A, "A"),
    ("azure-dreams", SHAPE_B, "B"),
    ("wipeout-3", SHAPE_M, "M"),
])
def test_detect_shape(tmp_path, name, text, expected) -> None:
    document, shape = manifest.load(_workspace(tmp_path, name, text))
    assert shape == expected


def test_detect_shape_returns_v2_for_migrated_output(tmp_path) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    document, shape = manifest.load(workspace)
    canonical, references, _ = manifest.migrate(document, shape, workspace)
    parsed = tomllib.loads(manifest.render(canonical, references))
    assert manifest.detect_shape(parsed) == "v2"


def test_detect_shape_is_unknown_for_an_unrecognised_set(tmp_path) -> None:
    workspace = _workspace(tmp_path, "odd", "[project]\ntitle = \"X\"\n")
    _, shape = manifest.load(workspace)
    assert shape == "unknown"


def test_load_rejects_a_missing_manifest(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(manifest.ManifestError, match="no project-manifest"):
        manifest.load(empty)


def test_load_rejects_invalid_toml(tmp_path) -> None:
    workspace = _workspace(tmp_path, "broken", "[project\ntitle = ")
    with pytest.raises(manifest.ManifestError):
        manifest.load(workspace)


# ---------------------------------------------------------------------------
# Validation. A v1 manifest must fail, and each v2 defect must be reported.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,text", [
    ("apocalypse", SHAPE_A), ("azure-dreams", SHAPE_B), ("wipeout", SHAPE_M),
])
def test_unversioned_manifests_do_not_conform(tmp_path, name, text) -> None:
    workspace = _workspace(tmp_path, name, text)
    document, shape = manifest.load(workspace)
    problems = manifest.validate(document, shape, workspace)
    assert any("schema_version" in problem for problem in problems)


def test_malformed_manifest_is_a_regression_fixture(tmp_path) -> None:
    """The shape M defects must stay rejected (spec section 6)."""
    workspace = _workspace(tmp_path, "Wipeout-3-Special-Edition-Recomp", SHAPE_M)
    document, shape = manifest.load(workspace)
    problems = "\n".join(manifest.validate(document, shape, workspace))
    assert "pin_status" in problems
    assert "title.slug" in problems
    assert "[reference] is deprecated" in problems


def test_regression_fixture_survives_migration_into_v2(tmp_path) -> None:
    """Migrating must not silently accept the malformed values."""
    workspace = _workspace(tmp_path, "Wipeout-3-Special-Edition-Recomp", SHAPE_M)
    document, shape = manifest.load(workspace)
    canonical, references, notes = manifest.migrate(document, shape, workspace)
    parsed = tomllib.loads(manifest.render(canonical, references))
    assert parsed["title"]["track"] == "enhanced-recompilation"
    assert parsed["title"]["slug"] == "Wipeout-3-Special-Edition-Recomp"
    assert parsed["framework"]["pin_status"] == "candidate"
    assert "purpose" not in parsed["references"][0]
    joined = "\n".join(notes)
    assert "pin_status" in joined
    assert "slug" in joined
    assert "[reference] converted" in joined


def test_every_shape_migrates_to_conforming_v2(tmp_path) -> None:
    cases = [
        ("apocalypse", SHAPE_A), ("azure-dreams", SHAPE_B),
        ("crash-bash", SHAPE_B), ("Wipeout-3-Special-Edition-Recomp", SHAPE_M),
    ]
    for name, text in cases:
        workspace = _workspace(tmp_path, name, text)
        document, shape = manifest.load(workspace)
        canonical, references, _ = manifest.migrate(document, shape, workspace)
        parsed = tomllib.loads(manifest.render(canonical, references))
        assert manifest.detect_shape(parsed) == "v2"
        assert manifest.validate(parsed, "v2", workspace) == [], name


def test_source_commit_must_match_framework_commit_without_a_receipt(tmp_path) -> None:
    text = SHAPE_B.replace(
        'source_commit = "5420458ad90a81ca73d8128ebe719d8e1d3e9e2b"',
        'source_commit = "0000000000000000000000000000000000000000"',
    )
    workspace = _workspace(tmp_path, "azure-dreams", SHAPE_A + text)
    document = tomllib.loads(text)
    document["schema_version"] = 2
    problems = "\n".join(manifest.validate(document, "v2", workspace))
    assert "no build receipt confirms it" in problems


def test_build_receipt_justifies_a_divergent_source_commit(tmp_path) -> None:
    """A real build receipt is the one thing that legitimises a divergence."""
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    (workspace / "BUILDINFO.json").write_text(json.dumps({
        "source_commit": "36621ddf8eebdc55bb3dd61704ca85d7c06d5339",
    }), encoding="utf-8")
    document, shape = manifest.load(workspace)
    canonical, references, notes = manifest.migrate(document, shape, workspace)
    parsed = tomllib.loads(manifest.render(canonical, references))
    binding = parsed["release_binding"]
    assert binding["source_commit"] == "36621ddf8eebdc55bb3dd61704ca85d7c06d5339"
    assert binding["source_commit"] != parsed["framework"]["commit"]
    assert manifest.validate(parsed, "v2", workspace) == []
    assert any("BUILDINFO.json" in note for note in notes)


def test_identity_state_must_agree_with_the_hash(tmp_path) -> None:
    workspace = _workspace(tmp_path, "shape-b", SHAPE_B)
    document = tomllib.loads(SHAPE_B)
    document["schema_version"] = 2
    document["platform"] = {"id": "ps1"}
    document["title"] = {
        "name": "X", "slug": "shape-b", "region": "USA", "track": "recompilation",
        "intended_audience": "player",
    }
    document["retail_identity"]["identity_state"] = "verified"
    problems = "\n".join(manifest.validate(document, "v2", workspace))
    assert "'verified' but executable_sha256 is empty" in problems


def test_release_version_is_reported_as_deprecated(tmp_path) -> None:
    workspace = _workspace(tmp_path, "shape-b", SHAPE_B)
    document = tomllib.loads(SHAPE_B)
    document["schema_version"] = 2
    problems = manifest.validate(document, "B", workspace)
    assert any("release.version is deprecated" in p for p in problems)


# ---------------------------------------------------------------------------
# Normalisation. These are the value-level reconciliations in the mapping table.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Europe", "Europe"),
    ("Europe PAL", "PAL"),
    ("USA NTSC-U", "NTSC-U"),
    ("Japan NTSC-J", "NTSC-J"),
])
def test_normalise_region(raw, expected) -> None:
    assert manifest._normalise_region(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("recompilation", "recompilation"),
    ("enhanced recompilation", "enhanced-recompilation"),
    ("Enhanced Recompilation", "enhanced-recompilation"),
])
def test_normalise_track(raw, expected) -> None:
    assert manifest._normalise_track(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("candidate diverges from the accepted portfolio runtime", "candidate"),
    ("accepted", "accepted"),
    ("diverged and superseded", "diverged"),
    ("", "accepted"),
    ("something unexpected", "accepted"),
])
def test_normalise_pin(raw, expected) -> None:
    assert manifest._normalise_pin(raw) == expected


def test_migration_carries_retail_id_into_serials(tmp_path) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    document, shape = manifest.load(workspace)
    canonical, _, _ = manifest.migrate(document, shape, workspace)
    assert canonical["retail_identity"]["serials"] == ["SLES-00460"]


def test_migration_maps_implementation_state_to_graduation(tmp_path) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    document, shape = manifest.load(workspace)
    canonical, _, notes = manifest.migrate(document, shape, workspace)
    assert canonical["release"]["graduation_state"] == "release_candidate_prepared"
    assert any("implementation_state" in note for note in notes)


def test_migration_flags_the_candidate_publication_ambiguity(tmp_path) -> None:
    """`candidate` mapped to `preparatory` is interpretive and must be flagged."""
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    document, shape = manifest.load(workspace)
    canonical, _, notes = manifest.migrate(document, shape, workspace)
    assert canonical["release_binding"]["publication"] == "preparatory"
    assert any("CONFIRM" in note for note in notes)


def test_migration_is_deterministic(tmp_path) -> None:
    workspace = _workspace(tmp_path, "azure-dreams", SHAPE_B)
    first = manifest.render(*manifest.migrate(*manifest.load(workspace), workspace)[:2])
    second = manifest.render(*manifest.migrate(*manifest.load(workspace), workspace)[:2])
    assert first == second


# ---------------------------------------------------------------------------
# Enrichment from game.toml and BUILDINFO.json. Without this the migrated
# manifest declares every title unidentified, because the manifest alone carries
# no disc hash for 53 of 56 titles.
# ---------------------------------------------------------------------------

GAME_TOML = """
[game]
id = "SLES-00460"
exe = "L:/cache/SLES_004.60"
load_address = "0x80010000"
entry_pc = "0x80086808"

[prepare_disc]
boot_exe = "SLES_004.60"
known_sizes = [459223296, 491857296]
known_md5 = ["ba0fce10982da9313fa4cd8e211da637", "1f82bf57095b14d0ea4d636895967bf2"]
known_sha1 = ["f0ee4a74b4d79d95cc52aa4651552ae1244edc84"]
known_crc32 = ["745fa692", "7ec6604b"]
"""

BUILDINFO = {
    "schema": 1,
    "source_commit": "36621ddf8eebdc55bb3dd61704ca85d7c06d5339",
    "executable_sha256": "a7b5add7f9577b1dab5ed3cea84825e72b47ff0f28affe9cd6b6cbb7a398c4c2",
}


def _enriched(tmp_path, name="apocalypse", text=SHAPE_A) -> Path:
    workspace = _workspace(tmp_path, name, text)
    (workspace / "game.toml").write_text(GAME_TOML, encoding="utf-8")
    (workspace / "BUILDINFO.json").write_text(json.dumps(BUILDINFO), encoding="utf-8")
    return workspace


def test_executable_hash_comes_from_the_build_receipt(tmp_path) -> None:
    """Shape A has no hash field at all; the receipt supplies it."""
    workspace = _enriched(tmp_path)
    document, shape = manifest.load(workspace)
    canonical, _, notes = manifest.migrate(document, shape, workspace)
    identity = canonical["retail_identity"]
    assert identity["executable_sha256"] == BUILDINFO["executable_sha256"]
    assert identity["identity_state"] == "verified"
    assert any("BUILDINFO.json" in note and "executable_sha256" in note
               for note in notes)


def test_identity_is_enriched_from_game_toml(tmp_path) -> None:
    workspace = _enriched(tmp_path)
    document, shape = manifest.load(workspace)
    canonical, _, _ = manifest.migrate(document, shape, workspace)
    identity = canonical["retail_identity"]
    assert identity["executable_paths"] == ["SLES_004.60"]
    assert identity["disc_count"] == 2
    assert identity["load_address"] == "0x80010000"
    assert identity["entry_point"] == "0x80086808"


def test_declared_identity_wins_over_enrichment(tmp_path) -> None:
    """A manifest value is an assertion and must not be overwritten."""
    text = SHAPE_B.replace('executable_paths = ["disc/SLUS_006.14"]',
                           'executable_paths = ["DECLARED.EXE"]')
    text = text.replace('disc_count = 1', 'disc_count = 9')
    workspace = _enriched(tmp_path, "azure-dreams", text)
    document, shape = manifest.load(workspace)
    canonical, _, _ = manifest.migrate(document, shape, workspace)
    identity = canonical["retail_identity"]
    assert identity["executable_paths"] == ["DECLARED.EXE"]
    assert identity["disc_count"] == 9


def test_disc_hashes_are_not_duplicated_into_the_manifest(tmp_path) -> None:
    """game.toml stays the single authority for disc hashes."""
    workspace = _enriched(tmp_path)
    document, shape = manifest.load(workspace)
    canonical, _, notes = manifest.migrate(document, shape, workspace)
    rendered = manifest.render(canonical, [])
    assert "ba0fce10982da9313fa4cd8e211da637" not in rendered
    assert any("disc hashes live in game.toml only" in note for note in notes)


def test_migration_survives_a_missing_game_toml(tmp_path) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    document, shape = manifest.load(workspace)
    canonical, _, _ = manifest.migrate(document, shape, workspace)
    assert canonical["retail_identity"]["identity_state"] == "unrecorded"


def test_migration_survives_a_corrupt_game_toml(tmp_path) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    (workspace / "game.toml").write_text("[game\nbroken", encoding="utf-8")
    document, shape = manifest.load(workspace)
    canonical, _, _ = manifest.migrate(document, shape, workspace)
    assert canonical["retail_identity"]["executable_sha256"] == ""


def test_migration_survives_a_corrupt_build_receipt(tmp_path) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    (workspace / "BUILDINFO.json").write_text("{not json", encoding="utf-8")
    document, shape = manifest.load(workspace)
    canonical, _, _ = manifest.migrate(document, shape, workspace)
    assert canonical["retail_identity"]["identity_state"] == "unrecorded"


# ---------------------------------------------------------------------------
# Framework repository pin (D1a). The estate carried four values for one repo:
# a local path, a stale `mstan` alias, and a `.git` suffix inconsistency.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://github.com/Alexbeav/psxrecomp", manifest.CANONICAL_FRAMEWORK_REPOSITORY),
    ("https://github.com/Alexbeav/psxrecomp.git", manifest.CANONICAL_FRAMEWORK_REPOSITORY),
    ("https://github.com/mstan/psxrecomp", manifest.CANONICAL_FRAMEWORK_REPOSITORY),
    ("https://github.com/mstan/psxrecomp.git", manifest.CANONICAL_FRAMEWORK_REPOSITORY),
    ("https://github.com/RetroPortingToolKit/psxrecomp.git",
     manifest.CANONICAL_FRAMEWORK_REPOSITORY),
    ("https://github.com/RetroPortingToolKit/psxrecomp",
     manifest.CANONICAL_FRAMEWORK_REPOSITORY),
])
def test_normalise_repository_maps_aliases(raw, expected) -> None:
    assert manifest.normalise_repository(raw) == expected


@pytest.mark.parametrize("raw", [
    "I:/Projects/PSX-References/_local/sources/psxrecomp-fork",
    "C:\\Projects\\psxrecomp",
    "psxrecomp",
    "",
    None,
])
def test_normalise_repository_replaces_non_urls(raw) -> None:
    """A local path resolves only on one machine, so it cannot be a pin."""
    assert manifest.normalise_repository(raw) == manifest.CANONICAL_FRAMEWORK_REPOSITORY


def test_validator_rejects_a_local_path_as_a_pin(tmp_path) -> None:
    text = SHAPE_B.replace(
        'repository = "https://github.com/Alexbeav/psxrecomp.git"',
        'repository = "I:/Projects/PSX-References/_local/sources/psxrecomp-fork"',
    )
    workspace = _workspace(tmp_path, "azure-dreams", text)
    document, shape = manifest.load(workspace)
    problems = "\n".join(manifest.validate(document, shape, workspace))
    assert "not an https URL" in problems


def test_validator_rejects_the_mstan_alias(tmp_path) -> None:
    text = SHAPE_B.replace(
        'repository = "https://github.com/Alexbeav/psxrecomp.git"',
        'repository = "https://github.com/mstan/psxrecomp"',
    )
    workspace = _workspace(tmp_path, "azure-dreams", text)
    document, shape = manifest.load(workspace)
    problems = "\n".join(manifest.validate(document, shape, workspace))
    assert "is an alias" in problems


def test_migration_replaces_a_local_path_pin(tmp_path) -> None:
    text = SHAPE_A.replace(
        'repository = "https://github.com/Alexbeav/psxrecomp"',
        'repository = "I:/Projects/PSX-References/_local/sources/psxrecomp-fork"',
    )
    workspace = _workspace(tmp_path, "apocalypse", text)
    document, shape = manifest.load(workspace)
    canonical, _, notes = manifest.migrate(document, shape, workspace)
    assert canonical["framework"]["repository"] == manifest.CANONICAL_FRAMEWORK_REPOSITORY
    assert any("framework.repository" in note for note in notes)


def test_migrated_framework_repository_always_validates(tmp_path) -> None:
    """Every historical form must migrate to something the validator accepts."""
    for index, raw in enumerate([
        "https://github.com/Alexbeav/psxrecomp",
        "https://github.com/mstan/psxrecomp",
        "I:/Projects/PSX-References/_local/sources/psxrecomp-fork",
    ]):
        text = SHAPE_A.replace('repository = "https://github.com/Alexbeav/psxrecomp"',
                               f'repository = "{raw}"')
        workspace = _workspace(tmp_path, f"apocalypse-{index}", text)
        document, shape = manifest.load(workspace)
        canonical, references, _ = manifest.migrate(document, shape, workspace)
        parsed = tomllib.loads(manifest.render(canonical, references))
        assert manifest.validate(parsed, "v2", workspace) == [], raw


def test_rendered_output_is_valid_toml_for_every_shape(tmp_path) -> None:
    cases = [("apocalypse", SHAPE_A), ("azure-dreams", SHAPE_B),
             ("Wipeout-3-Special-Edition-Recomp", SHAPE_M)]
    for name, text in cases:
        workspace = _workspace(tmp_path, name, text)
        document, shape = manifest.load(workspace)
        canonical, references, _ = manifest.migrate(document, shape, workspace)
        tomllib.loads(manifest.render(canonical, references))


def test_options_are_not_read_as_per_title_assertions(tmp_path) -> None:
    """bios.profile is a batch default and must survive as a value, not a claim."""
    first = _workspace(tmp_path, "apocalypse", SHAPE_A)
    other = _workspace(tmp_path, "colony-wars", SHAPE_A)
    a, a_shape = manifest.load(first)
    b, b_shape = manifest.load(other)
    canonical, _, _ = manifest.migrate(a, a_shape, first)
    other_canonical, _, _ = manifest.migrate(b, b_shape, other)
    assert canonical["bios"]["profile"] == "SCPH5552"
    assert other_canonical["bios"]["profile"] == canonical["bios"]["profile"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_round_trip(tmp_path, monkeypatch) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    monkeypatch.setattr("sys.argv", ["manifest", "validate", str(workspace)])
    assert manifest.main() == 1

    monkeypatch.setattr("sys.argv", ["manifest", "migrate", str(workspace), "--write"])
    assert manifest.main() == 0

    monkeypatch.setattr("sys.argv", ["manifest", "validate", str(workspace)])
    assert manifest.main() == 0
    assert (workspace / (manifest.MANIFEST_NAME + ".v1")).is_file()


def test_cli_migrate_without_write_does_not_mutate(tmp_path, monkeypatch) -> None:
    workspace = _workspace(tmp_path, "apocalypse", SHAPE_A)
    before = (workspace / manifest.MANIFEST_NAME).read_bytes()
    monkeypatch.setattr("sys.argv", ["manifest", "migrate", str(workspace)])
    assert manifest.main() == 0
    assert (workspace / manifest.MANIFEST_NAME).read_bytes() == before
    assert not (workspace / (manifest.MANIFEST_NAME + ".v1")).exists()


def test_iter_workspaces_expands_a_parent_directory(tmp_path) -> None:
    _workspace(tmp_path, "one", SHAPE_A)
    _workspace(tmp_path, "two", SHAPE_B)
    (tmp_path / "no-manifest").mkdir()
    found = manifest._iter_workspaces([str(tmp_path)])
    assert sorted(path.name for path in found) == ["one", "two"]


def test_iter_workspaces_rejects_a_non_directory(tmp_path) -> None:
    with pytest.raises(manifest.ManifestError):
        manifest._iter_workspaces([str(tmp_path / "absent")])

