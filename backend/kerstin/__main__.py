"""`python -m kerstin` — start the server with host/port from settings (.env)."""

from __future__ import annotations

import socket
import sys

import uvicorn

from .config import Settings, settings

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def uvicorn_kwargs(s: Settings) -> dict:
    """Uvicorn options; TLS only adds the cert/key paths."""
    kwargs: dict = {"host": s.host, "port": s.port, "log_level": s.log_level}
    if s.tls_enabled:
        kwargs["ssl_certfile"] = str(s.tls_certfile)
        kwargs["ssl_keyfile"] = str(s.tls_keyfile)
    return kwargs


def _urls(s: Settings) -> list[str]:
    scheme = "https" if s.tls_enabled else "http"
    if s.tls_enabled and s.host not in LOOPBACK_HOSTS:
        hostname = socket.gethostname().split(".")[0]
        return [
            f"{scheme}://{hostname}.local:{s.port}",
            f"{scheme}://localhost:{s.port}",
        ]
    return [f"{scheme}://localhost:{s.port}"]


def _check_tls_files(s: Settings) -> None:
    if not s.tls_enabled:
        return
    missing = [p for p in (s.tls_certfile, s.tls_keyfile) if not p.exists()]
    if missing:
        files = ", ".join(str(p) for p in missing)
        print(
            f"TLS is enabled but these files are missing: {files}\n"
            "Run `make certs` to create the local CA and server certificate.",
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    _check_tls_files(settings)
    for url in _urls(settings):
        print(f"Kerstin: open {url}", flush=True)
    uvicorn.run("kerstin.main:app", **uvicorn_kwargs(settings))
