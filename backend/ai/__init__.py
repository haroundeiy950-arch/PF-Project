"""AI pipeline package.

Contains the object detector, tracker, optional face recognition, the demo
camera renderer, the recording engine and the per-camera worker thread.
Importing this package does **not** load any model weights; heavy imports are
performed lazily by the individual engines.
"""

from backend.ai.detector import BaseDetector, Detection, MotionDetector, YoloDetector, build_detector
from backend.ai.tracker import IouTracker, Track

__all__ = [
    "BaseDetector",
    "Detection",
    "MotionDetector",
    "YoloDetector",
    "build_detector",
    "IouTracker",
    "Track",
]
