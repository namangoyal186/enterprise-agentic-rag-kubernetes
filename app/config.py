import os
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    # --- API KEYS & CORE ---
    GEMINI_API_KEY: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    JINA_API_KEY: str | None = Field(default=None, validation_alias="JINA_API_KEY")
    GROQ_API_KEY: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile", validation_alias="GROQ_MODEL")
    
    # --- VECTOR DB ---
    QDRANT_URL: str | None = Field(default=None, validation_alias="QDRANT_CLUSTER_ENDPOINT")
    QDRANT_API_KEY: str | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    QDRANT_COLLECTION: str = "enterprise_rag"

    # --- OBSERVABILITY ---
    LOGFIRE_TOKEN: str | None = Field(default=None, validation_alias="LOGFIRE_TOKEN")
    LOGFIRE_BASE_URL: str = Field(default="https://logfire-us.pydantic.dev", validation_alias="LOGFIRE_BASE_URL")
    LANGSMITH_TRACING: str = "true"
    LANGSMITH_API_KEY: str | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")
    LANGSMITH_PROJECT: str = "rag_scale_test"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    # --- PORTKEY LLM GATEWAY ---
    PORTKEY_API_KEY: str | None = Field(default=None, validation_alias="PORTKEY_API_KEY")
    PORTKEY_PRIMARY_SLUG: str = "marathon-api"
    PORTKEY_FALLBACK_SLUG: str = "anthropic-fallback"
    PORTKEY_PRIMARY_CONFIG_ID: str | None = Field(default=None, validation_alias="PORTKEY_PRIMARY_CONFIG_ID")

    # --- OPENAI LLM ---
    OPENAI_API_KEY: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    JUDGE_OPENAI_API_KEY: str | None = None

    # --- DATABASE & REDIS ALIASES ---
    postgres_uri: str | None = Field(default=None, validation_alias="NEON_DB_URL")
    UPSTASH_REDIS_REST_URL: str | None = Field(default=None, validation_alias="UPSTASH_REDIS_REST_URL")
    UPSTASH_REDIS_REST_TOKEN: str | None = Field(default=None, validation_alias="UPSTASH_REDIS_REST_TOKEN")

    @property
    def redis_url(self) -> str | None:
        raw_url = self.UPSTASH_REDIS_REST_URL
        if not raw_url:
            return None
        if raw_url.startswith("rediss://") or raw_url.startswith("redis://"):
            return raw_url
        if self.UPSTASH_REDIS_REST_TOKEN:
            host = raw_url.replace("https://", "").replace("http://", "").strip("/")
            return f"rediss://default:{self.UPSTASH_REDIS_REST_TOKEN}@{host}:6379"
        return raw_url

    # --- API SAFETY & AUTH ---
    API_KEY: str | None = Field(default=None, alias="RAG_API_KEY")
    RATE_LIMIT_PER_MINUTE: int = 100
    STRICT_STARTUP: bool = False
    GOOGLE_CLIENT_ID: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_SECRET")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()