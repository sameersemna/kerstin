import asyncio
import logging

from kerstin.thermal import ThermalGuard, ThermalStatus


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class SequenceReader:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        return self.values.pop(0)


async def test_ok_below_hot_threshold():
    guard = ThermalGuard(80, 74, read_temp=SequenceReader(79), clock=FakeClock())

    assert await guard.check() == ThermalStatus("ok", 79)


async def test_hot_at_hot_threshold():
    guard = ThermalGuard(80, 74, read_temp=SequenceReader(80), clock=FakeClock())

    assert await guard.check() == ThermalStatus("hot", 80)


async def test_stays_hot_between_thresholds():
    clock = FakeClock()
    guard = ThermalGuard(
        80, 74, read_temp=SequenceReader(80, 77), clock=clock
    )

    assert (await guard.check()).state == "hot"
    clock.now = 2.0
    assert await guard.check() == ThermalStatus("hot", 77)


async def test_ok_again_at_resume_threshold():
    clock = FakeClock()
    guard = ThermalGuard(
        80, 74, read_temp=SequenceReader(81, 74), clock=clock
    )

    assert (await guard.check()).state == "hot"
    clock.now = 2.0
    assert await guard.check() == ThermalStatus("ok", 74)


async def test_cache_is_reused_and_refreshed():
    clock = FakeClock()
    reader = SequenceReader(70, 81)
    guard = ThermalGuard(80, 74, read_temp=reader, clock=clock)

    assert await guard.check() == ThermalStatus("ok", 70)
    assert reader.calls == 1

    clock.now = 1.9
    assert await guard.check() == ThermalStatus("ok", 70)
    assert reader.calls == 1

    clock.now = 2.0
    assert await guard.check() == ThermalStatus("hot", 81)
    assert reader.calls == 2


async def test_unknown_and_warning_once(monkeypatch, caplog):
    async def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing)
    clock = FakeClock()
    guard = ThermalGuard(80, 74, clock=clock)

    with caplog.at_level(logging.WARNING, logger="kerstin.thermal"):
        assert await guard.check() == ThermalStatus("unknown", None)
        clock.now = 3.0
        assert await guard.check() == ThermalStatus("unknown", None)

    warnings = [
        record
        for record in caplog.records
        if record.name == "kerstin.thermal" and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1


async def test_default_reader_parses_temperature(monkeypatch):
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"47\n", b""

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    guard = ThermalGuard(80, 74, clock=FakeClock())

    assert await guard.check() == ThermalStatus("ok", 47)
    assert calls[0][0] == (
        "nvidia-smi",
        "--query-gpu=temperature.gpu",
        "--format=csv,noheader,nounits",
    )
    assert calls[0][1]["stdout"] is asyncio.subprocess.PIPE
    assert calls[0][1]["stderr"] is asyncio.subprocess.PIPE
