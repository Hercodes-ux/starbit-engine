"""
Shared LLM client factory for every agent.

Using Groq (not Anthropic/OpenAI) specifically because Groq's API has a
genuinely free tier -- no credit card required.

Two model tiers, not one:
- The main model (settings.model_name) handles SQL generation and the
  hallucination-check summary -- tasks where getting it wrong actually
  matters.
- A smaller "fast" model (settings.fast_model_name) handles cheap
  classification-style decisions (e.g. "which chart type") where a
  bigger model buys no real accuracy but does add real latency. Every
  question runs 4+ sequential LLM calls, so trimming latency on the
  low-stakes ones is a meaningful, real speedup, not a placebo.

Get a free key at https://console.groq.com/keys
"""
from langchain_groq import ChatGroq
from config import settings

_clients: dict[str, ChatGroq] = {}


def get_llm(temperature: float = 0.0, fast: bool = False, max_tokens: int = 1024) -> ChatGroq:
    model = settings.fast_model_name if fast else settings.model_name
    cache_key = f"{model}:{temperature}:{max_tokens}"
    if cache_key not in _clients:
        _clients[cache_key] = ChatGroq(
            model=model,
            api_key=settings.groq_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return _clients[cache_key]
