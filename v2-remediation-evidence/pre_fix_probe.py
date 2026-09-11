"""Reproduce RR-01..RR-09 gaps against the frozen pre-remediation verifier.

This is a historical red witness. It is intentionally outside the strict
``v2/`` package and is not part of clone-green validation after remediation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import shutil
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

EXPECTED_PRE_FIX = {
    "v2/authority.json": "51c13b209d514437fd91e1f948c67191172542c50144ffb7c697029c91fd6c31",
    "v2/SHA256SUMS": "eb5d1fd4d4b00b863d28eded0a0317b8651446cd4304948ccafc557c2d1e4c",
    "v2/verify.py": "9b3e7db5e520cc120c7a5fe956b3527ff2bee781932278643d00dc919e7aacb1",
    "ttg/curve_recompute.py": "d7f7fe0231edd605668ccc2f431ce5851da351f85478a0d9ab85b2b7d587207c",
}


def load_verifier(repo_root: Path) -> ModuleType:
    """Load the frozen verifier module without treating v2 as a package."""
    path = repo_root / "v2" / "verify.py"
    spec = importlib.util.spec_from_file_location("ttg_v2_pre_fix_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    """Return a file's SHA-256 digest."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require_pre_fix_candidate(repo_root: Path) -> None:
    """Refuse to mislabel a post-fix checkout as the historical red input."""
    mismatches = {
        relative: digest(repo_root / relative)
        for relative, expected in EXPECTED_PRE_FIX.items()
        if digest(repo_root / relative) != expected
    }
    if mismatches:
        raise RuntimeError(
            "pre-fix candidate hashes do not match; this historical probe must "
            f"run only against the frozen red input: {mismatches}"
        )


def copy_clone_fixture(repo_root: Path, destination: Path) -> None:
    """Copy the package and scorer closure needed by clone validation."""
    shutil.copyfile(repo_root / "README.md", destination / "README.md")
    shutil.copyfile(repo_root / "BUNDLE.md", destination / "BUNDLE.md")
    shutil.copytree(repo_root / "v2", destination / "v2")
    (destination / "ttg").mkdir()
    for name in (
        "__init__.py",
        "comparable_path.py",
        "curve_recompute.py",
        "matcher.py",
        "report_io.py",
        "rollup.py",
    ):
        shutil.copyfile(repo_root / "ttg" / name, destination / "ttg" / name)


def restamp_package(package_root: Path) -> None:
    """Refresh the pre-fix manifest after a deliberate fixture mutation."""
    manifest = package_root / "SHA256SUMS"
    members = [line.split("  ", 1)[1] for line in manifest.read_text().splitlines()]
    manifest.write_text(
        "".join(f"{digest(package_root / member)}  {member}\n" for member in members),
        encoding="utf-8",
    )


