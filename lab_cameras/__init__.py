"""Single-owner camera access for the lab host.

    from lab_cameras import CameraOwner
    with CameraOwner(mode="vision") as cams:
        frame = cams.latest("workspace")

RULE: no code outside this package may call `cv2.VideoCapture` on `/dev/cam_*`.
That rule, not the architecture, is what prevents a stray YUYV open from hanging
the Innomaker and dragging the C922 through a USB reset with it.
"""

from lab_cameras.owner import (  # noqa: F401
    DEFAULT_CAMERAS,
    CameraLock,
    CameraOwner,
    CamerasBusy,
    CameraStats,
    Frame,
    LabCameraError,
    read_session,
    who_owns,
)

__all__ = [
    "CameraLock",
    "CameraOwner",
    "CamerasBusy",
    "CameraStats",
    "DEFAULT_CAMERAS",
    "Frame",
    "LabCameraError",
    "read_session",
    "who_owns",
]
