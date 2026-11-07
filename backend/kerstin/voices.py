"""Selectable voice catalog. The engine names are the contract with Piper/Kokoro."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    label: str
    engine: str
    engine_voice: str


VOICES = (
    VoiceInfo("kokoro-kerstin", "Kerstin (Kokoro)", "kokoro", "kerstin"),
    VoiceInfo("kokoro-thorsten", "Thorsten (Kokoro)", "kokoro", "thorsten"),
    VoiceInfo("piper-thorsten", "Thorsten (Piper)", "piper", ""),
)
BY_ID = {voice.id: voice for voice in VOICES}


def get_voice(voice_id: str) -> VoiceInfo | None:
    return BY_ID.get(voice_id)


def catalog_for_backend(backend: str) -> tuple[VoiceInfo, ...]:
    if backend == "piper":
        return tuple(voice for voice in VOICES if voice.engine == "piper")
    return VOICES


def default_voice_id(backend: str, configured: str) -> str:
    allowed = catalog_for_backend(backend)
    if backend == "piper":
        return allowed[0].id
    if get_voice(configured) in allowed:
        return configured
    raise ValueError(f"unknown voice default {configured!r}")


def resolve_voice(
    requested: str | None, backend: str, configured: str
) -> VoiceInfo:
    allowed = catalog_for_backend(backend)
    if requested:
        voice = get_voice(requested)
        if voice in allowed:
            return voice
    default = default_voice_id(backend, configured)
    return get_voice(default) or allowed[0]
