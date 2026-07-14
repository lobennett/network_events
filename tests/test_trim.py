import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np


class TestCalculateVolumeCutoff:
    def test_basic_calculation(self):
        from network_events.trim import calculate_volume_cutoff
        # onset_cutoff=10000ms, TR=2000ms -> 5 volumes
        assert calculate_volume_cutoff(10000.0, 2.0) == 5

    def test_rounds_down(self):
        from network_events.trim import calculate_volume_cutoff
        # onset_cutoff=11000ms, TR=2000ms -> floor(5.5) = 5
        assert calculate_volume_cutoff(11000.0, 2.0) == 5


class TestTrimNifti:
    def test_trims_to_correct_volumes(self, tmp_path):
        from network_events.trim import trim_nifti
        import nibabel as nib

        # Create a fake 4D NIfTI with 10 volumes
        data = np.random.rand(2, 2, 2, 10).astype(np.float32)
        img = nib.Nifti1Image(data, np.eye(4))
        nifti_path = tmp_path / "bold.nii.gz"
        nib.save(img, str(nifti_path))

        # Also create a JSON sidecar
        sidecar = {"RepetitionTime": 2.0, "NumVolumes": 10}
        json_path = tmp_path / "bold.json"
        json_path.write_text(json.dumps(sidecar))

        out_nifti = tmp_path / "out" / "bold_trimmed.nii.gz"
        out_json = tmp_path / "out" / "bold_trimmed.json"
        out_nifti.parent.mkdir(parents=True)

        trim_nifti(nifti_path, out_nifti, n_volumes=7)

        trimmed = nib.load(str(out_nifti))
        assert trimmed.shape[-1] == 7

    def test_patches_json_sidecar(self, tmp_path):
        from network_events.trim import trim_nifti
        import nibabel as nib

        data = np.random.rand(2, 2, 2, 10).astype(np.float32)
        img = nib.Nifti1Image(data, np.eye(4))
        nifti_path = tmp_path / "bold.nii.gz"
        nib.save(img, str(nifti_path))

        sidecar = {"RepetitionTime": 2.0, "NumVolumes": 10}
        json_path = tmp_path / "bold.json"
        json_path.write_text(json.dumps(sidecar))

        out_nifti = tmp_path / "out" / "bold_trimmed.nii.gz"
        out_json = tmp_path / "out" / "bold_trimmed.json"
        out_nifti.parent.mkdir(parents=True)

        trim_nifti(nifti_path, out_nifti, n_volumes=7, json_in=json_path, json_out=out_json)

        patched = json.loads(out_json.read_text())
        assert patched["NumVolumes"] == 7
