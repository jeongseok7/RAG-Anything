# LiteLLM Integration Guide for RAG-Anything

[LiteLLM](https://github.com/BerriAI/litellm) is a unified API gateway that exposes 100+ LLM providers (OpenAI, Anthropic, Vertex, Bedrock, custom OSS endpoints, …) through a single OpenAI-compatible interface.

This guide covers how to point RAG-Anything at an **already-running internal LiteLLM router** (e.g. `http://localhost/v1`).

> **No code changes required.** LiteLLM proxy is OpenAI-compatible — RAG-Anything connects via the existing `LLM_BINDING=openai` path.

## Why an internal LiteLLM router?

| Concern | Direct provider call | Via internal LiteLLM |
|---------|----------------------|-----------------------|
| API key management | Each user holds vendor keys | Centralized virtual keys |
| Cost / budget tracking | Per-vendor billing | Unified spend logs |
| Routing & fallback | Manual | Configured in proxy |
| Audit logging | Per-vendor | Single observability plane |
| Provider lock-in | Yes | Switch model with one env var |

**Choose this integration when:** Your organization runs a shared LiteLLM proxy and wants RAG-Anything to go through it for governance.

## Quick Start

### 1. Discover available models

```bash
curl -s -H "Authorization: Bearer sk-your-litellm-virtual-key" \
  http://localhost/v1/models | jq '.data[].id'
```

The IDs returned are exactly what you put in `LLM_MODEL` / `EMBEDDING_MODEL` — copy them verbatim.

### 2. Configure `.env`

```bash
### Server
LLM_BINDING=openai
LLM_BINDING_HOST=http://localhost/v1
LLM_BINDING_API_KEY=sk-your-litellm-virtual-key

### Recommended models (see "Model selection" below)
LLM_MODEL=openai/gpt-5.4-mini:2026-03-17
VISION_MODEL=openai/gpt-5.4-mini:2026-03-17

### Embedding via the same proxy
EMBEDDING_BINDING=openai
EMBEDDING_BINDING_HOST=http://localhost/v1
EMBEDDING_BINDING_API_KEY=sk-your-litellm-virtual-key
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBEDDING_DIM=1024
```

### 3. Run

```bash
python examples/litellm_integration_example.py
```

## Environment Variables

| Variable | Value | Notes |
|----------|-------|-------|
| `LLM_BINDING` | `openai` | LiteLLM proxy speaks OpenAI protocol |
| `LLM_BINDING_HOST` | `http://localhost/v1` | Trailing `/v1` is required |
| `LLM_BINDING_API_KEY` | `sk-...` | LiteLLM **virtual key** (issued by the proxy admin) |
| `LLM_MODEL` | e.g. `openai/gpt-5.4-mini:2026-03-17` | Must match `/v1/models` ID exactly |
| `VISION_MODEL` | same family as `LLM_MODEL` | Used for image / table extraction |
| `EMBEDDING_BINDING` | `openai` | Reuses the OpenAI-compatible embedding path |
| `EMBEDDING_BINDING_HOST` | same as `LLM_BINDING_HOST` | Single proxy serves both |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | No `openai/` prefix — copy from `/models` |
| `EMBEDDING_DIM` | `1024` | Verify with `/v1/embeddings` probe |

## Model Selection

RAG-Anything's cost is dominated by **indexing-time entity/relation extraction** (one LLM call per chunk). Optimize this slot first.

### Recommended

| Slot | Model | Rationale |
|------|-------|-----------|
| `LLM_MODEL` (primary) | `openai/gpt-5.4-mini:2026-03-17` | Latest mini, structured-output reliable, vision capable, ~1/5 cost of flagship |
| `VISION_MODEL` | `openai/gpt-5.4-mini:2026-03-17` | Same model — simpler config, vision native |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | 1024-dim, lightweight, good multilingual quality |

### GPT alternatives on the router

| Model | When to use |
|-------|-------------|
| `openai/gpt-5-mini:2025-08-07` | Fallback if `gpt-5.4-mini` has issues — proven stability |
| `openai/gpt-4.1-mini:2025-04-14` | Most conservative choice — well-tested mini |
| `openai/gpt-5.4-nano:2026-03-17` | Extreme volume indexing only; expect lower extraction accuracy |
| `openai/gpt-5.4:2026-03-05` | Quality-critical workloads (~5x cost) |

### Embedding alternatives

| Model | Dim | Notes |
|-------|-----|-------|
| `Qwen/Qwen3-Embedding-0.6B` | 1024 | **Default** — fast, cheap, multilingual |
| `Qwen/Qwen3-Embedding-4B` | (probe) | Higher quality, more cost |
| `Qwen/Qwen3-Embedding-8B` | (probe) | Best Qwen quality |
| `BAAI/bge-m3` | 1024 | Strong multilingual baseline |
| `openai/text-embedding-3-small` | 1536 | OpenAI baseline |
| `openai/text-embedding-3-large` | 3072 | Highest OpenAI quality |

> ⚠️ Always probe `EMBEDDING_DIM` with a real call before committing — the dim affects vector store schema and cannot be changed without re-indexing.

```bash
curl -s -H "Authorization: Bearer sk-..." \
  http://localhost/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model-id>","input":"probe"}' \
  | jq '.data[0].embedding | length'
```

## Model ID prefix gotcha

The router lists models with provider prefixes (`openai/...`, `anthropic/...`, `google/...`, or bare like `Qwen/...`). When calling **through the proxy**, use the ID **exactly as listed** — do not add or remove prefixes. For example:

| ✅ Correct | ❌ Wrong |
|-----------|---------|
| `LLM_MODEL=openai/gpt-5.4-mini:2026-03-17` | `LLM_MODEL=gpt-5.4-mini` |
| `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B` | `EMBEDDING_MODEL=openai/Qwen/Qwen3-Embedding-0.6B` |

The `openai/` prefix on a non-OpenAI model is a LiteLLM **SDK** convention (provider hint). When using the proxy you reuse the listed ID.

## Connectivity test

Quick smoke tests before running the full example:

```bash
# 1. List models
curl -s -H "Authorization: Bearer sk-..." \
  http://localhost/v1/models | jq '.data | length'

# 2. Chat
curl -s -H "Authorization: Bearer sk-..." \
  http://localhost/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"openai/gpt-5.4-mini:2026-03-17",
       "messages":[{"role":"user","content":"reply ok"}],
       "max_tokens":10}'

# 3. Embedding
curl -s -H "Authorization: Bearer sk-..." \
  http://localhost/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-Embedding-0.6B","input":"probe"}'
```

## Architecture

```
┌──────────────────────┐
│   RAG-Anything       │
│  (LLM_BINDING=openai)│
└──────┬───────────────┘
       │ OpenAI-compatible HTTPS
       ▼
┌──────────────────────────────────────────┐
│   Internal LiteLLM Router                 │
│   localhost:8080   │
│   ─────────────────────────────────────   │
│   · virtual key auth                      │
│   · routing / fallback / budget           │
│   · unified logs                          │
└──────┬───────────────┬─────────────┬─────┘
       ▼               ▼             ▼
   OpenAI API     Anthropic     Vertex / Bedrock / OSS
```

## Troubleshooting

### `401 Unauthorized`
- Verify the virtual key with the LiteLLM admin team
- Confirm the key is not expired or rate-limited

### `404 model not found`
- Re-fetch `/v1/models` and copy the ID **exactly** (including `:date` suffix)
- Common mistake: dropping the date tag (e.g. `gpt-5.4-mini` instead of `openai/gpt-5.4-mini:2026-03-17`)

### Wrong `EMBEDDING_DIM`
- Vector store rejects insert with shape mismatch
- Probe the dim with a real call (see "Connectivity test")
- If you already indexed with the wrong dim, you must re-index

### Slow / timeouts on indexing
- Increase `MAX_ASYNC` (e.g. `MAX_ASYNC=8`) — proxy handles concurrency well
- Confirm with the proxy admin that your virtual key has sufficient rate limits

### Structured-output failures during entity extraction
- Switch to a higher-tier model temporarily (`gpt-5.4` instead of `gpt-5.4-mini`)
- If the issue is consistent, file an issue with the proxy admin (model routing may be misconfigured)
