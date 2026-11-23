"""Tests for the demo renderer, tracker and bilingual voice engine."""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from backend.ai.demo import DemoScene
from backend.ai.detector import Detection
from backend.ai.tracker import IouTracker
from backend.services.voice import build_voice_messages, build_voice_text, camera_number
from backend.utils.time_utils import now


def test_demo_scene_renders_valid_frames():
    scene = DemoScene(camera_id=1, code="CAM-01")
    frame = scene.render(0.0)
    assert isinstance(frame, np.ndarray)
    assert frame.dtype == np.uint8
    assert frame.shape == (540, 960, 3)
    assert frame.std() > 5  # the synthetic scene contains real detail


def test_demo_scene_objects_are_stable_and_bounded():
    scene = DemoScene(camera_id=4, code="CAM-04")
    objects = scene.objects(10.0)
    assert objects, "every demo scene must contain moving targets"
    for item in objects:
        assert 0.0 <= item.x <= 1.0 and 0.0 <= item.y <= 1.0
        assert 0.02 < item.w < 0.6 and 0.05 < item.h < 0.6
        assert 0.0 <= item.confidence <= 1.0
        assert item.kind in {"person", "vehicle"}


def test_tracker_keeps_id_between_frames():
    tracker = IouTracker(iou_threshold=0.2)
    start = now()
    first = tracker.update(
        [Detection(bbox=[0.2, 0.3, 0.1, 0.2], target_type="person", confidence=0.9)], start
    )
    assert len(first) == 1
    track_id = first[0].id
    second = tracker.update(
        [Detection(bbox=[0.21, 0.31, 0.1, 0.2], target_type="person", confidence=0.92)],
        start + timedelta(seconds=1),
    )
    assert [track.id for track in second] == [track_id]
    assert second[0].hits == 2
    assert second[0].dwell_seconds == 1.0


def test_tracker_creates_new_track_for_distant_object():
    tracker = IouTracker(iou_threshold=0.5)
    start = now()
    tracker.update([Detection(bbox=[0.1, 0.1, 0.1, 0.2], confidence=0.9)], start)
    tracks = tracker.update(
        [Detection(bbox=[0.7, 0.7, 0.1, 0.2], confidence=0.9)], start + timedelta(seconds=1)
    )
    assert len(tracks) == 1  # only the matched track is "active" this frame
    assert set(tracker.tracks) == {"T-0001", "T-0002"}


def test_tracker_drops_stale_tracks():
    tracker = IouTracker(max_misses=2)
    start = now()
    tracker.update([Detection(bbox=[0.2, 0.2, 0.1, 0.2], confidence=0.9)], start)
    for offset in range(1, 5):
        active = tracker.update([], start + timedelta(seconds=offset))
        assert active == []
    assert tracker.tracks == {}


def test_voice_messages_are_bilingual_and_auditable():
    messages = build_voice_messages("restricted_intrusion", "Vault Access Corridor", "CAM-04")
    assert [message["language"] for message in messages] == ["en", "ar"]
    assert "WARNING" in messages[0]["text"]
    assert "CAM" not in messages[0]["text"]
    assert "04" in messages[0]["text"]
    assert messages[1]["voice"] == "ar-SA"
    assert "\u062a\u062d\u0630\u064a\u0631" in messages[1]["text"]  # Arabic "warning"


def test_voice_fallback_for_unknown_type_and_language():
    text = build_voice_text("not-a-threat", "Gate", "CAM-01", language="ar")
    assert text
    assert camera_number("CAM-07") == "07"
    assert camera_number("") == "1"
