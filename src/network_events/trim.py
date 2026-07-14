"""Trim NIfTIs to match behavioral cutoff."""
import json
import logging
import math
import re
from pathlib import Path

log = logging.getLogger(__name__)


def calculate_volume_cutoff(onset_cutoff_ms: float, tr_seconds: float) -> int:
    """Calculate number of volumes to keep based on onset cutoff time."""
    onset_seconds = onset_cutoff_ms / 1000.0
    return math.floor(onset_seconds / tr_seconds)


def trim_nifti(
    nifti_in: Path,
    nifti_out: Path,
    n_volumes: int,
    json_in: Path | None = None,
    json_out: Path | None = None,
) -> None:
    """Truncate a 4D NIfTI to n_volumes and optionally patch JSON sidecar."""
    import nibabel as nib

    img = nib.load(str(nifti_in))
    trimmed_img = img.slicer[:, :, :, :n_volumes]
    nifti_out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: temp file + rename to avoid corrupt output if killed mid-write
    tmp_path = nifti_out.parent / nifti_out.name.replace(".nii.gz", "_tmp.nii.gz")
    nib.save(trimmed_img, str(tmp_path))
    tmp_path.rename(nifti_out)
    log.info("Trimmed %s -> %s (%d volumes)", nifti_in.name, nifti_out.name, n_volumes)

    if json_in is not None and json_out is not None and json_in.exists():
        sidecar = json.loads(json_in.read_text())
        if "NumVolumes" in sidecar:
            sidecar["NumVolumes"] = n_volumes
        json_out.write_text(json.dumps(sidecar, indent=2))


def run_trim(bids_dir: Path) -> None:
    """Trim NIfTIs based on trim_list.json from behavioral QC.

    Reads: {bids_dir}/sourcedata/behavioral_qc/trim_list.json
    Writes: {bids_dir}/derivatives/trimmed/sub-*/ses-*/func/*_desc-trimmed_bold.nii.gz
    """
    trim_list_path = bids_dir / "sourcedata" / "behavioral_qc" / "trim_list.json"
    if not trim_list_path.exists():
        log.warning("No trim list found at %s", trim_list_path)
        return

    trim_list = json.loads(trim_list_path.read_text())
    if not trim_list:
        log.info("Trim list is empty, nothing to do")
        return

    deriv_dir = bids_dir / "derivatives" / "trimmed"

    for entry in trim_list:
        subject = entry["subject"]
        session = entry["session"]
        task = entry["task"]
        cutoff_ms = entry["cutoff_onset_ms"]

        func_dir = bids_dir / subject / session / "func"
        if not func_dir.exists():
            log.warning("No func dir for %s %s", subject, session)
            continue

        # Find matching NIfTIs
        pattern = f"{subject}_{session}_task-{task}_*_bold.nii.gz"
        niftis = sorted(func_dir.glob(pattern))
        if not niftis:
            # Try without run entity
            pattern = f"{subject}_{session}_task-{task}_bold.nii.gz"
            niftis = sorted(func_dir.glob(pattern))

        for nifti_path in niftis:
            # Get TR from JSON sidecar
            json_path = Path(str(nifti_path).replace(".nii.gz", ".json"))
            if not json_path.exists():
                log.warning("No JSON sidecar for %s, skipping", nifti_path)
                continue

            sidecar = json.loads(json_path.read_text())
            tr = sidecar.get("RepetitionTime")
            if tr is None:
                log.warning("No RepetitionTime in %s, skipping", json_path)
                continue

            n_volumes = calculate_volume_cutoff(cutoff_ms, tr)

            # Build output path with desc-trimmed entity
            out_name = re.sub(r"_bold\.nii\.gz$", "_desc-trimmed_bold.nii.gz", nifti_path.name)
            out_path = deriv_dir / subject / session / "func" / out_name
            out_json = Path(str(out_path).replace(".nii.gz", ".json"))

            trim_nifti(nifti_path, out_path, n_volumes, json_in=json_path, json_out=out_json)

    log.info("Trimming complete: processed %d entries", len(trim_list))
