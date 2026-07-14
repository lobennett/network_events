#!/usr/bin/env python3
"""Migrate behavioral data (in-scanner + out-of-scanner + survey) to BIDS sourcedata.

Merged from the original ``migrate_behavioral.py`` (in-scanner, manifest-driven)
and ``migrate_archive.py`` (out-of-scanner practice/pretouch + survey data)
extraction sources.

In-scanner behavioral:
  Source: reviewed reconciliation manifest (see network_events.reconcile)
  Target: sourcedata/in_scanner_behavior/sub-{sub}/ses-{X}/beh/*_beh.csv

Out-of-scanner behavioral:
  Sources:
    - {raw_dir}/s{sub}/ses-{X}/practice/*.csv  (per-session practice runs)
    - {raw_dir}/s{sub}/pretouch/*.csv          (subject-level pretouch runs)
  Target: sourcedata/out_scanner_behavior/sub-{sub}/

Survey data:
  Sources:
    - {survey_root}/prescan_surveys/raw/s{sub}/*  (JSON + PDF)
    - {survey_root}/demographics_surveys/raw/s{sub}/*
  Target: sourcedata/survey_data/sub-{sub}/{category}/

Usage:
    uv run python -m network_events.migrate --help
"""
import argparse
import csv
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-scanner behavioral (from migrate_behavioral.py)
# ---------------------------------------------------------------------------

def migrate_from_manifest(
    manifest_path: Path,
    output_dir: Path,
    strict: bool = False,
) -> dict:
    """Copy in-scanner behavioral files according to the reviewed manifest.

    Args:
        manifest_path: TSV manifest from network_events.reconcile
        output_dir: Sourcedata output root
        strict: If True, raise SystemExit if any rows are still 'pending'

    Returns:
        Report dict with counts.
    """
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)

    with open(manifest_path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    report = {
        "copied": 0,
        "skipped_pending": 0,
        "skipped_irreconcilable": 0,
        "skipped_skip": 0,
        "skipped_no_raw_path": 0,
        "files": [],
    }

    pending_rows = [r for r in rows if r["action"] == "pending"]
    if strict and pending_rows:
        log.error(
            "%d rows still marked 'pending'. Resolve all discrepancies before migrating.",
            len(pending_rows),
        )
        sys.exit(1)

    for row in rows:
        action = row["action"]

        if action == "pending":
            report["skipped_pending"] += 1
            continue
        if action == "skip":
            report["skipped_skip"] += 1
            continue
        if action == "irreconcilable":
            report["skipped_irreconcilable"] += 1
            continue
        if action != "copy":
            log.warning("Unknown action '%s' for %s %s %s, skipping",
                        action, row["subject"], row["session"], row["task"])
            continue

        raw_path = row.get("raw_path", "")
        if not raw_path or not Path(raw_path).exists():
            log.warning("Raw file not found: %s", raw_path)
            report["skipped_no_raw_path"] += 1
            continue

        subject = row["subject"]
        dest_session = row["dest_session"]
        task = row["task"]
        dest_run = row.get("dest_run", "").strip()

        sub_label = f"sub-{subject}" if not subject.startswith("sub-") else subject
        run_part = f"_run-{dest_run}" if dest_run else ""
        filename = f"{sub_label}_{dest_session}_task-{task}{run_part}_beh.csv"
        dest_path = output_dir / "in_scanner_behavior" / sub_label / dest_session / "beh" / filename

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw_path, dest_path)

        report["copied"] += 1
        report["files"].append({
            "src": raw_path,
            "dest": str(dest_path),
            "subject": subject,
            "session": dest_session,
            "task": task,
        })

        log.info("Copied %s -> %s", Path(raw_path).name, dest_path)

    return report


