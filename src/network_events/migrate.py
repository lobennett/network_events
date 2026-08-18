#!/usr/bin/env python3
"""Copy out-of-scanner and survey behavioral data into BIDS sourcedata.

In-scanner CSVs arrive already cleaned and 1:1 from `network_fmri behavior-clean`,
so no manifest-driven migration happens here.

Out-of-scanner behavioral: practice/pretouch runs -> sourcedata/out_scanner_behavior/
Survey: prescan + demographics -> sourcedata/survey/
"""
import csv
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _write_migration_report(report: dict, output_dir, name: str) -> Path:
    """Write a migration provenance report JSON to ``output_dir/name``.

    Prepends a UTC ``generated`` timestamp and creates ``output_dir`` if
    needed. Shared by the ``migrate`` / ``migrate-archive`` / ``migrate-survey``
    CLI handlers so every reachable migration path leaves a provenance record.
    Returns the report path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"generated": datetime.now(timezone.utc).isoformat(), **report}
    report_path = output_dir / name
    report_path.write_text(json.dumps(payload, indent=2) + "\n")
    return report_path


# ---------------------------------------------------------------------------
# In-scanner behavioral (from migrate_behavioral.py)
# ---------------------------------------------------------------------------

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
