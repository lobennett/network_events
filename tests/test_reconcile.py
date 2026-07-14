"""Tests for network_events.reconcile (moved from scripts/reconcile_sessions.py)"""
import csv
from pathlib import Path

from network_events.reconcile import (
    TSV_COLUMNS,
    _zero_pad_session,
    normalize_task_name,
    parse_behavioral_csv,
    reconcile,
    scan_bids_bold,
    scan_raw_behavioral,
    write_manifest_tsv,
)


# ===================================================================
# Layer 1: normalize_task_name
# ===================================================================


class TestNormalizeTaskName:
    """Tests for task name normalization."""

    def test_camelcase_passthrough(self):
        assert normalize_task_name("goNogo") == "goNogo"
        assert normalize_task_name("stopSignal") == "stopSignal"
        assert normalize_task_name("flanker") == "flanker"
        assert normalize_task_name("nBack") == "nBack"
        assert normalize_task_name("rest") == "rest"
        assert normalize_task_name("cuedTS") == "cuedTS"
        assert normalize_task_name("spatialTS") == "spatialTS"
        assert normalize_task_name("directedForgetting") == "directedForgetting"
        assert normalize_task_name("shapeMatching") == "shapeMatching"

    def test_camelcase_dual_tasks(self):
        assert normalize_task_name("stopSignalWFlanker") == "stopSignalWFlanker"
        assert normalize_task_name("directedForgettingWFlanker") == "directedForgettingWFlanker"
        assert normalize_task_name("cuedTSWFlanker") == "cuedTSWFlanker"
        assert normalize_task_name("shapeMatchingWCuedTS") == "shapeMatchingWCuedTS"
        assert normalize_task_name("nBackWShapeMatching") == "nBackWShapeMatching"

    def test_dash_separated(self):
        assert normalize_task_name("go-nogo") == "goNogo"
        assert normalize_task_name("stop-signal") == "stopSignal"
        assert normalize_task_name("shape-matching") == "shapeMatching"
        assert normalize_task_name("spatial-task-switching") == "spatialTS"
        assert normalize_task_name("cued-task-switching") == "cuedTS"
        assert normalize_task_name("directed-forgetting") == "directedForgetting"
        assert normalize_task_name("n-back") == "nBack"

    def test_underscore_single_tasks(self):
        assert normalize_task_name("stop_signal") == "stopSignal"
        assert normalize_task_name("go_nogo") == "goNogo"
        assert normalize_task_name("n_back") == "nBack"
        assert normalize_task_name("cued_task_switching") == "cuedTS"
        assert normalize_task_name("spatial_task_switching") == "spatialTS"
        assert normalize_task_name("directed_forgetting") == "directedForgetting"
        assert normalize_task_name("shape_matching") == "shapeMatching"
        assert normalize_task_name("flanker") == "flanker"
        assert normalize_task_name("rest") == "rest"

    def test_underscore_dual_tasks(self):
        assert normalize_task_name("stop_signal_with_flanker") == "stopSignalWFlanker"
        assert normalize_task_name("stop_signal_with_directed_forgetting") == "stopSignalWDirectedForgetting"
        assert normalize_task_name("directed_forgetting_with_flanker") == "directedForgettingWFlanker"
        assert normalize_task_name("directed_forgetting_with_cued_task_switching") == "directedForgettingWCuedTS"
        assert normalize_task_name("cued_task_switching_with_directed_forgetting") == "directedForgettingWCuedTS"
        assert normalize_task_name("spatial_task_switching_with_cued_task_switching") == "spatialTSWCuedTS"
        assert normalize_task_name("flanker_with_shape_matching") == "flankerWShapeMatching"
        assert normalize_task_name("flanker_with_cued_task_switching") == "cuedTSWFlanker"
        assert normalize_task_name("n_back_with_shape_matching") == "nBackWShapeMatching"
        assert normalize_task_name("n_back_with_spatial_task_switching") == "nBackWSpatialTS"
        assert normalize_task_name("shape_matching_with_cued_task_switching") == "shapeMatchingWCuedTS"
        assert normalize_task_name("shape_matching_with_spatial_task_switching") == "spatialTSWShapeMatching"

    def test_unknown_returns_none(self):
        assert normalize_task_name("unknown_task") is None
        assert normalize_task_name("") is None
        assert normalize_task_name("foobar") is None


