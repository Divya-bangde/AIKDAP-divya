"""Assert the Ollama passthrough; run with `python -m scripts.check_qwen_num_ctx`."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.llm import gateway as gateway_module
from app.core.llm.gateway import (
    LLMGateway,
    reset_litellm_logging_worker_for_task_boundary,
)


async def check_num_ctx_passthrough() -> None:
    completion = SimpleNamespace(
        model="ollama_chat/qwen3.5:4b",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"status":"ok"}'),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            model_dump=lambda: {
                "prompt_tokens": 8,
                "completion_tokens": 5,
                "total_tokens": 13,
            }
        ),
    )
    mocked_completion = AsyncMock(return_value=completion)

    try:
        with patch.object(gateway_module, "acompletion", mocked_completion):
            gateway = LLMGateway(
                default_model="ollama_chat/qwen3.5:4b",
                max_retries=0,
            )
            await gateway.generate(
                prompt="Return JSON.",
                num_ctx=16_384,
                allow_fallback=False,
                respect_provider_health=False,
            )

        assert mocked_completion.await_args.kwargs["num_ctx"] == 16_384
    finally:
        await reset_litellm_logging_worker_for_task_boundary()


if __name__ == "__main__":
    asyncio.run(check_num_ctx_passthrough())
    print("num_ctx passthrough check passed")
