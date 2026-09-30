import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("rtr_copilot")

#: TIP-012 AC-03 — every known-default/placeholder credential value that ships
#: in `.env.example` (or common vendor defaults). `APP_ENV=production` refuses
#: to boot while any catalogued secret still holds one of these values.
#: Maintain this list together with `.env.example`.
KNOWN_DEFAULT_SECRETS: frozenset[str] = frozenset({
    # .env.example shipped defaults
    "change-this-local-password",           # POSTGRES_PASSWORD / MIGRATION_DSN
    "change-this-runtime-password",         # POSTGRES_RUNTIME_PASSWORD / POSTGRES_DSN
    "change-this-local-secret",             # S3_SECRET_KEY
    "rtr-local",                            # S3_ACCESS_KEY
    "development-only-sot-signing-secret-32bytes",              # code default
    "replace-with-a-dedicated-random-secret-at-least-32-bytes",  # SOT_SIGNING_SECRET
    # common vendor/tutorial defaults that must never reach production
    "minioadmin",
    "postgres",
    "password",
    "secret",
    "changeme",
    "change-me",
    "rtr_owner_pw",
    "rtr_app_pw",
})


def _dsn_passwords(dsn: PostgresDsn) -> list[str]:
    return [
        str(host["password"])
        for host in dsn.hosts()
        if host.get("password")
    ]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: PostgresDsn
    migration_dsn: PostgresDsn | None = None
    redis_url: str = Field(pattern=r"^rediss?://")
    s3_endpoint: HttpUrl
    s3_access_key: str = Field(min_length=3)
    s3_secret_key: str = Field(min_length=8)
    s3_bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    log_level: str = "INFO"
    rtr_build_sha: str = Field(default="development", min_length=7, max_length=64)
    app_env: Literal["development", "test", "production"] = "development"
    public_base_url: HttpUrl = HttpUrl("http://127.0.0.1:3000")
    oidc_issuer: HttpUrl | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_allowed_domains: str = "rtrobotics.com,rtrobotics.me"
    oidc_group_mapping: str = "{}"
    dev_oidc_enabled: bool = True
    session_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    session_cookie_name: str = "rtr_session"
    session_cookie_secure: bool | None = None
    expected_schema_revision: str = "0015_generation_term_stats"
    sot_staging_root: Path = Path("/tmp/rtr-sot-staging")
    research_staging_root: Path = Path("/tmp/rtr-research-staging")
    sot_signing_secret: SecretStr = SecretStr(
        "development-only-sot-signing-secret-32bytes",
    )
    sot_allow_claim_as_approved: bool = False
    # TIP-014RE — real semantic embeddings. The provider default is "offline"
    # (deterministic hash stub): enabling "openai" is an explicit operator
    # decision because indexing sends corpus text and querying sends the user
    # question to the external provider. It therefore rides the SAME
    # external-export policy gate as the LLM rewrite path (key + "internal"
    # in the classification allowlist), enforced by the validator below.
    rag_embedding_provider: Literal["offline", "openai"] = "offline"
    rag_embedding_dimension: int = Field(default=1536, ge=64, le=3072)
    rag_embedding_model: str = "rtr-offline-hash-embedding"
    rag_embedding_version: str = "1"
    rag_embedding_openai_model: str = "text-embedding-3-small"
    rag_embedding_timeout_seconds: float = Field(default=8.0, ge=0.05, le=60.0)
    rag_chunk_max_chars: int = Field(default=1200, ge=128, le=8000)
    rag_chunk_overlap_chars: int = Field(default=120, ge=0, le=1000)
    rag_query_max_bytes: int = Field(default=4096, ge=64, le=32768)
    rag_candidate_limit: int = Field(default=200, ge=1, le=1000)
    rag_metadata_scan_limit: int = Field(default=5000, ge=1, le=20000)
    # Metadata carries authorization attributes, not answer content. Read it in
    # larger bounded pages than the final semantic candidate set to remove DB
    # round trips without expanding what can reach the provider.
    rag_metadata_page_size: int = Field(default=1000, ge=1, le=5000)
    rag_retrieval_timeout_ms: int = Field(default=2000, ge=100, le=10000)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_answer_candidate_k: int = Field(default=12, ge=1, le=20)
    rag_authority_candidate_k: int = Field(default=20, ge=1, le=64)
    rag_min_vector_score: float = Field(default=0.15, ge=0.0, le=1.0)
    # TIP-014RE: cosine floor above which a REAL provider embedding match is
    # accepted as relevance evidence for candidates sharing zero tokens with
    # the question. Chosen from the calibration harness distribution BEFORE
    # the confirming run (oracle scores of the semantic acceptance cases
    # 0.52/0.56 vs distractor median 0.46). Never applies to the offline
    # hash stub or degraded queries.
    rag_semantic_relevance_floor: float = Field(default=0.48, ge=0.0, le=1.0)
    rag_evidence_max_bytes: int = Field(default=16000, ge=512, le=100000)
    rag_answer_max_chars: int = Field(default=12000, ge=256, le=50000)
    # TIP-030: when True, honest-null API responses carry the internal
    # decision label (e.g. "called_answer_irrelevant") so acceptance
    # campaigns can classify refusals without database access. The label is
    # a fixed enum-like string — never evidence content. Default OFF: the
    # production surface is unchanged unless an operator opts in (e2e sets
    # RAG_EXPOSE_DECISION_DIAGNOSTICS=1 on the isolated stack only).
    rag_expose_decision_diagnostics: bool = False
    rag_provider_timeout_seconds: float = Field(default=120.0, ge=0.05, le=300.0)
    rag_provider_mode: Literal["local", "external"] = "local"
    rag_external_classification_allowlist: str = ""
    rag_external_endpoint_policy: str | None = None
    rag_external_credential_source: str | None = None
    rag_gap_routing_key: str = "curator:sot"
    # TIP-014/TIP-024.6 — LLM query planning (OpenAI quality-primary, configured
    # Anthropic fallback). It remains behind export policy
    # and credentials; without either, deterministic registry planning remains.
    rag_rewrite_enabled: bool = True
    rag_ontology_path: Path | None = None
    rag_query_candidate_limit: int = Field(default=16, ge=1, le=64)
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    rag_rewrite_anthropic_model: str = "claude-3-5-haiku-latest"
    rag_rewrite_openai_model: str = "gpt-5.6-sol"
    rag_rewrite_timeout_seconds: float = Field(default=20.0, ge=0.05, le=60.0)
    rag_rewrite_cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    rag_rewrite_cache_max_entries: int = Field(default=2048, ge=0, le=100_000)
    # TIP-024.6 quality-first grounded answering. Required mode never falls back
    # to the local extractive adapter; provider/policy failure becomes honest-null.
    rag_answer_llm_required: bool = True
    rag_answer_openai_model: str = "gpt-5.6-sol"
    rag_answer_anthropic_model: str | None = None
    # Reviewer routing is deliberately independent. A compact binary evidence
    # audit should not inherit the generator's output budget or reasoning cost.
    # ``None`` preserves same-model review unless operators approve another
    # model; deterministic grounding remains the final acceptance authority.
    rag_review_openai_model: str | None = None
    rag_answer_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max",
    ] = "high"
    # TIP-033: routine evidence-organization does not benefit from the same
    # reasoning depth as analysis/comparison. Keep it independently tunable so
    # operators can roll latency tuning back without changing the quality lane.
    rag_answer_routine_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max",
    ] = "low"
    rag_review_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max",
    ] = "low"
    # ``on_demand`` lets deterministic grounding prove ordinary candidates
    # first and spends a semantic reviewer call only for non-lexical support.
    # ``always`` is the explicit operational rollback mode.
    rag_review_mode: Literal["always", "on_demand"] = "on_demand"
    rag_answer_timeout_seconds: float = Field(default=45.0, ge=1.0, le=120.0)
    rag_answer_max_output_tokens: int = Field(default=4096, ge=256, le=32768)
    rag_review_max_output_tokens: int = Field(default=256, ge=128, le=2048)
    rag_prompt_cache_enabled: bool = True
    maintenance_mode: bool = False
    retention_policy_json: str | None = None
    backup_destination: str | None = None
    ingestion_max_upload_bytes: int = Field(default=52_428_800, ge=1_048_576)
    ingestion_max_image_pixels: int = Field(default=40_000_000, ge=1_000_000)
    ingestion_max_pdf_pages: int = Field(default=500, ge=1, le=5000)
    ingestion_max_pdf_objects: int = Field(default=100_000, ge=1000)
    ingestion_max_archive_entries: int = Field(default=5000, ge=10, le=50000)
    ingestion_max_archive_entry_bytes: int = Field(
        default=52_428_800,
        ge=1_048_576,
    )
    ingestion_max_expanded_bytes: int = Field(default=209_715_200, ge=1_048_576)
    ingestion_max_compression_ratio: int = Field(default=100, ge=2, le=1000)
    ingestion_max_cells: int = Field(default=250_000, ge=1000)
    ingestion_max_slides: int = Field(default=500, ge=1)
    ingestion_max_media_seconds: int = Field(default=14_400, ge=1)
    ingestion_max_media_width: int = Field(default=3840, ge=320, le=16384)
    ingestion_max_media_height: int = Field(default=2160, ge=240, le=16384)
    ingestion_max_sample_rate: int = Field(default=96_000, ge=8000, le=384_000)
    ingestion_tool_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    ingestion_temp_bytes: int = Field(default=524_288_000, ge=10_485_760)
    ingestion_job_max_attempts: int = Field(default=3, ge=1, le=20)
    ingestion_lease_seconds: int = Field(default=120, ge=10, le=3600)
    ingestion_retry_base_seconds: int = Field(default=5, ge=1, le=3600)
    ingestion_ocr_languages: str = "eng"
    ingestion_ocr_enabled: bool = True
    ingestion_transcript_enabled: bool = True
    ingestion_vosk_model_path: str = (
        "/opt/rtr/models/vosk-model-small-en-us-0.15"
    )
    ingestion_vosk_model_sha256: str = (
        "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"
    )
    ingestion_external_egress: bool = False
    malware_scanner_host: str = "clamav"
    malware_scanner_port: int = Field(default=3310, ge=1, le=65535)
    malware_signature_max_age_seconds: int = Field(default=172800, ge=3600)
    viewer_capability_ttl_seconds: int = Field(default=300, ge=30, le=900)
    # TIP-012 Task 2 (D-012-03) — app-layer rate limiting (Redis-backed, keyed on
    # subject id AND client IP). Deploy-time infrastructure limits enforced in
    # middleware on every request; kept out of governance_settings so the hot
    # path never depends on Postgres. Cost budgets and job caps live in
    # governance SETTING_REGISTRY (admin-editable at runtime) instead.
    limits_enabled: bool = True
    limits_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    limits_rate_auth_max: int = Field(default=20, ge=1, le=1_000_000)
    limits_rate_ask_max: int = Field(default=30, ge=1, le=1_000_000)
    limits_rate_upload_max: int = Field(default=20, ge=1, le=1_000_000)
    limits_rate_render_max: int = Field(default=30, ge=1, le=1_000_000)
    limits_rate_admin_max: int = Field(default=60, ge=1, le=1_000_000)
    limits_rate_default_read_max: int = Field(default=120, ge=1, le=1_000_000)
    # App-layer body-size limit (typed 413) for non-upload JSON bodies; keep in
    # sync with the ingress `request_body max_size` hook. Uploads use the larger
    # ingestion_max_upload_bytes bound instead.
    limits_max_body_bytes: int = Field(default=1_048_576, ge=1024, le=104_857_600)
    # Provider circuit breaker (per provider, Redis-shared state).
    limits_breaker_failure_threshold: int = Field(default=5, ge=1, le=1000)
    limits_breaker_cooldown_seconds: int = Field(default=30, ge=1, le=3600)
    # Retry-After guidance (seconds) returned with a queue_saturated rejection.
    limits_queue_retry_after_seconds: int = Field(default=15, ge=1, le=3600)
    # TIP-012 Task 3 (D-012-05) — the worker has no request HTTP app, so it
    # publishes the Prometheus registry on this dedicated port. Scraped on the
    # compose network only (never published in the hardened profile), matching
    # the api's internal-only /metrics posture.
    worker_metrics_port: int = Field(default=9100, ge=1024, le=65535)

    @field_validator("oidc_issuer", mode="before")
    @classmethod
    def empty_oidc_issuer_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("session_cookie_secure", mode="before")
    @classmethod
    def empty_session_cookie_secure_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("rag_ontology_path", mode="before")
    @classmethod
    def empty_ontology_path_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def production_identity_config(self) -> "Settings":
        if self.rag_metadata_scan_limit < self.rag_candidate_limit:
            raise ValueError("rag_metadata_scan_limit:below_candidate_limit")
        if self.rag_answer_candidate_k < self.rag_top_k:
            raise ValueError("rag_answer_candidate_k:below_rag_top_k")
        if self.rag_authority_candidate_k < self.rag_answer_candidate_k:
            raise ValueError(
                "rag_authority_candidate_k:below_rag_answer_candidate_k",
            )
        if self.rag_chunk_overlap_chars >= self.rag_chunk_max_chars:
            raise ValueError("rag_chunk_overlap_chars:must_be_below_chunk_max")
        if self.rag_embedding_provider != "offline":
            # TIP-014RE: embeddings export corpus/query text, in EVERY
            # environment. Fail loudly at construction instead of silently
            # downgrading to the offline stub — a half-configured operator
            # intent must never look like a working semantic index.
            embedding_allowlist = {
                item.strip().lower()
                for item in self.rag_external_classification_allowlist.split(",")
                if item.strip()
            }
            if (
                self.openai_api_key is None
                or "internal" not in embedding_allowlist
            ):
                raise ValueError("rag_embedding_provider:policy_required")
        if self.app_env != "production":
            return self
        if not re.fullmatch(r"[0-9a-f]{12,64}", self.rtr_build_sha):
            raise ValueError("rtr_build_sha:clean_identity_required")
        required = {
            "oidc_issuer": self.oidc_issuer,
            "oidc_client_id": self.oidc_client_id,
            "oidc_client_secret": self.oidc_client_secret,
            "public_base_url": self.public_base_url,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError("required:" + ",".join(sorted(missing)))
        if self.public_base_url.scheme != "https":
            raise ValueError("public_base_url:https_required")
        if self.oidc_issuer is not None and self.oidc_issuer.scheme != "https":
            raise ValueError("oidc_issuer:https_required")
        if self.dev_oidc_enabled:
            raise ValueError("dev_oidc_enabled:forbidden_in_production")
        if self.session_cookie_secure is False:
            raise ValueError("session_cookie_secure:required_in_production")
        if not self.allowed_domains:
            raise ValueError("oidc_allowed_domains:required_in_production")
        try:
            group_mapping = json.loads(self.oidc_group_mapping)
        except json.JSONDecodeError as error:
            raise ValueError("oidc_group_mapping:object_required") from error
        if not isinstance(group_mapping, dict):
            raise ValueError("oidc_group_mapping:object_required")
        secret_catalog: dict[str, list[str]] = {
            "postgres_dsn": _dsn_passwords(self.postgres_dsn),
            "migration_dsn": (
                _dsn_passwords(self.migration_dsn) if self.migration_dsn else []
            ),
            "redis_url": (
                [urlsplit(self.redis_url).password or ""]
                if urlsplit(self.redis_url).password
                else []
            ),
            "s3_access_key": [self.s3_access_key],
            "s3_secret_key": [self.s3_secret_key],
            "oidc_client_secret": (
                [self.oidc_client_secret] if self.oidc_client_secret else []
            ),
            "sot_signing_secret": [self.sot_signing_secret.get_secret_value()],
        }
        defaulted = sorted(
            key
            for key, values in secret_catalog.items()
            if any(value.lower() in KNOWN_DEFAULT_SECRETS for value in values)
        )
        if defaulted:
            raise ValueError("default_secret:" + ",".join(defaulted))
        signing_secret = self.sot_signing_secret.get_secret_value()
        if (
            len(signing_secret) < 32
            or signing_secret == "development-only-sot-signing-secret-32bytes"
            or signing_secret in {self.s3_secret_key, self.oidc_client_secret}
        ):
            raise ValueError("sot_signing_secret:unsafe_in_production")
        if self.rag_provider_mode == "external":
            external_allowlist = {
                item.strip().lower()
                for item in self.rag_external_classification_allowlist.split(",")
                if item.strip()
            }
            if (
                "internal" not in external_allowlist
                or not self.rag_external_endpoint_policy
                or not self.rag_external_credential_source
                or (self.openai_api_key is None and self.anthropic_api_key is None)
            ):
                raise ValueError("rag_external_provider:policy_required")
        return self

    @property
    def session_cookie_secure_effective(self) -> bool:
        """Whether session cookies carry the `Secure` attribute.

        Explicit `SESSION_COOKIE_SECURE` wins; otherwise production is always
        secure and other environments follow the public base URL scheme, so a
        dev stack served through the HTTPS ingress marks cookies `Secure`
        while the plain-HTTP dev profile keeps today's behavior.
        """
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return (
            self.app_env == "production"
            or self.public_base_url.scheme == "https"
        )

    @property
    def allowed_domains(self) -> frozenset[str]:
        return frozenset(
            domain.strip().lower()
            for domain in self.oidc_allowed_domains.split(",")
            if domain.strip()
        )


class ConfigurationError(RuntimeError):
    """Configuration is invalid without retaining secret-bearing input values."""


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        issues: list[str] = []
        for issue in error.errors(include_input=False, include_url=False):
            key = ".".join(str(part) for part in issue["loc"])
            if not key and issue["type"] == "value_error":
                reason = str(issue.get("ctx", {}).get("error", "invalid"))
                if reason.startswith("required:"):
                    issues.extend(
                        f"{item}:required"
                        for item in reason.removeprefix("required:").split(",")
                    )
                    continue
                if reason.startswith("default_secret:"):
                    issues.extend(
                        f"{item}:known_default_forbidden"
                        for item in reason.removeprefix("default_secret:").split(",")
                    )
                    continue
                if ":" in reason:
                    safe_key, safe_reason = reason.split(":", 1)
                    issues.append(f"{safe_key}:{safe_reason}")
                    continue
            issues.append(f"{key}:{issue['type']}")
        logger.error(json.dumps({
            "event": "configuration_rejected",
            "issues": sorted(issues),
        }))
        raise ConfigurationError(
            "Invalid configuration: " + ", ".join(sorted(issues)),
        ) from None