# ===================================================================
# Layer 2: parse_behavioral_csv
# ===================================================================


class TestParseBehavioralCsv:
    """Tests for CSV filename parsing."""

    def test_descriptive_pattern(self):
        """Pattern 1: descriptive filenames with __fmri_results."""
        assert (
            parse_behavioral_csv(
                "cued_task_switching_single_task_network__fmri_results (5).csv"
            )
            == "cuedTS"
        )
        assert (
            parse_behavioral_csv("stop_signal__fmri_results.csv")
            == "stopSignal"
        )
        assert (
            parse_behavioral_csv("directed_forgetting__fmri_results (2).csv")
            == "directedForgetting"
        )
        assert (
            parse_behavioral_csv(
                "directed_forgetting_with_flanker__fmri_results.csv"
            )
            == "directedForgettingWFlanker"
        )

    def test_bids_dash_pattern(self):
        """Pattern 2: BIDS-style with dash-separated task names."""
        assert (
            parse_behavioral_csv("sub-s03_ses-1_task-go-nogo_desc-raw.csv")
            == "goNogo"
        )
        assert (
            parse_behavioral_csv("sub-s10_ses-03_task-stop-signal_desc-raw.csv")
            == "stopSignal"
        )
        assert (
            parse_behavioral_csv("sub-s19_ses-05_task-n-back_desc-raw.csv")
            == "nBack"
        )

    def test_bids_camelcase_pattern(self):
        """Pattern 3: BIDS-style with camelCase task names."""
        assert (
            parse_behavioral_csv("sub-s76_ses-01_task-stopSignal_desc-beh.csv")
            == "stopSignal"
        )
        assert (
            parse_behavioral_csv("sub-s43_ses-03_task-flanker_desc-raw.csv")
            == "flanker"
        )
        assert (
            parse_behavioral_csv("sub-s10_ses-02_task-nBack_desc-beh.csv")
            == "nBack"
        )

    def test_dual_underscore_pattern(self):
        """Pattern 4: BIDS-style with underscore task names."""
        assert (
            parse_behavioral_csv(
                "sub-s29_ses_11_task-directed_forgetting_with_flanker_desc_raw.csv"
            )
            == "directedForgettingWFlanker"
        )
        assert (
            parse_behavioral_csv(
                "sub-s29_ses_11_task-stop_signal_with_flanker_desc_raw.csv"
            )
            == "stopSignalWFlanker"
        )

    def test_practice_files_skipped(self):
        """Practice files should return None."""
        assert parse_behavioral_csv("go_nogo__practice__fmri_results.csv") is None
        assert parse_behavioral_csv("sub-s03_ses-1_task-flanker_practice_desc-raw.csv") is None

    def test_unrecognized_returns_none(self):
        """Unrecognized filenames should return None."""
        assert parse_behavioral_csv("random_file.csv") is None
        assert parse_behavioral_csv("notes.txt") is None
        assert parse_behavioral_csv("") is None


# ===================================================================
# Layer 3: Directory scanning
# ===================================================================


def _make_bold(tmp_path, sub, ses, task, run=1, echo=1):
    """Create a minimal BOLD NIfTI placeholder (empty file for scanning tests)."""
    func_dir = tmp_path / f"sub-{sub}" / ses / "func"
    func_dir.mkdir(parents=True, exist_ok=True)
    stem = f"sub-{sub}_{ses}_task-{task}_run-{run:02d}_echo-{echo}_bold.nii.gz"
    nifti_path = func_dir / stem
    nifti_path.write_bytes(b"")  # Empty file; we only need it to exist
    return nifti_path


def _make_raw_csv(raw_dir, subject, session, filename):
    """Create a minimal behavioral CSV in raw directory structure."""
    csv_dir = raw_dir / subject / session
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / filename
    csv_path.write_text("col1,col2\n1,2\n")
    return csv_path


class TestZeroPadSession:
    """Tests for session zero-padding."""

    def test_single_digit(self):
        assert _zero_pad_session("ses-1") == "ses-01"

    def test_already_padded(self):
        assert _zero_pad_session("ses-01") == "ses-01"

    def test_double_digit(self):
        assert _zero_pad_session("ses-11") == "ses-11"

    def test_non_standard(self):
        assert _zero_pad_session("ses-foo") == "ses-foo"


