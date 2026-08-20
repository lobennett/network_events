"""Scan-length truncation + its trial-retention metric.

When a run is aborted at the scanner the behavioural session keeps going, so the CSV
describes trials that were never imaged. Left alone, a first-level model builds
regressors for timepoints that do not exist. So:

  * ``create_events_df`` CLIPS onsets to the acquired scan length. Always applied --
    a data-integrity fix, mirroring the non-monotonic truncation.
  * ``events_truncation_stats`` MEASURES what the clip cost, under ``scan_*`` keys.
    Whether the surviving run is worth modelling is ``network_qa``'s call.

Scan length is read from the NIfTI, not the sidecar: ``NumberOfTemporalPositions``
records the intended volume count, so an aborted run reports a length it never reached.
"""
import nibabel as nib
import numpy as np

from tests.test_nonmonotonic import _make_flanker_csv


def _write_bold(path, n_volumes, tr=1.49):
    """A minimal 4-D NIfTI with a real TR in its header."""
    img = nib.Nifti1Image(np.zeros((2, 2, 2, n_volumes), dtype=np.int16), np.eye(4))
    img.header.set_zooms((1.0, 1.0, 1.0, tr))
    nib.save(img, path)
    return path


class TestAcquiredDuration:
    def test_reads_volumes_times_tr(self, tmp_path):
        from network_events.create import acquired_duration

        _write_bold(tmp_path / "sub-s01_ses-01_task-flanker_run-1_bold.nii.gz", 100)
        # The header stores the TR as float32, so compare approximately.
        got = acquired_duration(tmp_path, "sub-s01", "ses-01", "flanker", 1)
        assert abs(got - 149.0) < 1e-4

    def test_matches_multiecho_names(self, tmp_path):
        from network_events.create import acquired_duration

        _write_bold(
            tmp_path / "sub-s01_ses-01_task-flanker_run-1_echo-1_bold.nii.gz", 50)
        got = acquired_duration(tmp_path, "sub-s01", "ses-01", "flanker", 1)
        assert abs(got - 74.5) < 1e-4

    def test_missing_or_unreadable_returns_none(self, tmp_path):
        from network_events.create import acquired_duration

        assert acquired_duration(tmp_path, "sub-s01", "ses-01", "flanker", 1) is None
        (tmp_path / "sub-s01_ses-01_task-flanker_run-1_bold.nii.gz").touch()
        assert acquired_duration(tmp_path, "sub-s01", "ses-01", "flanker", 1) is None


class TestCreateEventsClips:
    def test_events_past_scan_end_are_dropped(self, tmp_path):
        from network_events.create import create_events_df

        # 40 trials at 3 s from 20 s -> last onset 137 s. A 60 s scan keeps 14.
        csv = _make_flanker_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv", n_trials=40)
        ev = create_events_df(csv, "flanker", scan_s=60.0)
        assert (ev["trial_id"] == "test_trial").sum() == 14
        assert ev["onset"].max() < 60.0

    def test_scan_longer_than_task_drops_nothing(self, tmp_path):
        from network_events.create import create_events_df

        csv = _make_flanker_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv", n_trials=20)
        full = create_events_df(csv, "flanker")
        clipped = create_events_df(csv, "flanker", scan_s=1000.0)
        assert len(clipped) == len(full)

    def test_none_disables_clipping(self, tmp_path):
        from network_events.create import create_events_df

        csv = _make_flanker_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv", n_trials=40)
        assert len(create_events_df(csv, "flanker", scan_s=None)) == \
            len(create_events_df(csv, "flanker"))


class TestScanStatsRecorded:
    def test_stats_report_the_clip(self, tmp_path):
        from network_events.create import events_truncation_stats

        csv = _make_flanker_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv", n_trials=40)
        stats = events_truncation_stats(csv, "flanker", scan_s=60.0)
        assert stats["scan_duration_s"] == 60.0
        assert stats["scan_test_dropped"] == 26
        assert abs(stats["fraction_scan_test_dropped"] - 26 / 40) < 1e-9
        # The non-monotonic metrics are untouched by clipping.
        assert stats["cut"] is None
        assert stats["n_test_dropped"] == 0

    def test_no_scan_length_reports_no_loss(self, tmp_path):
        from network_events.create import events_truncation_stats

        csv = _make_flanker_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv", n_trials=20)
        stats = events_truncation_stats(csv, "flanker")
        assert stats["scan_duration_s"] is None
        assert stats["scan_rows_dropped"] == 0
        assert stats["fraction_scan_test_dropped"] == 0.0


class TestEndToEnd:
    def test_run_create_events_clips_against_the_real_nifti(self, tmp_path):
        from network_events.create import run_create_events

        beh = tmp_path / "sourcedata" / "sub-s01" / "ses-01" / "beh"
        beh.mkdir(parents=True)
        _make_flanker_csv(beh / "sub-s01_ses-01_task-flanker_beh.csv", n_trials=40)
        func = tmp_path / "sub-s01" / "ses-01" / "func"
        func.mkdir(parents=True)
        # 40 volumes x 1.49 s = 59.6 s of scan against 137 s of task.
        _write_bold(func / "sub-s01_ses-01_task-flanker_run-1_bold.nii.gz", 40)

        run_create_events(behavioral_dir=tmp_path / "sourcedata", bids_dir=tmp_path)

        import pandas as pd
        ev = pd.read_csv(
            func / "sub-s01_ses-01_task-flanker_run-1_events.tsv", sep="\t")
        assert ev["onset"].max() < 59.6
        assert (ev["trial_id"] == "test_trial").sum() == 14
