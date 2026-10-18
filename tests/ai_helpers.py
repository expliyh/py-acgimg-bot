"""Configure real shared providers for moderation integration tests."""

from services.ai import providers
from services.ai.schemas import AIRequestConfig, AISelection, ProviderInput
from services.moderation import store
from services.moderation.schemas import AIConfig


async def configure_ai(*, base_url, text_model="", vision_model="", api_key=None, timeout=20, concurrency=2):
    provider = await providers.save(ProviderInput(
        name="Test provider", base_url=base_url, api_key=api_key,
        models=[{"id": model, "input_types": ["text", "image"]}
                for model in (list(dict.fromkeys(filter(None, [text_model, vision_model]))) or ["unused"])],
        timeout=timeout, concurrency=concurrency,
    ))
    def selection(model):
        return AISelection(provider_id=provider.id, model=model) if model else None
    return await store.save_ai_config(AIConfig(
        ai_text=selection(text_model), ai_vision=selection(vision_model or ("unused" if not text_model else "")),
        ai_username=selection(text_model),
    ))


def request_config(*, base_url, model="test", api_key=None, timeout=20, concurrency=2):
    return AIRequestConfig(
        provider_id="test-provider", base_url=base_url.rstrip("/"), api_key=api_key,
        model=model, timeout=timeout, concurrency=concurrency,
    )
