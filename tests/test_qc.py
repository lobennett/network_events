import pandas as pd
import numpy as np
import pytest
from pathlib import Path


def _make_stop_signal_events():
    """Minimal stop signal events TSV as DataFrame."""
    return pd.DataFrame({
        "trial_id": ["test_trial"] * 10,
        "trial_type": ["go"] * 5 + ["stop_success"] * 3 + ["stop_failure"] * 2,
        "onset": [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0],
        "response_time": [0.4, 0.5, 0.45, 0.42, 0.48, "n/a", "n/a", "n/a", 0.6, 0.55],
        "acc": [1, 1, 1, 0, 1, 1, 1, 1, 0, 0],
    })


class TestRtTailCutoff:
    def test_no_cutoff_when_all_respond(self):
        from network_events.qc import detect_rt_tail_cutoff
        df = pd.DataFrame({
            "trial_id": ["test_trial"] * 5,
            "rt": [400, 500, 450, 420, 480],
        })
        result = detect_rt_tail_cutoff(df)
        assert result is None

    def test_detects_tail_cutoff(self):
        from network_events.qc import detect_rt_tail_cutoff
        # 5 good responses, then 10 non-responses
        rts = [400, 500, 450, 420, 480] + [-1] * 10
        df = pd.DataFrame({
            "trial_id": ["test_trial"] * 15,
            "rt": rts,
            "time_elapsed": list(range(1000, 16000, 1000)),
        })
        result = detect_rt_tail_cutoff(df)
        assert result is not None
        assert "cutoff_index" in result
        assert "cutoff_before_halfway" in result

    def test_cutoff_before_halfway_flags_exclude(self):
        from network_events.qc import detect_rt_tail_cutoff
        # 2 good, 10 bad -> cutoff is before halfway
        rts = [400, 500] + [-1] * 10
        df = pd.DataFrame({
            "trial_id": ["test_trial"] * 12,
            "rt": rts,
            "time_elapsed": list(range(1000, 13000, 1000)),
        })
        result = detect_rt_tail_cutoff(df)
        assert result is not None
        assert result["cutoff_before_halfway"] is True


class TestCheckStopSignalExclusion:
    def test_valid_stop_signal_not_excluded(self):
        from network_events.qc import check_stop_signal_exclusion
        # 50% stop success, go_rt < 1000ms -> valid
        metrics = {
            "stop_success_rate": 0.5,
            "go_rt": 800.0,
        }
        result = check_stop_signal_exclusion(metrics)
        assert result is None

    def test_low_stop_success_excluded(self):
        from network_events.qc import check_stop_signal_exclusion
        metrics = {
            "stop_success_rate": 0.1,  # Below 0.25 threshold
            "go_rt": 800.0,
        }
        result = check_stop_signal_exclusion(metrics)
        assert result is not None
        assert "stop_success" in result["reason"]

    def test_high_stop_success_excluded(self):
        from network_events.qc import check_stop_signal_exclusion
        metrics = {
            "stop_success_rate": 0.9,  # Above 0.75 threshold
            "go_rt": 800.0,
        }
        result = check_stop_signal_exclusion(metrics)
        assert result is not None

    def test_high_go_rt_excluded(self):
        from network_events.qc import check_stop_signal_exclusion
        metrics = {
            "stop_success_rate": 0.5,
            "go_rt": 1100.0,  # Above 1000ms threshold
        }
        result = check_stop_signal_exclusion(metrics)
        assert result is not None
        assert "go_rt" in result["reason"]


class TestCheckGoNogoExclusion:
    def test_valid_gonogo_not_excluded(self):
        from network_events.qc import check_go_nogo_exclusion
        metrics = {"go_acc": 0.9, "nogo_acc": 0.6}
        assert check_go_nogo_exclusion(metrics) is None

    def test_both_rules_triggered(self):
        from network_events.qc import check_go_nogo_exclusion
        # rule1: go <= 0.75 or nogo <= 0.2 -> nogo=0.1 triggers
        # rule2: go <= 0.5 or nogo <= 0.5  -> nogo=0.1 triggers
        metrics = {"go_acc": 0.9, "nogo_acc": 0.1}
        result = check_go_nogo_exclusion(metrics)
        assert result is not None


class TestCheckOtherExclusion:
    def test_valid_not_excluded(self):
        from network_events.qc import check_other_exclusion
        metrics = {"acc": 0.8, "omission_rate": 0.1}
        assert check_other_exclusion(metrics) is None

    def test_low_accuracy_excluded(self):
        from network_events.qc import check_other_exclusion
        metrics = {"acc": 0.4, "omission_rate": 0.1}
        result = check_other_exclusion(metrics)
        assert result is not None
        assert "accuracy" in result["reason"]

    def test_high_omission_excluded(self):
        from network_events.qc import check_other_exclusion
        metrics = {"acc": 0.8, "omission_rate": 0.35}
        result = check_other_exclusion(metrics)
        assert result is not None
        assert "omission" in result["reason"]
