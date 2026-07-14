#!/usr/bin/env python3
"""Reconcile BIDS functional scans with raw behavioral CSVs.

Read-only analysis: matches BIDS BOLD files to raw behavioral CSVs and
produces a TSV manifest for human review. Does not modify any data on disk
except writing the output TSV.

Usage:
    uv run python scripts/reconcile_sessions.py \
        --bids-dir /scratch/users/logben/discovery_bids \
        --raw-dir /oak/.../behavioral_data/raw_cleaned \
        --scan-notes docs/SCAN-NOTES.md \
        --output /tmp/reconciliation_manifest.tsv
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layer 1: Task name normalization
# ---------------------------------------------------------------------------

_LONG_NAME_TO_BIDS: dict[str, str] = {
    "stop_signal": "stopSignal",
    "flanker": "flanker",
    "go_nogo": "goNogo",
    "n_back": "nBack",
    "cued_task_switching": "cuedTS",
    "spatial_task_switching": "spatialTS",
    "directed_forgetting": "directedForgetting",
    "shape_matching": "shapeMatching",
    "rest": "rest",
    "stop_signal_with_flanker": "stopSignalWFlanker",
    "stop_signal_with_directed_forgetting": "stopSignalWDirectedForgetting",
    "directed_forgetting_with_flanker": "directedForgettingWFlanker",
    "directed_forgetting_with_cued_task_switching": "directedForgettingWCuedTS",
    "cued_task_switching_with_directed_forgetting": "directedForgettingWCuedTS",
    "spatial_task_switching_with_cued_task_switching": "spatialTSWCuedTS",
    "flanker_with_shape_matching": "flankerWShapeMatching",
    "flanker_with_cued_task_switching": "cuedTSWFlanker",
    "n_back_with_shape_matching": "nBackWShapeMatching",
    "n_back_with_spatial_task_switching": "nBackWSpatialTS",
    "shape_matching_with_cued_task_switching": "shapeMatchingWCuedTS",
    "shape_matching_with_spatial_task_switching": "spatialTSWShapeMatching",
}

_DASH_TO_BIDS: dict[str, str] = {
    "go-nogo": "goNogo",
    "stop-signal": "stopSignal",
    "shape-matching": "shapeMatching",
    "spatial-task-switching": "spatialTS",
    "cued-task-switching": "cuedTS",
    "directed-forgetting": "directedForgetting",
    "n-back": "nBack",
    # Full camelCase variants (used by s76)
    "cuedTaskSwitching": "cuedTS",
    "spatialTaskSwitching": "spatialTS",
}

# Known camelCase BIDS task names (passthrough)
_CAMEL_CASE_TASKS: set[str] = {
    "goNogo",
    "stopSignal",
    "flanker",
    "nBack",
    "cuedTS",
    "spatialTS",
    "directedForgetting",
    "shapeMatching",
    "rest",
    "stopSignalWFlanker",
    "stopSignalWDirectedForgetting",
    "directedForgettingWFlanker",
    "directedForgettingWCuedTS",
    "spatialTSWCuedTS",
    "flankerWShapeMatching",
    "cuedTSWFlanker",
    "nBackWShapeMatching",
    "nBackWSpatialTS",
    "shapeMatchingWCuedTS",
    "spatialTSWShapeMatching",
}


def normalize_task_name(raw: str) -> str | None:
    """Normalize a task name to its BIDS camelCase form.

    Accepts dash-separated, underscore long names, and camelCase passthrough.
    Returns None for unrecognized task names.
    """
    # CamelCase passthrough
    if raw in _CAMEL_CASE_TASKS:
        return raw

    # Dash-separated names
    if raw in _DASH_TO_BIDS:
        return _DASH_TO_BIDS[raw]

    # Underscore long names
    if raw in _LONG_NAME_TO_BIDS:
        return _LONG_NAME_TO_BIDS[raw]

    return None


# ---------------------------------------------------------------------------
# Layer 2: CSV filename parsing
# ---------------------------------------------------------------------------

# Regex for BIDS-style filenames: sub-XXX_ses-YY_task-TASKNAME_desc-...
_BIDS_CSV_RE = re.compile(
    r"sub-\w+[_-]ses[_-](\d+)[_-]task[_-](.+?)[_-]desc[_-]"
)

# Regex for descriptive filenames: taskname__fmri_results
_DESCRIPTIVE_CSV_RE = re.compile(
    r"^(.+?)(?:_single_task_network)?__fmri_results"
)


def parse_behavioral_csv(filename: str) -> str | None:
    """Extract and normalize task name from a behavioral CSV filename.

    Handles four naming patterns:
    1. Descriptive: cued_task_switching_single_task_network__fmri_results (5).csv
    2. BIDS dash: sub-s03_ses-1_task-go-nogo_desc-raw.csv
    3. BIDS camelCase: sub-s76_ses-01_task-stopSignal_desc-beh.csv
    4. Dual underscore: sub-s29_ses_11_task-directed_forgetting_with_flanker_desc_raw.csv

    Returns None for practice files and unrecognized filenames.
    """
    # Skip practice files
    if "__practice" in filename or "_practice_" in filename:
        return None

    # Try BIDS-style patterns first (patterns 2, 3, 4)
    m = _BIDS_CSV_RE.search(filename)
    if m:
        task_raw = m.group(2)
        # Normalize (handles camelCase, dash-separated, and underscore names)
        result = normalize_task_name(task_raw)
        if result is not None:
            return result
        return None

    # Try descriptive pattern (pattern 1)
    m = _DESCRIPTIVE_CSV_RE.search(filename)
    if m:
        task_raw = m.group(1)
        result = normalize_task_name(task_raw)
        if result is not None:
            return result
        return None

    return None


# ---------------------------------------------------------------------------
# Layer 3: Directory scanning
# ---------------------------------------------------------------------------

def _zero_pad_session(ses: str) -> str:
    """Normalize session labels to zero-padded two-digit form.

    Examples: 'ses-1' -> 'ses-01', 'ses-01' -> 'ses-01', 'ses-11' -> 'ses-11'
    """
    m = re.match(r"ses-(\d+)", ses)
    if m:
        return f"ses-{int(m.group(1)):02d}"
    return ses


def scan_bids_bold(bids_dir: str | Path) -> dict:
    """Scan a BIDS directory for BOLD functional files.

    Returns dict keyed by (subject, session, task) with values containing
    bold_path (absolute path to one representative file).
    Deduplicates across echoes and runs (a task counts once per session).
    """
    bids_dir = Path(bids_dir)
    result: dict[tuple[str, str, str], dict] = {}

    bold_re = re.compile(
        r"(sub-[^_]+)_(ses-[^_]+)_task-([^_]+).*_bold\.nii\.gz$"
    )

    for nifti_path in sorted(bids_dir.glob("sub-*/ses-*/func/*_bold.nii.gz")):
        m = bold_re.search(nifti_path.name)
        if not m:
            log.warning("Could not parse BOLD filename: %s", nifti_path.name)
            continue

        subject = m.group(1)  # e.g. sub-s03
        session = m.group(2)  # e.g. ses-01
        task = m.group(3)     # e.g. goNogo

        key = (subject, session, task)
        if key not in result:
            result[key] = {"bold_path": str(nifti_path.resolve())}

    return result


def scan_raw_behavioral(raw_dir: str | Path) -> dict:
    """Scan raw behavioral directory for CSV files.

    Expects structure: raw_dir/s*/ses-*/*.csv
    Also scans:        raw_dir/exclusions/s*/ses-*/*.csv

    Skips practice/, pretouch/, dropped_subjects/, extra/ directories.

    Returns dict keyed by (subject, session, task) with values containing
    raw_path (absolute path) and in_exclusions flag.
    """
    raw_dir = Path(raw_dir)
    result: dict[tuple[str, str, str], dict] = {}
    skip_dirs = {"practice", "pretouch", "dropped_subjects", "extra"}

    def _scan_tree(base_dir: Path, in_exclusions: bool = False) -> None:
        # Pattern: base_dir/s*/ses-*/*.csv
        for csv_path in sorted(base_dir.glob("s*/ses-*/*.csv")):
            # Skip if any parent directory is in the skip list
            if any(part in skip_dirs for part in csv_path.parts):
                continue

            # Extract subject and session from path
            # Path looks like: .../s03/ses-1/file.csv
            parts = csv_path.relative_to(base_dir).parts
            if len(parts) < 3:
                continue

            raw_subject = parts[0]   # e.g. "s03"
            raw_session = parts[1]   # e.g. "ses-1"

            subject = f"sub-{raw_subject}"
            session = _zero_pad_session(raw_session)

            task = parse_behavioral_csv(csv_path.name)
            if task is None:
                continue

            key = (subject, session, task)
            if key not in result:
                result[key] = {
                    "raw_path": str(csv_path.resolve()),
                    "in_exclusions": in_exclusions,
                }

    _scan_tree(raw_dir, in_exclusions=False)

    exclusions_dir = raw_dir / "exclusions"
    if exclusions_dir.is_dir():
        _scan_tree(exclusions_dir, in_exclusions=True)

    return result


# ---------------------------------------------------------------------------
# Layer 4: Manifest generation
# ---------------------------------------------------------------------------

def _load_scan_notes(scan_notes_path: str | Path) -> str:
    """Load SCAN-NOTES.md content for annotation lookup."""
    path = Path(scan_notes_path)
    if path.exists():
        return path.read_text()
    log.warning("Scan notes file not found: %s", scan_notes_path)
    return ""


def _find_notes(
    scan_notes_text: str,
    subject: str,
    session: str,
    task: str,
) -> str:
    """Search SCAN-NOTES.md for mentions of this subject/session/task.

    Finds lines that mention the subject AND (session or task).
    Also captures lines immediately following a subject-only header
    if they mention the session or task.

    Returns matching context lines or empty string.
    """
    if not scan_notes_text:
        return ""

    # Strip "sub-" prefix for searching (notes use s03, not sub-s03)
    short_subject = subject.replace("sub-", "")

    notes_lines: list[str] = []
    lines = scan_notes_text.splitlines()
    in_subject_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        has_subject = short_subject in line
        has_session = session in line
        has_task = task in line

        # Track whether we are inside a section about this subject
        if has_subject and stripped.startswith("#"):
            in_subject_section = True
            continue  # Skip the header itself
        elif stripped.startswith("#"):
            in_subject_section = False
            continue

        # Lines that mention the subject AND (session or task)
        if has_subject and (has_session or has_task):
            if stripped not in notes_lines:
                notes_lines.append(stripped)
        # Lines in the subject's section that mention session or task
        elif in_subject_section and (has_session or has_task):
            if stripped not in notes_lines:
                notes_lines.append(stripped)

    return "; ".join(notes_lines[:3])  # Cap at 3 relevant lines


def reconcile(
    bids_dir: str | Path,
    raw_dir: str | Path,
    scan_notes_path: str | Path | None = None,
) -> list[dict]:
    """Match BIDS BOLD scans to raw behavioral CSVs.

    Returns a list of row dicts suitable for TSV output with columns:
    subject, session, task, status, action, dest_session, raw_path,
    bold_path, same_task_other_sessions, notes
    """
    bids_bold = scan_bids_bold(bids_dir)
    raw_beh = scan_raw_behavioral(raw_dir)

    scan_notes_text = ""
    if scan_notes_path:
        scan_notes_text = _load_scan_notes(scan_notes_path)

    # Determine subjects present in BIDS
    bids_subjects = {k[0] for k in bids_bold}

    # Filter raw behavioral to only BIDS subjects
    raw_beh_filtered = {
        k: v for k, v in raw_beh.items() if k[0] in bids_subjects
    }

    # Build cross-session index: for each (subject, task), which sessions exist?
    bids_sessions_by_subj_task: dict[tuple[str, str], set[str]] = {}
    for (subj, ses, task) in bids_bold:
        bids_sessions_by_subj_task.setdefault((subj, task), set()).add(ses)

    raw_sessions_by_subj_task: dict[tuple[str, str], set[str]] = {}
    for (subj, ses, task) in raw_beh_filtered:
        raw_sessions_by_subj_task.setdefault((subj, task), set()).add(ses)

    all_keys = set(bids_bold.keys()) | set(raw_beh_filtered.keys())

    rows: list[dict] = []
    for key in sorted(all_keys):
        subject, session, task = key
        if subject not in bids_subjects:
            continue

        has_bold = key in bids_bold
        has_beh = key in raw_beh_filtered

        if has_bold and has_beh:
            status = "matched"
            action = "copy"
        elif has_bold and not has_beh:
            status = "bold_without_behavioral"
            action = "pending"
        else:
            status = "behavioral_without_bold"
            action = "pending"

        bold_path = bids_bold[key]["bold_path"] if has_bold else ""
        raw_path = raw_beh_filtered[key]["raw_path"] if has_beh else ""

        # Cross-session context for unmatched rows
        other_sessions = ""
        if status != "matched":
            # Check if same subject+task appears in any other session
            bids_other = bids_sessions_by_subj_task.get(
                (subject, task), set()
            ) - {session}
            raw_other = raw_sessions_by_subj_task.get(
                (subject, task), set()
            ) - {session}
            parts = []
            for ses in sorted(bids_other | raw_other):
                in_bids = ses in bids_other
                in_raw = ses in raw_other
                if in_bids and in_raw:
                    parts.append(f"{ses}:matched")
                elif in_bids:
                    parts.append(f"{ses}:bold_only")
                else:
                    parts.append(f"{ses}:behavioral_only")
            if parts:
                other_sessions = ",".join(parts)

        notes = ""
        if scan_notes_text:
            notes = _find_notes(scan_notes_text, subject, session, task)

        rows.append(
            {
                "subject": subject,
                "session": session,
                "task": task,
                "status": status,
                "action": action,
                "dest_session": session if action == "copy" else "",
                "raw_path": raw_path,
                "bold_path": bold_path,
                "same_task_other_sessions": other_sessions,
                "notes": notes,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Layer 5: TSV output + CLI
# ---------------------------------------------------------------------------

TSV_COLUMNS = [
    "subject",
    "session",
    "task",
    "status",
    "action",
    "dest_session",
    "raw_path",
    "bold_path",
    "same_task_other_sessions",
    "notes",
]


def write_manifest_tsv(rows: list[dict], output_path: str | Path) -> None:
    """Write reconciliation manifest to a TSV file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    log.info("Wrote manifest to %s (%d rows)", output_path, len(rows))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile BIDS functional scans with raw behavioral CSVs. "
            "Read-only analysis that produces a TSV manifest for human review."
        )
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        required=True,
        help="Path to raw_cleaned behavioral directory",
    )
    parser.add_argument(
        "--bids-dir",
        type=Path,
        required=True,
        help="Path to BIDS directory",
    )
    parser.add_argument(
        "--scan-notes",
        type=Path,
        default=None,
        help="Path to SCAN-NOTES.md for auto-annotation",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output TSV path",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.bids_dir.exists():
        parser.error(f"BIDS directory not found: {args.bids_dir}")
    if not args.raw_dir.exists():
        parser.error(f"Raw directory not found: {args.raw_dir}")

    rows = reconcile(
        bids_dir=args.bids_dir,
        raw_dir=args.raw_dir,
        scan_notes_path=args.scan_notes,
    )

    write_manifest_tsv(rows, args.output)

    # Print summary
    matched = sum(1 for r in rows if r["status"] == "matched")
    bold_only = sum(1 for r in rows if r["status"] == "bold_without_behavioral")
    beh_only = sum(1 for r in rows if r["status"] == "behavioral_without_bold")

    print(f"Total rows: {len(rows)}")
    print(f"  Matched: {matched}")
    print(f"  BOLD without behavioral: {bold_only}")
    print(f"  Behavioral without BOLD: {beh_only}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