class TestScanBidsBold:
    """Tests for BIDS BOLD directory scanning."""

    def test_basic_scan(self, tmp_path):
        _make_bold(tmp_path, "s03", "ses-01", "goNogo")
        _make_bold(tmp_path, "s03", "ses-01", "flanker")

        result = scan_bids_bold(tmp_path)

        assert ("sub-s03", "ses-01", "goNogo") in result
        assert ("sub-s03", "ses-01", "flanker") in result
        assert len(result) == 2

    def test_deduplication_across_echoes(self, tmp_path):
        """Multiple echoes of the same task should count as one entry."""
        _make_bold(tmp_path, "s03", "ses-01", "goNogo", echo=1)
        _make_bold(tmp_path, "s03", "ses-01", "goNogo", echo=2)
        _make_bold(tmp_path, "s03", "ses-01", "goNogo", echo=3)

        result = scan_bids_bold(tmp_path)

        assert len(result) == 1
        assert ("sub-s03", "ses-01", "goNogo") in result

    def test_deduplication_across_runs(self, tmp_path):
        """Multiple runs of the same task should count as one entry."""
        _make_bold(tmp_path, "s03", "ses-01", "goNogo", run=1)
        _make_bold(tmp_path, "s03", "ses-01", "goNogo", run=2)

        result = scan_bids_bold(tmp_path)

        assert len(result) == 1
        assert ("sub-s03", "ses-01", "goNogo") in result

    def test_different_sessions(self, tmp_path):
        _make_bold(tmp_path, "s03", "ses-01", "goNogo")
        _make_bold(tmp_path, "s03", "ses-02", "goNogo")

        result = scan_bids_bold(tmp_path)

        assert len(result) == 2
        assert ("sub-s03", "ses-01", "goNogo") in result
        assert ("sub-s03", "ses-02", "goNogo") in result

    def test_empty_dir(self, tmp_path):
        result = scan_bids_bold(tmp_path)
        assert len(result) == 0

    def test_bold_path_is_absolute(self, tmp_path):
        _make_bold(tmp_path, "s03", "ses-01", "flanker")
        result = scan_bids_bold(tmp_path)
        bold_path = result[("sub-s03", "ses-01", "flanker")]["bold_path"]
        assert Path(bold_path).is_absolute()


class TestScanRawBehavioral:
    """Tests for raw behavioral directory scanning."""

    def test_basic_scan(self, tmp_path):
        _make_raw_csv(tmp_path, "s03", "ses-01", "sub-s03_ses-01_task-goNogo_desc-raw.csv")
        _make_raw_csv(tmp_path, "s03", "ses-01", "sub-s03_ses-01_task-flanker_desc-raw.csv")

        result = scan_raw_behavioral(tmp_path)

        assert ("sub-s03", "ses-01", "goNogo") in result
        assert ("sub-s03", "ses-01", "flanker") in result
        assert len(result) == 2

    def test_session_zero_padding(self, tmp_path):
        """ses-1 should be normalized to ses-01."""
        _make_raw_csv(tmp_path, "s03", "ses-1", "sub-s03_ses-1_task-goNogo_desc-raw.csv")

        result = scan_raw_behavioral(tmp_path)

        assert ("sub-s03", "ses-01", "goNogo") in result
        assert ("sub-s03", "ses-1", "goNogo") not in result

    def test_exclusions_directory(self, tmp_path):
        """Files in exclusions/ directory should be found with in_exclusions=True."""
        excl_dir = tmp_path / "exclusions"
        _make_raw_csv(excl_dir, "s180", "ses-12",
                       "shape_matching_with_cued_task_switching__fmri_results (3).csv")

        result = scan_raw_behavioral(tmp_path)

        key = ("sub-s180", "ses-12", "shapeMatchingWCuedTS")
        assert key in result
        assert result[key]["in_exclusions"] is True

    def test_normal_not_in_exclusions(self, tmp_path):
        _make_raw_csv(tmp_path, "s03", "ses-01", "sub-s03_ses-01_task-flanker_desc-raw.csv")

        result = scan_raw_behavioral(tmp_path)

        key = ("sub-s03", "ses-01", "flanker")
        assert result[key]["in_exclusions"] is False

    def test_practice_files_skipped(self, tmp_path):
        _make_raw_csv(tmp_path, "s03", "ses-01", "go_nogo__practice__fmri_results.csv")

        result = scan_raw_behavioral(tmp_path)

        assert len(result) == 0

    def test_practice_directory_skipped(self, tmp_path):
        """Files in practice/ subdirectory should be skipped."""
        prac_dir = tmp_path / "s03" / "ses-01" / "practice"
        prac_dir.mkdir(parents=True)
        (prac_dir / "go_nogo__fmri_results.csv").write_text("col1\n1\n")

        result = scan_raw_behavioral(tmp_path)

        assert len(result) == 0

    def test_descriptive_filenames(self, tmp_path):
        _make_raw_csv(tmp_path, "s10", "ses-03",
                       "cued_task_switching_single_task_network__fmri_results (5).csv")

        result = scan_raw_behavioral(tmp_path)

        assert ("sub-s10", "ses-03", "cuedTS") in result

    def test_raw_path_is_absolute(self, tmp_path):
        _make_raw_csv(tmp_path, "s03", "ses-01", "sub-s03_ses-01_task-flanker_desc-raw.csv")

        result = scan_raw_behavioral(tmp_path)

        raw_path = result[("sub-s03", "ses-01", "flanker")]["raw_path"]
        assert Path(raw_path).is_absolute()

    def test_empty_dir(self, tmp_path):
        result = scan_raw_behavioral(tmp_path)
        assert len(result) == 0