def rewrite_provenance(path: Path, module: ModuleType, rows: list[dict[str, str]]) -> None:
    """Write a provenance fixture with the verifier's frozen field order."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=module.PROVENANCE_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def require_accepted(
    name: str,
    module: ModuleType,
    repo_root: Path,
    temporary_root: Path,
    mutation: Any,
) -> None:
    """Require the pre-fix clone verifier to accept a known-invalid fixture."""
    fixture = temporary_root / name
    fixture.mkdir()
    copy_clone_fixture(repo_root, fixture)
    mutation(fixture, module)
    restamp_package(fixture / "v2")
    module.load_and_validate(fixture, fixture / "v2")
    print(f"RED accepted: {name}")


def main() -> int:
    """Run all historical pre-fix controls."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    audit_root = args.audit_root.resolve()
    require_pre_fix_candidate(repo_root)
    module = load_verifier(repo_root)
    report_io = importlib.import_module("ttg.report_io")

    with tempfile.TemporaryDirectory(prefix="ttg-v2-remediation-red-") as temporary:
        temporary_root = Path(temporary)

        def delete_preregistration(fixture: Path, verifier: ModuleType) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = [
                row
                for row in verifier.load_provenance(path)
                if row["kind"] != "preregistration"
            ]
            rewrite_provenance(path, verifier, rows)

        require_accepted(
            "rr02-missing-preregistration",
            module,
            repo_root,
            temporary_root,
            delete_preregistration,
        )

        def downgrade_native_producer(fixture: Path, verifier: ModuleType) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = verifier.load_provenance(path)
            for row in rows:
                if row["kind"] == "producer" and row["id"] == "noodl-eval-native-floor":
                    row["state"] = "declared-only"
                    row["sha256"] = "-"
            rewrite_provenance(path, verifier, rows)

        require_accepted(
            "rr02-native-producer-downgrade",
            module,
            repo_root,
            temporary_root,
            downgrade_native_producer,
        )

        def drift_producer_version(fixture: Path, verifier: ModuleType) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = verifier.load_provenance(path)
            for row in rows:
                if row["kind"] == "producer" and row["id"] == "noodl-eval-nbx-shipped":
                    row["version"] = "git:0000000000000000000000000000000000000000"
            rewrite_provenance(path, verifier, rows)

        require_accepted(
            "rr02-producer-version-drift",
            module,
            repo_root,
            temporary_root,
            drift_producer_version,
        )

        def mismatch_tokenizer(fixture: Path, verifier: ModuleType) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = verifier.load_provenance(path)
            for row in rows:
                if row["kind"] == "tokenizer":
                    row["id"] = "different_tokenizer"
                    row["version"] = "different_tokenizer"
            rewrite_provenance(path, verifier, rows)

        require_accepted(
            "rr02-tokenizer-mismatch",
            module,
            repo_root,
            temporary_root,
            mismatch_tokenizer,
        )

        def drift_bundle_status(fixture: Path, _verifier: ModuleType) -> None:
            path = fixture / "v2" / "BUNDLE.md"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "POINT ESTIMATES FILLED; UNCERTAINTY GATE OPEN",
                    "SCORING COMPLETE",
                ),
                encoding="utf-8",
            )

        require_accepted(
            "rr04-bundle-status-drift",
            module,
            repo_root,
            temporary_root,
            drift_bundle_status,
        )

        def add_alternate_results(fixture: Path, _verifier: ModuleType) -> None:
            (fixture / "v2" / "alternate-results.json").write_text(
                "{}\n", encoding="utf-8"
            )

        require_accepted(
            "rr05-extra-package-file",
            module,
            repo_root,
            temporary_root,
            add_alternate_results,
        )

        def boolean_median(fixture: Path, verifier: ModuleType) -> None:
            authority_path = fixture / "v2" / "authority.json"
            authority = verifier.load_json(authority_path)
            authority["results"][0]["metrics"]["ttg_at_80_whole_response"][
                "median_wire_tokens"
            ] = True
            verifier.write_json(authority_path, authority)
            provenance = verifier.load_provenance(fixture / "v2" / "provenance.tsv")
            context = verifier.validate_authority(authority, provenance)
            (fixture / "v2" / "RESULTS.md").write_text(
                verifier.render_results(authority, context), encoding="utf-8"
            )

        require_accepted(
            "rr06-boolean-median",
            module,
            repo_root,
            temporary_root,
            boolean_median,
        )

        def corrupt_fixture_scorer(fixture: Path, _verifier: ModuleType) -> None:
            path = fixture / "ttg" / "matcher.py"
            path.write_text(path.read_text(encoding="utf-8") + "\n# corrupted\n")

        require_accepted(
            "rr09-fixture-scorer-escape",
            module,
            repo_root,
            temporary_root,
            corrupt_fixture_scorer,
        )

        authority = module.load_json(repo_root / "v2" / "authority.json")
        provenance = module.load_provenance(repo_root / "v2" / "provenance.tsv")
        context = module.validate_authority(authority, provenance)
        base_bundle = temporary_root / "base-bundle"
        module.prepare_bundle(
            audit_root,
            base_bundle,
            authority,
            provenance,
            context,
        )

        curve_bundle = temporary_root / "rr01-curve-bundle"
        shutil.copytree(base_bundle, curve_bundle)
        curve_rows = [dict(row) for row in provenance]
        curve_report_row = next(
            row for row in curve_rows if row["id"] == "py-nbx-shipped"
        )
        curve_report_path = curve_bundle / curve_report_row["release_path"]
        curve_report = report_io.load_report(curve_report_path)
        curve_result = next(
            row
            for row in curve_report["results"]
            if "error" not in row and row.get("gold_symbol_count", 0) > 0
        )
        stored = curve_result["token_coverage_wire"]["tokens_to_coverage"]
        stored["50"] = int(stored["50"]) + 1
        module.write_json(curve_report_path, curve_report)
        curve_report_row["sha256"] = digest(curve_report_path)
        module.audit_evidence(curve_bundle, curve_rows, "release_path")
        module.recompute_results(
            curve_bundle,
            "release_path",
            authority,
            curve_rows,
            context,
        )
        print("RED accepted: rr01-stored-curve-corruption")

        error_bundle = temporary_root / "rr03-error-bundle"
        shutil.copytree(base_bundle, error_bundle)
        error_rows = [dict(row) for row in provenance]
        error_report_row = next(
            row for row in error_rows if row["id"] == "rust-graphify-32k"
        )
        error_report_path = error_bundle / error_report_row["release_path"]
        error_report = module.load_json(error_report_path)
        error_report["results"] = [
            row
            for row in error_report["results"]
            if row.get("instance_id") != "astral-sh__ruff-15626"
        ]
        module.write_json(error_report_path, error_report)
        error_report_row["sha256"] = digest(error_report_path)
        module.audit_evidence(error_bundle, error_rows, "release_path")
        module.recompute_results(
            error_bundle,
            "release_path",
            authority,
            error_rows,
            context,
        )
        print("RED accepted: rr03-zero-gold-error-row-removal")

        partial_target = temporary_root / "rr08-partial-target"
        real_copyfile = module.shutil.copyfile
        copy_calls = 0

        def fail_second_copy(source: Path, destination: Path) -> None:
            nonlocal copy_calls
            copy_calls += 1
            if copy_calls == 2:
                raise OSError("injected copy failure")
            real_copyfile(source, destination)

        module.shutil.copyfile = fail_second_copy
        try:
            module.prepare_bundle(
                audit_root,
                partial_target,
                authority,
                provenance,
                context,
            )
        except OSError as exc:
            if str(exc) != "injected copy failure":
                raise
        finally:
            module.shutil.copyfile = real_copyfile
        if not partial_target.is_dir() or not any(partial_target.rglob("*")):
            raise RuntimeError("pre-fix bundle did not expose its partial target")
        print("RED exposed: rr08-copy-failure-left-partial-target")

    ci_text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    lint_line = next(line for line in ci_text.splitlines() if "ruff check" in line)
    if "v2/verify.py" in lint_line:
        raise RuntimeError("pre-fix CI already lints v2/verify.py")
    print("RED omitted: rr07-v2-verifier-from-ci-lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
