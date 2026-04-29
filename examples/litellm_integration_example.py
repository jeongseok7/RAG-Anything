"""
LiteLLM (Internal Router) Integration Example with RAG-Anything

Connects RAG-Anything to a shared, internal LiteLLM router. LiteLLM proxy
exposes an OpenAI-compatible API, so this example reuses
`lightrag.llm.openai` helpers — no code changes are needed inside RAG-Anything
itself.

See docs/litellm_integration.md for the full setup guide.

Environment Setup (.env):
    LLM_BINDING=openai
    LLM_BINDING_HOST=http://localhost/v1
    LLM_BINDING_API_KEY=sk-your-litellm-virtual-key
    LLM_MODEL=openai/gpt-5.4-mini:2026-03-17
    VISION_MODEL=openai/gpt-5.4-mini:2026-03-17
    EMBEDDING_BINDING=openai
    EMBEDDING_BINDING_HOST=http://localhost/v1
    EMBEDDING_BINDING_API_KEY=sk-your-litellm-virtual-key
    EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
    EMBEDDING_DIM=1024
"""

import os
import uuid
import asyncio
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache, openai_embed

load_dotenv()

LITELLM_BASE_URL = os.getenv(
    "LLM_BINDING_HOST", "http://localhost/v1"
)
LITELLM_API_KEY = os.getenv("LLM_BINDING_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-5.4-mini:2026-03-17")

EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BINDING_HOST", LITELLM_BASE_URL)
EMBEDDING_API_KEY = os.getenv("EMBEDDING_BINDING_API_KEY", LITELLM_API_KEY)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))


def _require_api_key() -> str:
    if not LITELLM_API_KEY:
        raise ValueError(
            "LLM_BINDING_API_KEY is required. "
            "Issue a virtual key from your LiteLLM admin and export it."
        )
    return LITELLM_API_KEY


async def litellm_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    return await openai_complete_if_cache(
        model=LLM_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=LITELLM_BASE_URL,
        api_key=_require_api_key(),
        **kwargs,
    )


async def litellm_embedding_async(texts: List[str]) -> List[List[float]]:
    embeddings = await openai_embed(
        texts=texts,
        model=EMBEDDING_MODEL,
        base_url=EMBEDDING_BASE_URL,
        api_key=_require_api_key(),
    )
    return embeddings.tolist()


class LiteLLMRAGIntegration:
    def __init__(self):
        self.config = RAGAnythingConfig(
            working_dir=f"./rag_storage_litellm/{uuid.uuid4()}",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=False,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        print(f"📁 working_dir: {self.config.working_dir}")
        self.rag: Optional[RAGAnything] = None

    async def test_connection(self) -> bool:
        print(f"🔌 Probing LiteLLM router: {LITELLM_BASE_URL}")
        client = AsyncOpenAI(base_url=LITELLM_BASE_URL, api_key=_require_api_key())
        try:
            models = await client.models.list()
            ids = [m.id for m in models.data]
            print(f"✅ Connected. {len(ids)} models available.")

            for slot, model in (("LLM_MODEL", LLM_MODEL), ("EMBEDDING_MODEL", EMBEDDING_MODEL)):
                marker = "✅" if model in ids else "❌"
                print(f"   {marker} {slot}={model}")
            if LLM_MODEL not in ids or EMBEDDING_MODEL not in ids:
                print("\n💡 Model ID must match /v1/models response exactly.")
                return False
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def test_chat(self) -> bool:
        try:
            print(f"💬 Chat probe: {LLM_MODEL}")
            reply = await litellm_llm_model_func(
                "Reply with the single word: ok",
                system_prompt="You are a terse assistant.",
                max_tokens=10,
            )
            print(f"   reply: {reply.strip()}")
            return True
        except Exception as e:
            print(f"❌ Chat probe failed: {e}")
            return False

    async def test_embedding(self) -> bool:
        try:
            print(f"🧮 Embedding probe: {EMBEDDING_MODEL}")
            vecs = await litellm_embedding_async(["probe"])
            actual_dim = len(vecs[0])
            ok = actual_dim == EMBEDDING_DIM
            marker = "✅" if ok else "⚠️"
            print(f"   {marker} dim={actual_dim} (configured EMBEDDING_DIM={EMBEDDING_DIM})")
            if not ok:
                print(
                    "   Update EMBEDDING_DIM to match the actual dimension before indexing."
                )
            return ok
        except Exception as e:
            print(f"❌ Embedding probe failed: {e}")
            return False

    async def initialize_rag(self) -> bool:
        print("Initializing RAG-Anything via LiteLLM...")
        try:
            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=litellm_llm_model_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=EMBEDDING_DIM,
                    max_token_size=8192,
                    func=litellm_embedding_async,
                ),
            )

            async def _noop_mark_multimodal(doc_id: str):
                return None

            self.rag._mark_multimodal_processing_complete = _noop_mark_multimodal
            print("✅ RAG-Anything initialized.")
            return True
        except Exception as e:
            print(f"❌ RAG init failed: {e}")
            return False

    async def simple_query_demo(self):
        if not self.rag:
            return
        try:
            print("\nInserting sample content...")
            await self.rag.insert_content_list(
                content_list=[
                    {
                        "type": "text",
                        "text": (
                            "LiteLLM is a unified gateway exposing 100+ LLM providers "
                            "through an OpenAI-compatible API. RAG-Anything connects to "
                            "an internal LiteLLM router using the standard openai binding."
                        ),
                        "page_idx": 0,
                    }
                ],
                file_path="litellm_integration_demo.txt",
                doc_id=f"demo-{uuid.uuid4()}",
                display_stats=True,
            )

            print("Running query...")
            answer = await self.rag.aquery(
                "How does RAG-Anything connect to LiteLLM?", mode="hybrid"
            )
            print(f"✅ answer: {answer[:300]}...")
        except Exception as e:
            print(f"❌ Query failed: {e}")


async def main() -> bool:
    print("=" * 70)
    print("LiteLLM (Internal Router) + RAG-Anything Integration Example")
    print("=" * 70)

    integration = LiteLLMRAGIntegration()

    if not await integration.test_connection():
        return False
    if not await integration.test_chat():
        return False
    if not await integration.test_embedding():
        return False

    print("\n" + "─" * 50)
    if not await integration.initialize_rag():
        return False

    await integration.simple_query_demo()

    print("\n" + "=" * 70)
    print("Done.")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
