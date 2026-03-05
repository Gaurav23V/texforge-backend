import time

from app.timing import TimingRecorder


def test_timing_recorder_collects_stage_durations():
    timings = TimingRecorder()

    with timings.stage("fetch"):
        time.sleep(0.005)
    with timings.stage("compile"):
        time.sleep(0.005)

    data = timings.as_ms()
    assert data["fetch_ms"] >= 4
    assert data["compile_ms"] >= 4
    assert data["total_ms"] >= data["fetch_ms"] + data["compile_ms"]


def test_timing_recorder_manual_duration():
    timings = TimingRecorder()
    timings.set_duration("queue_wait", 0.01)
    timings.add_duration("queue_wait", 0.01)
    data = timings.as_ms()
    assert data["queue_wait_ms"] >= 20