def main_in_scanner():
    parser = argparse.ArgumentParser(
        description="Migrate in-scanner behavioral data to BIDS sourcedata using reviewed manifest"
    )
    parser.add_argument("--manifest", required=True, type=Path,
                        help="Reviewed TSV manifest from network_events.reconcile")
    parser.add_argument("--raw-dir", required=True, type=Path,
                        help="Path to raw_cleaned behavioral directory (for out-of-scanner, survey, mTurk)")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="Sourcedata output root")
    parser.add_argument("--sample", required=True, choices=["discovery", "validation"],
                        help="Sample name (for filtering out-of-scanner/survey subjects)")
    parser.add_argument("--strict", action="store_true",
                        help="Fail if any manifest rows are still 'pending'")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    report = migrate_from_manifest(args.manifest, args.output_dir, strict=args.strict)

    # Write migration report
    report_out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest),
        "sample": args.sample,
        **{k: v for k, v in report.items() if k != "files"},
        "files": report["files"],
    }
    report_path = args.output_dir / "migration_report.json"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_out, indent=2) + "\n")

    print(f"Copied: {report['copied']}")
    print(f"Skipped (pending): {report['skipped_pending']}")
    print(f"Skipped (irreconcilable): {report['skipped_irreconcilable']}")
    print(f"Skipped (skip): {report['skipped_skip']}")
    print(f"Report: {report_path}")


# ---------------------------------------------------------------------------
# Out-of-scanner behavioral + survey (from migrate_archive.py)
# ---------------------------------------------------------------------------

def _load_subjects_from_manifests(manifest_paths):
    """Collect all subject labels appearing in the provided manifests."""
    subjects = set()
    for mp in manifest_paths:
        with open(mp, newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                sub = row["subject"].replace("sub-", "")
                subjects.add(sub)
    return subjects


def migrate_out_scanner(raw_dir, output_dir, subjects):
    """Copy practice and pretouch files for each subject."""
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir) / "out_scanner_behavior"
    copied = 0

    for sub in sorted(subjects):
        sub_raw = raw_dir / sub
        if not sub_raw.exists():
            continue
        sub_out = output_dir / f"sub-{sub}"
        sub_out.mkdir(parents=True, exist_ok=True)

        # Session-level practice
        for ses_dir in sub_raw.glob("ses-*/practice"):
            ses_label = ses_dir.parent.name  # ses-02
            for csv_file in ses_dir.glob("*.csv"):
                dest = sub_out / f"{ses_label}_{csv_file.name}"
                shutil.copy2(csv_file, dest)
                copied += 1

        # Subject-level pretouch
        pretouch_dir = sub_raw / "pretouch"
        if pretouch_dir.exists():
            for csv_file in pretouch_dir.glob("*.csv"):
                dest = sub_out / f"pretouch_{csv_file.name}"
                shutil.copy2(csv_file, dest)
                copied += 1

    log.info("Out-of-scanner: copied %d files", copied)
    return copied


def migrate_survey(survey_root, output_dir, subjects):
    """Copy prescan_surveys and demographics_surveys raw files per subject."""
    survey_root = Path(survey_root)
    output_dir = Path(output_dir) / "survey_data"
    copied = 0

    for category in ("prescan_surveys", "demographics_surveys"):
        raw_cat = survey_root / category / "raw"
        if not raw_cat.exists():
            log.warning("Survey source missing: %s", raw_cat)
            continue
        for sub in sorted(subjects):
            sub_src = raw_cat / sub
            if not sub_src.exists():
                continue
            sub_dest = output_dir / f"sub-{sub}" / category
            sub_dest.mkdir(parents=True, exist_ok=True)
            for f in sub_src.iterdir():
                if f.is_file():
                    shutil.copy2(f, sub_dest / f.name)
                    copied += 1

    log.info("Survey: copied %d files", copied)
    return copied


def main_archive():
    parser = argparse.ArgumentParser(
        description="Migrate out-of-scanner behavioral and survey data to BIDS sourcedata"
    )
    parser.add_argument("--raw-dir", required=True, type=Path,
                        help="raw_cleaned behavioral archive")
    parser.add_argument("--survey-root", required=True, type=Path,
                        help="survey_data root containing prescan_surveys/ and demographics_surveys/")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="sourcedata output root")
    parser.add_argument("--manifests", nargs="+", required=True, type=Path,
                        help="Reconciliation manifests for subject filtering")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    subjects = _load_subjects_from_manifests(args.manifests)
    log.info("Migrating %d subjects", len(subjects))

    out_scanner_copied = migrate_out_scanner(args.raw_dir, args.output_dir, subjects)
    survey_copied = migrate_survey(args.survey_root, args.output_dir, subjects)

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "subjects": sorted(subjects),
        "out_scanner_files": out_scanner_copied,
        "survey_files": survey_copied,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "archive_migration_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print(f"Out-of-scanner: {out_scanner_copied} files")
    print(f"Survey: {survey_copied} files")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main_in_scanner()
