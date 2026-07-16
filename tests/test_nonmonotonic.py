"""Non-monotonic onset truncation + trial-retention metric.

A raw jsPsych ``time_elapsed`` clock glitch (a backward jump) produces an
``events.tsv`` whose onsets step backward once. Trials after the jump have
unreliable absolute timing, so:

  * ``create_events_df`` TRUNCATES the events at the first non-monotonic onset
    (keeps the clean monotonic prefix). Always applied -- a data-integrity fix,
    not a policy decision.
  * ``events_truncation_stats`` / the ``_events.json`` sidecar written by
    ``run_create_events`` MEASURE how many test trials that truncation dropped.
    Deciding whether that loss is small enough to keep the run is
    ``network_qa``'s job, not this package's -- no threshold is applied here.

Mirrors neuro_workflow's tests/events/test_nonmonotonic.py (the monolith that
generated the canonical dataset), minus the run_qc exclusion-decision tests
(that policy now lives in network_qa).
"""
import json

import numpy as np
import pandas as pd

from network_events.config import N_DUMMY, TR_SECONDS

# --- pure cut-finder -------------------------------------------------------


class TestFindNonmonotonicCut:
    def test_monotonic_returns_none(self):
        from network_events.utils import find_nonmonotonic_cut

        assert find_nonmonotonic_cut([1.0, 2.0, 3.0, 4.0]) is None

    def test_equal_onsets_allowed(self):
        from network_events.utils import find_nonmonotonic_cut

        assert find_nonmonotonic_cut([1.0, 1.0, 2.0, 2.0]) is None

    def test_first_backward_step_index(self):
        from network_events.utils import find_nonmonotonic_cut

        # 3.0 -> 2.5 at position 3 is the first decrease
        assert find_nonmonotonic_cut([1.0, 2.0, 3.0, 2.5, 3.5]) == 3

    def test_empty_and_single(self):
        from network_events.utils import find_nonmonotonic_cut

        assert find_nonmonotonic_cut([]) is None
        assert find_nonmonotonic_cut([5.0]) is None


# --- truncation stats on a built df ---------------------------------------


class TestNonmonotonicTruncation:
    def test_drops_backward_tail_counts_test_trials(self):
        from network_events.create import _nonmonotonic_truncation

        df = pd.DataFrame(
            {
                "onset": [1.0, 2.0, 3.0, 2.5, 3.5],
                "trial_id": [
                    "test_trial",
                    "test_fixation",
                    "test_trial",
                    "test_trial",
                    "test_trial",
                ],
            }
        )
        cut, n_total, n_dropped = _nonmonotonic_truncation(df)
        assert cut == 3
        assert n_total == 4  # four test_trial rows total
        assert n_dropped == 2  # rows 3,4 are test_trial

    def test_monotonic_no_cut(self):
        from network_events.create import _nonmonotonic_truncation

        df = pd.DataFrame(
            {
                "onset": [1.0, 2.0, 3.0],
                "trial_id": ["test_trial"] * 3,
            }
        )
        cut, n_total, n_dropped = _nonmonotonic_truncation(df)
        assert cut is None and n_total == 3 and n_dropped == 0


# --- end-to-end through the real events pipeline --------------------------

_DUMMY_OFFSET_MS = N_DUMMY * TR_SECONDS * 1000.0
_TRIGGER_TIME_MS = 60000.0
_BLOCK_DURATION_MS = 1500.0
_KEY_H = 89.0


def _te(onset_s: float) -> float:
    """Plant time_elapsed so create_events_df recovers events onset ``onset_s``."""
    return _TRIGGER_TIME_MS + _BLOCK_DURATION_MS + _DUMMY_OFFSET_MS + onset_s * 1000.0