# ===================================================================
# Layer 4: Manifest generation
# ===================================================================


class TestReconcile:
    """Tests for the reconcile function."""

    def _setup_matched(self, tmp_path):
        """Set up a matched BOLD + behavioral pair."""
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"

        _make_bold(bids_dir, "s03", "ses-01", "goNogo")
        _make_raw_csv(raw_dir, "s03", "ses-01", "sub-s03_ses-01_task-goNogo_desc-raw.csv")

        return bids_dir, raw_dir

    def test_matched_pair(self, tmp_path):
        bids_dir, raw_dir = self._setup_matched(tmp_path)

        rows = reconcile(bids_dir, raw_dir)

        assert len(rows) == 1
        row = rows[0]
        assert row["subject"] == "sub-s03"
        assert row["session"] == "ses-01"
        assert row["task"] == "goNogo"
        assert row["status"] == "matched"
        assert row["action"] == "copy"
        assert row["dest_session"] == "ses-01"
        assert row["bold_path"] != ""
        assert row["raw_path"] != ""

    def test_bold_without_behavioral(self, tmp_path):
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)

        _make_bold(bids_dir, "s03", "ses-01", "goNogo")

        rows = reconcile(bids_dir, raw_dir)

        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "bold_without_behavioral"
        assert row["action"] == "pending"
        assert row["dest_session"] == ""
        assert row["raw_path"] == ""

    def test_behavioral_without_bold(self, tmp_path):
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"

        # Need at least one BOLD file so the subject is in bids_subjects
        _make_bold(bids_dir, "s03", "ses-01", "flanker")
        _make_raw_csv(raw_dir, "s03", "ses-01", "sub-s03_ses-01_task-flanker_desc-raw.csv")
        _make_raw_csv(raw_dir, "s03", "ses-01", "sub-s03_ses-01_task-goNogo_desc-raw.csv")

        rows = reconcile(bids_dir, raw_dir)

        beh_only = [r for r in rows if r["status"] == "behavioral_without_bold"]
        assert len(beh_only) == 1
        assert beh_only[0]["task"] == "goNogo"
        assert beh_only[0]["action"] == "pending"
        assert beh_only[0]["bold_path"] == ""

    def test_filters_to_bids_subjects(self, tmp_path):
        """Behavioral-only subjects (not in BIDS) should be excluded."""
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"

        _make_bold(bids_dir, "s03", "ses-01", "flanker")
        # s99 has behavioral but no BIDS data
        _make_raw_csv(raw_dir, "s99", "ses-01", "sub-s99_ses-01_task-flanker_desc-raw.csv")
        _make_raw_csv(raw_dir, "s03", "ses-01", "sub-s03_ses-01_task-flanker_desc-raw.csv")

        rows = reconcile(bids_dir, raw_dir)

        subjects = {r["subject"] for r in rows}
        assert "sub-s99" not in subjects
        assert "sub-s03" in subjects

    def test_cross_session_context(self, tmp_path):
        """Unmatched rows should show other sessions with same subject+task."""
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"

        # BOLD in ses-01 and ses-02 for goNogo
        _make_bold(bids_dir, "s03", "ses-01", "goNogo")
        _make_bold(bids_dir, "s03", "ses-02", "goNogo")

        # Behavioral only in ses-01
        _make_raw_csv(raw_dir, "s03", "ses-01", "sub-s03_ses-01_task-goNogo_desc-raw.csv")

        rows = reconcile(bids_dir, raw_dir)

        bold_only = [r for r in rows if r["status"] == "bold_without_behavioral"]
        assert len(bold_only) == 1
        assert bold_only[0]["session"] == "ses-02"
        assert "ses-01:matched" in bold_only[0]["same_task_other_sessions"]

    def test_matched_rows_have_empty_other_sessions(self, tmp_path):
        """Matched rows should have empty same_task_other_sessions."""
        bids_dir, raw_dir = self._setup_matched(tmp_path)

        rows = reconcile(bids_dir, raw_dir)

        assert rows[0]["same_task_other_sessions"] == ""

    def test_scan_notes_annotation(self, tmp_path):
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"

        _make_bold(bids_dir, "s29", "ses-01", "cuedTS")

        # Create a minimal scan notes file
        notes_path = tmp_path / "notes.md"
        notes_path.write_text(
            "### s29\n"
            "| ses-01 | 1 | cuedTS was scanned instead of spatialTS |\n"
        )

        rows = reconcile(bids_dir, raw_dir, scan_notes_path=notes_path)

        assert len(rows) == 1
        assert "cuedTS" in rows[0]["notes"]

    def test_multiple_subjects(self, tmp_path):
        bids_dir = tmp_path / "bids"
        raw_dir = tmp_path / "raw"

        _make_bold(bids_dir, "s03", "ses-01", "goNogo")
        _make_bold(bids_dir, "s10", "ses-01", "flanker")
        _make_raw_csv(raw_dir, "s03", "ses-01", "sub-s03_ses-01_task-goNogo_desc-raw.csv")
        _make_raw_csv(raw_dir, "s10", "ses-01", "sub-s10_ses-01_task-flanker_desc-raw.csv")

        rows = reconcile(bids_dir, raw_dir)

        assert len(rows) == 2
        assert all(r["status"] == "matched" for r in rows)


