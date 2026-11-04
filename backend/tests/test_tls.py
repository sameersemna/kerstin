"""TLS configuration, uvicorn kwargs and CA download tests (no network/crypto)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import kerstin.main as main_module
from kerstin.__main__ import uvicorn_kwargs
from kerstin.config import Settings

CA_PEM = "-----BEGIN CERTIFICATE-----\nMIIBdummy\n-----END CERTIFICATE-----\n"


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_tls_certfile_and_keyfile_must_be_set_together(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        make_settings(tls_certfile=tmp_path / "kerstin.crt")
    with pytest.raises(ValidationError):
        make_settings(tls_keyfile=tmp_path / "kerstin.key")


def test_tls_enabled_property(tmp_path: Path) -> None:
    assert make_settings().tls_enabled is False
    s = make_settings(tls_certfile=tmp_path / "kerstin.crt", tls_keyfile=tmp_path / "kerstin.key")
    assert s.tls_enabled is True


def test_uvicorn_kwargs_without_tls() -> None:
    assert uvicorn_kwargs(make_settings()) == {
        "host": "127.0.0.1",
        "port": 8770,
        "log_level": "info",
    }


def test_uvicorn_kwargs_with_tls(tmp_path: Path) -> None:
    cert = tmp_path / "kerstin.crt"
    key = tmp_path / "kerstin.key"
    cert.write_text("cert")
    key.write_text("key")
    kwargs = uvicorn_kwargs(make_settings(tls_certfile=cert, tls_keyfile=key))
    assert kwargs["ssl_certfile"] == str(cert)
    assert kwargs["ssl_keyfile"] == str(key)


def make_client(monkeypatch, ca_path: Path | None) -> TestClient:
    monkeypatch.setattr(main_module, "settings", make_settings(tls_ca_certfile=ca_path))
    return TestClient(main_module.app)


def test_ca_cert_404_when_unset(monkeypatch) -> None:
    client = make_client(monkeypatch, None)
    assert client.get("/kerstin-ca.crt").status_code == 404


def test_ca_cert_is_served(monkeypatch, tmp_path: Path) -> None:
    ca_path = tmp_path / "kerstin-ca.crt"
    ca_path.write_text(CA_PEM)
    client = make_client(monkeypatch, ca_path)
    response = client.get("/kerstin-ca.crt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-x509-ca-cert")
    assert response.text == CA_PEM


def test_ca_cert_refuses_private_key(monkeypatch, tmp_path: Path) -> None:
    ca_path = tmp_path / "kerstin-ca.crt"
    ca_path.write_text("-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n")
    client = make_client(monkeypatch, ca_path)
    assert client.get("/kerstin-ca.crt").status_code == 500