def _make_flanker_csv(path, *, n_trials, iti=3.0, first_onset=20.0):
    """Synthesize a minimal raw flanker CSV with monotonic, well-spaced onsets."""
    rows = [
        {
            "trial_id": "fmri_trigger_initial",
            "time_elapsed": _TRIGGER_TIME_MS,
            "block_duration": 100.0,
            "rt": 0,
            "key_press": -1,
            "correct_response": -1,
            "stim_duration": 0,
            "exp_id": "flanker_single_task_network__fmri",
            "flanker_condition": np.nan,
            "center_letter": np.nan,
        }
    ]
    for i in range(n_trials):
        onset_s = first_onset + i * iti
        rows.append(
            {
                "trial_id": "test_trial",
                "time_elapsed": _te(onset_s),
                "block_duration": _BLOCK_DURATION_MS,
                "rt": 450 if i % 2 == 0 else -1,
                "key_press": _KEY_H if i % 2 == 0 else -1,
                "correct_response": _KEY_H,
                "stim_duration": 1500,
                "exp_id": "flanker_single_task_network__fmri",
                "flanker_condition": "congruent" if i % 2 == 0 else "incongruent",
                "center_letter": "H",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _make_backward_jump_csv(path, *, n_trials, jump_after_test_trial, offset_ms=12000.0):
    """Synth a flanker CSV, then shift ``time_elapsed`` of the tail backward.

    The shift starts at the (``jump_after_test_trial``+1)-th test trial, so the
    recovered onsets step backward exactly once there.
    """
    _make_flanker_csv(path, n_trials=n_trials, iti=3.0)
    df = pd.read_csv(path)
    test_pos = df.index[df["trial_id"] == "test_trial"].tolist()
    cut_raw_idx = test_pos[jump_after_test_trial]
    df.loc[df.index >= cut_raw_idx, "time_elapsed"] = (
        df.loc[df.index >= cut_raw_idx, "time_elapsed"] - offset_ms
    )
    df.to_csv(path, index=False)
    return path


class TestCreateEventsTruncates:
    def test_backward_jump_yields_monotonic_truncated_events(self, tmp_path):
        from network_events.create import create_events_df

        csv = _make_backward_jump_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv",
            n_trials=40,
            jump_after_test_trial=34,  # ~15% of trials past the jump
        )
        ev = create_events_df(csv, "flanker")
        assert ev["onset"].is_monotonic_increasing
        # tail (post-jump) trials were dropped, so fewer test trials remain
        assert (ev["trial_id"] == "test_trial").sum() < 40


class TestTruncationStatsRecorded:
    def test_stats_match_dropped_trials(self, tmp_path):
        from network_events.create import events_truncation_stats

        csv = _make_backward_jump_csv(
            tmp_path / "sub-s01_ses-01_task-flanker_beh.csv",
            n_trials=40,
            jump_after_test_trial=12,  # 28/40 = 70% dropped
        )
        stats = events_truncation_stats(csv, "flanker")
        assert stats["cut"] is not None
        assert stats["n_test_total"] == 40
        assert stats["n_test_dropped"] == 28
        assert abs(stats["fraction_test_dropped"] - 0.7) < 1e-9

    def test_sidecar_json_surfaces_metric(self, tmp_path):
        """run_create_events writes a truncation-QC sidecar network_qa can read.

        The sidecar lives OUT of func/ -- under sourcedata/events_qc/ with a
        non-reserved ``_desc-truncation.json`` name -- so bids-validator does
        not reject it (``_events.json`` in func/ is reserved for events-column
        descriptions). No ``_events.json`` is written into func/.
        """
        from network_events.create import run_create_events

        beh = tmp_path / "sourcedata" / "sub-s01" / "ses-01" / "beh"
        beh.mkdir(parents=True)
        _make_backward_jump_csv(
            beh / "sub-s01_ses-01_task-flanker_beh.csv",
            n_trials=40,
            jump_after_test_trial=12,
        )
        func_dir = tmp_path / "sub-s01" / "ses-01" / "func"
        func_dir.mkdir(parents=True)
        (func_dir / "sub-s01_ses-01_task-flanker_run-1_bold.nii.gz").touch()

        run_create_events(behavioral_dir=tmp_path / "sourcedata", bids_dir=tmp_path)

        events_tsv = func_dir / "sub-s01_ses-01_task-flanker_run-1_events.tsv"
        assert events_tsv.exists()
        # No reserved _events.json sidecar leaks into func/
        assert not (func_dir / "sub-s01_ses-01_task-flanker_run-1_events.json").exists()

        sidecar_path = (
            tmp_path / "sourcedata" / "events_qc" / "sub-s01" / "ses-01"
            / "sub-s01_ses-01_task-flanker_run-1_desc-truncation.json"
        )
        assert sidecar_path.exists()
        sidecar = json.loads(sidecar_path.read_text())
        assert sidecar["NTestTrialsExpected"] == 40
        assert sidecar["NTestTrialsRetained"] == 12
        assert abs(sidecar["FractionTestTrialsDropped"] - 0.7) < 1e-9


class TestNoTruncationWhenMonotonic:
    def test_monotonic_csv_drops_nothing(self, tmp_path):
        from network_events.create import create_events_df, events_truncation_stats

        csv = _make_flanker_csv(
            tmp_path / "sub-s02_ses-01_task-flanker_beh.csv", n_trials=20
        )
        ev = create_events_df(csv, "flanker")
        assert ev["onset"].is_monotonic_increasing
        assert (ev["trial_id"] == "test_trial").sum() == 20

        stats = events_truncation_stats(csv, "flanker")
        assert stats["cut"] is None
        assert stats["n_test_total"] == 20
        assert stats["n_test_dropped"] == 0
        assert stats["fraction_test_dropped"] == 0.0