# ===================================================================
# Layer 5: TSV output
# ===================================================================


class TestWriteManifestTsv:
    """Tests for TSV output."""

    def test_correct_header(self, tmp_path):
        output_path = tmp_path / "manifest.tsv"
        write_manifest_tsv([], output_path)

        with open(output_path) as f:
            reader = csv.reader(f, delimiter="\t")
            header = next(reader)

        assert header == TSV_COLUMNS

    def test_correct_data(self, tmp_path):
        output_path = tmp_path / "manifest.tsv"
        rows = [
            {
                "subject": "sub-s03",
                "session": "ses-01",
                "task": "goNogo",
                "status": "matched",
                "action": "copy",
                "dest_session": "ses-01",
                "raw_path": "/some/path.csv",
                "bold_path": "/some/bold.nii.gz",
                "same_task_other_sessions": "",
                "notes": "",
            }
        ]

        write_manifest_tsv(rows, output_path)

        with open(output_path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            data_rows = list(reader)

        assert len(data_rows) == 1
        assert data_rows[0]["subject"] == "sub-s03"
        assert data_rows[0]["task"] == "goNogo"
        assert data_rows[0]["status"] == "matched"

    def test_creates_parent_dirs(self, tmp_path):
        output_path = tmp_path / "subdir" / "nested" / "manifest.tsv"
        write_manifest_tsv([], output_path)
        assert output_path.exists()

    def test_tab_delimiter(self, tmp_path):
        output_path = tmp_path / "manifest.tsv"
        rows = [
            {
                "subject": "sub-s03",
                "session": "ses-01",
                "task": "goNogo",
                "status": "matched",
                "action": "copy",
                "dest_session": "ses-01",
                "raw_path": "/path",
                "bold_path": "/bold",
                "same_task_other_sessions": "",
                "notes": "",
            }
        ]

        write_manifest_tsv(rows, output_path)

        content = output_path.read_text()
        lines = content.strip().split("\n")
        # Header should have tabs
        assert "\t" in lines[0]
        # Data row should have tabs
        assert "\t" in lines[1]
        # Columns should be correct count
        assert len(lines[0].split("\t")) == len(TSV_COLUMNS)
