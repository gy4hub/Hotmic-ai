from __future__ import annotations

from config import USD_PER_CNY


def _qwen_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if not model.startswith("qwen-plus"):
        return None

    prompt_tokens = input_tokens or 0
    completion_tokens = output_tokens or 0

    # DashScope qwen-plus mainland pricing is tiered by input size.
    if prompt_tokens <= 128_000:
        input_cny_per_1m = 0.8
        output_cny_per_1m = 2.0
    elif prompt_tokens <= 256_000:
        input_cny_per_1m = 2.4
        output_cny_per_1m = 20.0
    else:
        input_cny_per_1m = 4.8
        output_cny_per_1m = 48.0

    input_cost_cny = prompt_tokens / 1_000_000 * input_cny_per_1m
    output_cost_cny = completion_tokens / 1_000_000 * output_cny_per_1m
    return round((input_cost_cny + output_cost_cny) * USD_PER_CNY, 6)


def _gemini_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    prices = {
        "gemini-flash-latest": (0.5, 3.0),
        "gemini-3-flash-preview": (0.5, 3.0),
        "gemini-3.1-pro-preview": (2.0, 12.0),
        "gemini-2.5-flash": (0.3, 2.5),
        "gemini-2.5-pro": (1.25, 10.0),
    }
    if model not in prices:
        return None

    input_usd_per_1m, output_usd_per_1m = prices[model]
    prompt_tokens = input_tokens or 0
    completion_tokens = output_tokens or 0
    return round(
        prompt_tokens / 1_000_000 * input_usd_per_1m
        + completion_tokens / 1_000_000 * output_usd_per_1m,
        6,
    )


def estimate_cost_usd(
    provider: str | None,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    if not provider or not model:
        return None

    provider_key = provider.strip().lower()
    if provider_key == "qwen":
        return _qwen_cost_usd(model, input_tokens, output_tokens)
    if provider_key == "google":
        return _gemini_cost_usd(model, input_tokens, output_tokens)
    return None
