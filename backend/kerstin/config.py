"""Runtime configuration, read from environment variables / .env.

Every setting has a KERSTIN_ prefix, e.g. KERSTIN_OLLAMA_MODEL.
See .env.example for the full list with comments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KERSTIN_",
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    # --- Server ---
    host: str = "127.0.0.1"  # bind to localhost; use 0.0.0.0 + TLS for LAN access
    port: int = 8770
    log_level: str = "info"

    # --- TLS (optional; created by `make certs`) ---
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None
    tls_ca_certfile: Path | None = None  # public CA cert, offered for download

    # --- LLM (Ollama) ---
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma4:26b"
    ollama_keep_alive: str = "10m"  # unload after idle so the shared GPU is freed
    ollama_max_loaded: int = 2  # mirrors OLLAMA_MAX_LOADED_MODELS; API cannot read it
    ollama_num_ctx: int = 8192
    llm_temperature: float = 0.8
    hint_temperature: float = 0.2
    llm_max_reply_tokens: int = 220  # keeps replies conversational and fast
    llm_think: bool = False  # disable reasoning mode on models that support it
    llm_seed: int | None = None  # fixed seed for benches; None = fresh random per request
    llm_warmup: bool = True  # preload the model while the opener is spoken
    history_max_turns: int = 24  # user+assistant messages kept in context

    # --- Thermal guard (D016) ---
    thermal_guard: bool = True
    thermal_hot_c: float = 80.0
    thermal_resume_c: float = 74.0

    # --- Speech-to-text ---
    # "whispercpp": whisper.cpp server (POST /inference, multipart)
    # "http": OpenAI-compatible /v1/audio/transcriptions endpoint (speaches, faster-whisper-server, ...)
    # "local": faster-whisper in-process
    stt_backend: Literal["http", "local", "whispercpp"] = "http"
    stt_url: str = "http://127.0.0.1:8000"
    stt_inference_path: str = "/inference"
    stt_model: str = "Systran/faster-whisper-large-v3"
    stt_language: str = "de"
    stt_local_device: str = "cuda"  # "cuda" or "cpu" (see docs/STATUS.md re: aarch64 wheels)
    stt_local_compute_type: str = "float16"
    stt_min_rms_dbfs: float = -55.0  # drop quieter utterances before calling STT
    stt_filter: bool = True  # drop hallucination/tag output and trim repetition loops
    early_stt: bool = True  # transcribe a draft during the VAD silence tail (D013)

    # --- Text-to-speech ---
    # "auto": Kokoro sidecar + Piper fallback; "http": alias of auto;
    # "piper": Piper only; "none": text only.
    tts_backend: Literal["auto", "http", "piper", "none"] = "auto"
    tts_voice_default: str = "kokoro-kerstin"
    piper_voice_path: Path = PROJECT_DIR / "voices" / "de_DE-thorsten-medium.onnx"
    piper_length_scale: float = 1.0  # >1.0 = slower speech
    tts_first_clause_min_words: int = 4  # speak the first clause early (0 = off)
    tts_url: str = "http://127.0.0.1:8880"

    # --- Prompts ---
    prompts_dir: Path = BACKEND_DIR / "prompts"
    default_scenario: str = "freies_gespraech"

    # --- Feedback ---
    feedback_lang: Literal["en", "de"] = "en"
    feedback_model: str | None = None  # None/empty -> ollama_model
    feedback_temperature: float = 0.3
    score_seed: int = 7

    # --- Mistake log (opt-in; categories only, never learner text) ---
    mistake_log_path: Path = PROJECT_DIR / "data" / "mistakes.sqlite3"
    mistake_log_enabled: bool = True  # server allows it; the learner opts in in the UI
    mistake_log_max_days: int = 180

    # --- Frontend ---
    frontend_dir: Path = PROJECT_DIR / "frontend"

    @field_validator(
        "piper_voice_path",
        "prompts_dir",
        "frontend_dir",
        "mistake_log_path",
        "tls_certfile",
        "tls_keyfile",
        "tls_ca_certfile",
        mode="after",
    )
    @classmethod
    def _resolve_relative(cls, v: Path | None) -> Path | None:
        # Relative paths in .env are relative to the project root, not the cwd
        if v is None:
            return None
        return v if v.is_absolute() else (PROJECT_DIR / v).resolve()

    @model_validator(mode="after")
    def _validate_tls_pair(self) -> Settings:
        if (self.tls_certfile is None) != (self.tls_keyfile is None):
            raise ValueError(
                "KERSTIN_TLS_CERTFILE and KERSTIN_TLS_KEYFILE must be set together"
            )
        return self

    @model_validator(mode="after")
    def _validate_voice_default(self) -> Settings:
        from .voices import get_voice

        if get_voice(self.tts_voice_default) is None:
            raise ValueError(
                f"KERSTIN_TTS_VOICE_DEFAULT={self.tts_voice_default!r} is not in the voice catalog"
            )
        return self

    @model_validator(mode="after")
    def _validate_thermal_thresholds(self) -> Settings:
        if self.thermal_resume_c >= self.thermal_hot_c:
            raise ValueError(
                "KERSTIN_THERMAL_RESUME_C must be lower than KERSTIN_THERMAL_HOT_C"
            )
        return self

    @property
    def tls_enabled(self) -> bool:
        return self.tls_certfile is not None and self.tls_keyfile is not None


settings = Settings()
