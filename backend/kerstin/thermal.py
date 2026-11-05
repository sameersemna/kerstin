"""Read-only GPU thermal admission control (D016)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)

NVIDIA_SMI_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class ThermalStatus:
    state: Literal["ok", "hot", "unknown"]
    temp_c: float | None


class ThermalGuard:
    def __init__(
        self,
        hot_c: float,
        resume_c: float,
        max_age_s: float = 2.0,
        read_temp: Callable[[], Awaitable[float | None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.hot_c = hot_c
        self.resume_c = resume_c
        self.max_age_s = max_age_s
        self._read_temp = read_temp or self._read_nvidia_smi
        self._clock = clock
        self._cached_temp: float | None = None
        self._last_read_at: float | None = None
        self._hot = False
        self._last_state: str | None = None
        self._warned = False

    async def check(self) -> ThermalStatus:
        now = self._clock()
        if self._last_read_at is None or now - self._last_read_at >= self.max_age_s:
            self._cached_temp = await self._read_temp()
            self._last_read_at = self._clock()

        status = self._evaluate(self._cached_temp)
        self._log_change(status)
        return status

    def _evaluate(self, temp: float | None) -> ThermalStatus:
        if temp is None:
            state = "unknown"
        elif self._hot:
            if temp <= self.resume_c:
                self._hot = False
                state = "ok"
            else:
                state = "hot"
        elif temp >= self.hot_c:
            self._hot = True
            state = "hot"
        else:
            state = "ok"
        return ThermalStatus(state=state, temp_c=temp)

    def _log_change(self, status: ThermalStatus) -> None:
        if status.state == self._last_state:
            return
        self._last_state = status.state
        if status.temp_c is None:
            log.info("thermal state %s (gpu=n/a)", status.state)
        else:
            log.info("thermal state %s (gpu=%g °C)", status.state, status.temp_c)

    def _warn_once(self) -> None:
        if self._warned:
            return
        self._warned = True
        log.warning("cannot read GPU temperature; thermal guard is fail-open")

    async def _read_nvidia_smi(self) -> float | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            self._warn_once()
            return None

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=NVIDIA_SMI_TIMEOUT_S
            )
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            self._warn_once()
            return None
        except OSError:
            self._warn_once()
            return None

        if proc.returncode != 0:
            self._warn_once()
            return None

        lines = stdout.decode("utf-8", errors="replace").splitlines()
        if not lines:
            self._warn_once()
            return None

        try:
            return float(lines[0].strip())
        except ValueError:
            self._warn_once()
            return None
