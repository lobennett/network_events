"""Orchestrate the behavioral half: raw behavioral dir -> BIDS (sourcedata + events).

Pure + idempotent so an operator can wrap each invocation in `datalad run`.
Review gate: without a reviewed manifest, run reconcile only and stop for review.
"""
from __future__ import annotations

import csv
from pathlib import Path

from network_events.reconcile import reconcile as _reconcile_impl, write_manifest_tsv
from network_events.migrate import (
    migrate_from_manifest,
    migrate_out_scanner,
    migrate_survey,
    _load_subjects_from_manifests,
)
from network_events.create import run_create_events
from network_events.qc import run_qc
from network_events.trim import run_trim


def reconcile(*, bids_dir, raw_dir, scan_notes=None, output):
    """Compute the reconciliation manifest and write it to ``output``.

    Thin wrapper around ``network_events.reconcile.reconcile`` (which returns
    rows only) + ``write_manifest_tsv`` (which writes them), exposed here as a
    single monkeypatchable step matching the ``run()`` call below.
    """
    rows = _reconcile_impl(bids_dir=bids_dir, raw_dir=raw_dir, scan_notes_path=scan_notes)
    write_manifest_tsv(rows, output)
    return output


def _manifest_has_pending(manifest: Path) -> bool:
    """True if any manifest row has ``action == 'pending'`` (unreviewed).

    Parses the TSV (matching migrate.py's strict-mode logic) rather than
    substring-scanning the raw text, so a free-text ``notes`` column that
    happens to contain the word "pending" can't trip the review gate. If the
    manifest has no ``action`` column, treat it as having no pending rows.
    """
    with open(Path(manifest), newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return any(row.get("action") == "pending" for row in reader)


def run(behavioral_dir, bids_dir, manifest=None, survey_root=None) -> None:
    behavioral_dir, bids_dir = Path(behavioral_dir), Path(bids_dir)
    sourcedata = bids_dir / "sourcedata"

    # 1. Reconcile (read-only) unless a reviewed manifest was supplied.
    if manifest is None:
        manifest = bids_dir / "reconciliation_manifest.tsv"
        reconcile(bids_dir=bids_dir, raw_dir=behavioral_dir, scan_notes=None, output=manifest)
        raise SystemExit(
            f"Wrote manifest for review: {manifest}. Review it, then re-run with "
            f"--manifest {manifest} to migrate + generate events."
        )
    manifest = Path(manifest)
    if _manifest_has_pending(manifest):
        raise SystemExit(f"Manifest {manifest} still has 'pending' rows — resolve them first.")

    # 2. Migrate in-scanner (per reviewed manifest) + out-of-scanner + survey (if given).
    migrate_from_manifest(manifest_path=manifest, output_dir=sourcedata, strict=True)
    subjects = _load_subjects_from_manifests([manifest])
    migrate_out_scanner(raw_dir=behavioral_dir, output_dir=sourcedata, subjects=subjects)
    if survey_root is not None:
        migrate_survey(survey_root=Path(survey_root), output_dir=sourcedata, subjects=subjects)

    # 3. Events -> QC -> behavioral trim. The in-scanner CSVs migrate to
    # sourcedata/in_scanner_behavior/sub-*/ses-*/beh/, so create/qc must scan
    # that subdir (not the sourcedata root, which holds no sub-* directly).
    in_scanner = sourcedata / "in_scanner_behavior"
    run_create_events(behavioral_dir=in_scanner, bids_dir=bids_dir)
    run_qc(behavioral_dir=in_scanner, bids_dir=bids_dir)
    run_trim(bids_dir=bids_dir)
