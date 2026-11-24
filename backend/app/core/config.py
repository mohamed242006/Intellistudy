"""Typed settings, read from environment variables only (contract SEC-01, SEC-04, SEC-05, JWT-02).

Every secret is a ``SecretStr``: it never appears in ``repr``, logs or error messages. A local ``.env`` file is read as
a convenience for the developer's shell environment; it is git-ignored and never committed (SEC-02).

Profiles:
    ``demo``  local demonstration (default). Same secret rules as ``prod`` except that no LLM key is required.
    ``prod``  every required secret must be present and strong; interactive API docs are off (HTTP-05).
    ``test``  for the test suite only; secrets are passed in code.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Values shipped in .env.example. A secret equal to one of these is a configuration error (SEC-05).
PLACEHOLDER_SECRETS = frozenset({
    "",
    "change-me",
    "changeme",
    "replace-me",
    "replace-with-output-of-secrets.token_urlsafe-32",
    "your-api-key-here",
    "sk-your-key-here",
})

#: CORS origins approved for the local demo (2026-11-24). `*` is never allowed (HTTP-02).
DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173")

MIN_JWT_SECRET_BYTES = 32  # approved 2026-11-24: at least 32 random bytes


class Profile(StrEnum):
    DEMO = "demo"
    PROD = "prod"
    TEST = "test"


class LLMProviderName(StrEnum):
    NONE = "none"
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    LOCAL = "local"


class ConfigurationError(RuntimeError):
    """The service must not start with this configuration. The message never contains a secret value."""


def is_placeholder(secret: SecretStr | None) -> bool:
    return secret is None or secret.get_secret_value().strip().lower() in PLACEHOLDER_SECRETS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTELLISTUDY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    profile: Profile = Profile.DEMO

    # --- storage ---------------------------------------------------------------------------------------------
    database_url: str = "sqlite:///data/backend/intellistudy.sqlite3"
    data_dir: Path = Path("data/backend")
    storage_root: Path = Path("data/backend/storage")

    # --- HTTP ------------------------------------------------------------------------------------------------
    cors_origins: Annotated[tuple[str, ...], NoDecode] = DEFAULT_CORS_ORIGINS
    max_json_body_bytes: int = Field(default=64 * 1024, gt=0)  # HTTP-06
    docs_enabled: bool | None = None  # None = on in demo/test, off in prod (HTTP-05)

    # --- authentication (used from M1) -----------------------------------------------------------------------
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "intellistudy-api"
    jwt_audience: str = "intellistudy-web"
    access_token_minutes: int = Field(default=15, ge=1, le=30)  # JWT-04
    refresh_idle_days: int = Field(default=7, ge=1, le=30)  # RT-03
    refresh_absolute_days: int = Field(default=30, ge=1, le=90)
    jwt_leeway_seconds: int = Field(default=30, ge=0, le=30)  # JWT-03: at most 30 s

    # Argon2id (JWT-10): minimums are the contract floor; defaults are stronger.
    argon2_memory_kib: int = Field(default=65536, ge=19456)
    argon2_time_cost: int = Field(default=3, ge=2)
    argon2_parallelism: int = Field(default=1, ge=1, le=1)

    # login protection (JWT-13) and password policy (JWT-11)
    lockout_threshold: int = Field(default=5, ge=1)
    lockout_minutes: int = Field(default=15, ge=1)
    password_min_length: int = Field(default=10, ge=10)
    password_max_length: int = Field(default=128, ge=10, le=1024)

    # --- uploads (used from M2) ------------------------------------------------------------------------------
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, gt=0)  # UPL-02 (approved: 100 MB)
    max_pages: int = Field(default=300, gt=0)  # UPL-07
    max_files_per_request: int = Field(default=10, gt=0)  # UPL-03
    storage_quota_bytes: int = Field(default=1024**3, gt=0)  # UPL-03
    max_queued_jobs_per_user: int = Field(default=5, gt=0)  # contract 9a

    # --- ZIP container checks before parsing (UPL-05) ------------------------------------------------------------
    zip_max_uncompressed_bytes: int = Field(default=500 * 1024 * 1024, gt=0)
    zip_max_ratio: float = Field(default=100.0, gt=1)  # real corpus peaks at 54:1 (2026-11-24)
    zip_max_entries: int = Field(default=10_000, gt=0)

    # --- sandboxed parsing (UPL-08, UPL-12) ---------------------------------------------------------------------
    parse_timeout_seconds: int = Field(default=600, gt=0)  # wall clock per document
    parse_rss_limit_bytes: int = Field(default=2 * 1024**3, gt=0)  # resident memory; the watchdog kills above it
    parse_address_space_bytes: int = Field(default=8 * 1024**3, gt=0)  # coarse RLIMIT_AS ceiling (see finding F-M2-01)
    parse_max_output_bytes: int = Field(default=256 * 1024 * 1024, gt=0)  # child output is untrusted, size-bounded
    ocr_timeout_seconds: float = Field(default=30.0, gt=0)  # per image
    chunk_tokenizer: str = Field(default="hf", pattern="^(hf|approx)$")  # "approx" only for tests / offline
    worker_enabled: bool = True  # background job runner; tests drive jobs explicitly

    # --- LLM provider (contract SEC-01, SEC-07) ----------------------------------------------------------------
    llm_provider: LLMProviderName = LLMProviderName.DEEPSEEK
    llm_model: str | None = None  # None = the provider's default
    llm_base_url: str | None = None  # None = the provider's default; configuration only, never user input (SEC-07)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)  # NFR-REL-03
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    deepseek_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # ------------------------------------------------------------------------------------------- validators
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for origin in value:
            if origin == "*" or "*" in origin:
                raise ValueError("wildcard CORS origins are not allowed (contract HTTP-02)")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS origin must be an absolute http(s) origin: {origin!r}")
        return value

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        if self.profile is Profile.TEST:
            return self
        problem = jwt_secret_problem(self.jwt_secret)
        if problem:
            raise ConfigurationError(
                f"INTELLISTUDY_JWT_SECRET {problem}. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        hosted = self.llm_provider in (LLMProviderName.DEEPSEEK, LLMProviderName.OPENAI)
        if self.profile is Profile.PROD and hosted and is_placeholder(self.provider_api_key):
            raise ConfigurationError(
                f"the API key for LLM provider {self.llm_provider.value!r} is missing or a placeholder"
            )
        return self

    # ---------------------------------------------------------------------------------------------- helpers
    @property
    def provider_api_key(self) -> SecretStr | None:
        if self.llm_provider is LLMProviderName.DEEPSEEK:
            return self.deepseek_api_key
        if self.llm_provider is LLMProviderName.OPENAI:
            return self.openai_api_key
        return None

    @property
    def api_docs_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled and self.profile is not Profile.PROD
        return self.profile is not Profile.PROD

    def secret_values(self) -> list[str]:
        """Every configured secret, for log redaction (SEC-06). Never log the return value."""
        values = []
        for secret in (self.jwt_secret, self.deepseek_api_key, self.openai_api_key):
            if secret is not None and secret.get_secret_value():
                values.append(secret.get_secret_value())
        return values


def jwt_secret_problem(secret: SecretStr | None) -> str:
    """Why ``secret`` is unacceptable (empty string = acceptable). The secret value is never part of the message."""
    if secret is None:
        return "is not set"
    value = secret.get_secret_value()
    if is_placeholder(secret):
        return "is a placeholder value"
    if len(value.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        return f"is shorter than {MIN_JWT_SECRET_BYTES} bytes"
    if len(set(value)) < 8:
        return "has too little variety to be random"
    return ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings from the environment (tests build ``Settings`` directly instead)."""
    return Settings()
