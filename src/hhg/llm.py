"""Free-tier LLM access through an OpenAI-compatible endpoint (Gemini by default, Groq as fallback).

The LLM never decides actions: policy.py does. It plans optional tool calls and writes text
(summary, SAR narrative, pattern description) from the GraphRAG context it is given.
"""
import json
import re
import time

from openai import OpenAI

from hhg import config

_client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL) if config.LLM_API_KEY else None
# Groq's free tier takes over for chat when Gemini's daily quota runs out (Groq has no embeddings).
_groq = OpenAI(api_key=config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1") if config.GROQ_API_KEY else None
tokens_used = 0


def available() -> bool:
    return _client is not None or _groq is not None


def chat_json(system: str, user: str, retries: int = 4) -> dict:
    """One JSON-object completion. Retries on rate limits (429), then falls back to Groq."""
    try:
        return _chat(_client, config.LLM_MODEL, system, user, retries)
    except Exception:
        if _groq is None:
            raise
        return _chat(_groq, config.GROQ_MODEL, system, user, retries)


def _chat(client, model, system, user, retries):
    global tokens_used
    for i in range(retries):
        try:
            r = client.chat.completions.create(
                model=model, temperature=0.2,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            tokens_used += r.usage.total_tokens if r.usage else 0
            text = r.choices[0].message.content
            return json.loads(re.sub(r"^```(json)?|```$", "", text.strip()))
        except Exception as e:  # rate limit or a malformed JSON reply: back off and retry
            if i == retries - 1:
                raise
            time.sleep(8 * (i + 1) if "429" in str(e) else 2)


def embed(texts: list[str]) -> list[list[float]]:
    """Local open-source embeddings (BAAI/bge-small-en-v1.5 via fastembed, 384-d): no quota, reproducible.
    Gemini's free embedding quota (1,000/day) is too small to embed the case history."""
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding(config.EMBED_MODEL, cache_dir=str(config.ROOT / ".cache" / "fastembed"))
    return [v.tolist() for v in _embedder.embed(texts)]


_embedder = None
