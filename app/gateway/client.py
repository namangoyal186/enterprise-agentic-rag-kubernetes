from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI, OpenAI
from portkey_ai import PORTKEY_GATEWAY_URL, createHeaders
from app.config import settings
import os
import logfire
from langchain_groq import ChatGroq
from app.gateway.key_manager import key_rotator


def _make_headers(feature: str = "rag") -> dict:
    """Build Portkey headers with explicit provider and virtual_key routing."""
    return createHeaders(
        api_key=settings.PORTKEY_API_KEY,
        provider="groq",
        virtual_key=settings.PORTKEY_PRIMARY_SLUG,
        metadata={
            "feature": feature,
            "_user": "rag-system",
            "environment": "production",
        },
    )


# OpenAI-compatible client routed through Portkey
portkey_client = OpenAI(
    api_key=settings.PORTKEY_API_KEY,
    base_url=PORTKEY_GATEWAY_URL,
    default_headers=_make_headers(),
)


def get_langchain_llm(feature: str = "default", use_gemini_fallback: bool = False):
    """
    Returns a LangChain LLM instance with key rotation and optional Gemini fallback.
    """
    if use_gemini_fallback:
        from langchain_google_genai import ChatGoogleGenerativeAI
        logfire.info("⚡ Using Google Gemini fallback LLM")
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0,
        )

    # Groq Chat LLM with active rotated key
    return ChatGroq(
        model_name=os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b"),
        groq_api_key=key_rotator.get_key(),
        temperature=0,
    )


def get_async_openai_client(feature: str = "rag") -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.PORTKEY_API_KEY,
        base_url=PORTKEY_GATEWAY_URL,
        default_headers=_make_headers(feature),
    )


def extract_cache_status(response) -> str:
    for attr in ("_raw_response", "_response", "_http_response", "headers"):
        raw = getattr(response, attr, None)
        if raw is not None:
            headers = getattr(raw, "headers", None)
            if headers is not None:
                status = headers.get("x-portkey-cache-status", "")
                if status:
                    return status.upper()
    return "MISS"