import httpx

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.fake import FakeProvider
from app.llm.openai_compat import OpenAICompatProvider


def build_provider(settings: Settings, http: httpx.AsyncClient) -> LLMProvider:
    if settings.llm_provider == "openai_compat":
        return OpenAICompatProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key.get_secret_value(),
            http=http,
            timeout=settings.llm_timeout_seconds,
            stream_usage=settings.llm_stream_usage,
        )
    delay = settings.llm_fake_delay_ms / 1000
    if settings.llm_fake_script:
        return FakeProvider.from_file(settings.llm_fake_script, delay=delay)
    return FakeProvider(delay=delay)
