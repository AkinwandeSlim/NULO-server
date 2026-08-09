"""
PropFlow Configuration
Environment-specific settings for Qwen, Mem0, and Alibaba Cloud OSS
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class PropFlowSettings(BaseSettings):
    """PropFlow AI Agent Settings — loaded from server/.env"""

    # ── Qwen API (Alibaba Cloud DashScope) ───────────────────────────────────
    QWEN_API_KEY: str | None = None
    QWEN_API_URL: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    # Primary model: qwen-plus gives better structured output than qwen-turbo
    # for intent extraction; falls back to qwen-turbo if quota exceeded
    QWEN_MODEL: str = "qwen-plus"
    QWEN_FALLBACK_MODEL: str = "qwen-turbo"
    QWEN_TEMPERATURE: float = 0.1   # Low = deterministic, good for JSON extraction
    QWEN_MAX_TOKENS: int = 1000
    # TLS verification for the DashScope connection. Default True (secure).
    # Set QWEN_VERIFY_SSL=false in local .env ONLY if your dev machine's CA
    # store rejects DashScope's cert chain (Python 3.14 / OpenSSL strict X.509).
    # Production should keep this True.
    QWEN_VERIFY_SSL: bool = True

    # ── Confidence Thresholds ─────────────────────────────────────────────────
    INTENT_CONFIDENCE_THRESHOLD: float = 0.7   # Below this, ask tenant to clarify
    PROPERTY_MATCH_THRESHOLD: float = 0.8

    # ── Mem0 Persistent Memory ────────────────────────────────────────────────
    # Use "local" for hackathon demo (no extra account needed)
    # Switch to "cloud" + MEM0_API_KEY for production
    MEM0_MODE: str = "local"        # "local" | "cloud"
    MEM0_API_KEY: str | None = None  # Only needed when MEM0_MODE=cloud
    # Local mode uses in-process vector store; no external service required
    MEM0_LOCAL_PATH: str = ".mem0_store"  # relative to server/ working dir

    # ── Alibaba Cloud OSS ─────────────────────────────────────────────────────
    # Mandatory hackathon requirement: proof of Alibaba Cloud service usage
    # Used to store generated tenancy agreement PDFs
    ALIBABA_CLOUD_ACCESS_KEY_ID: str | None = None
    ALIBABA_CLOUD_ACCESS_KEY_SECRET: str | None = None
    OSS_ENDPOINT: str = "https://oss-ap-southeast-1.aliyuncs.com"  # Singapore — closest to Nigeria
    OSS_BUCKET_NAME: str = "nuloafrica-agreements"
    OSS_REGION: str = "ap-southeast-1"

    # ── State Machine Configuration ───────────────────────────────────────────
    MAX_RETRIES: int = 3
    TIMEOUT_SECONDS: int = 30

    # ── Feature Flags ─────────────────────────────────────────────────────────
    ENABLE_PROPFLOW: bool = True
    ENABLE_MEM0_MEMORY: bool = False          # Toggle off in tests - disabled due to chromadb requirement
    ENABLE_OSS_STORAGE: bool = True          # Toggle off if OSS creds not set
    ENABLE_NOMBA_INTEGRATION: bool = True
    ENABLE_LANDLORD_APPROVAL_INTERRUPT: bool = True
    ENABLE_TENANT_SIGN_INTERRUPT: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_propflow_settings() -> PropFlowSettings:
    return PropFlowSettings()


propflow_settings = get_propflow_settings()
