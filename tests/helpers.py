"""Real BOLD timing evidence and the canonical audited conversion test seam."""
import json

import nibabel as nib
import numpy as np

from network_events.create import create_events
from network_events.identity import audit_dataset


def write_bold(path, n_volumes=100, tr=1.49, discarded=7):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = nib.Nifti1Image(np.zeros((2, 2, 2, n_volumes), dtype=np.int16), np.eye(4))
    img.header.set_zooms((1.0, 1.0, 1.0, tr))
    img.header.set_xyzt_units('mm', 'sec')
    nib.save(img, path)
    sidecar = path.with_name(path.name.split('.nii')[0] + '.json')
    sidecar.write_text(json.dumps({
        'NumberOfVolumesDiscardedByUser': discarded, 'RepetitionTime': tr,
    }))
    return path


def audited_create(bids, behavior=None):
    audit = audit_dataset(bids, behavior or bids / 'sourcedata' / 'behavioral')
    assert audit.errors == ()
    return create_events(bids, audit.pairs)
