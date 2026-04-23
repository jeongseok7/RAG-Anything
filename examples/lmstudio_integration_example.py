"""
LM Studio Integration Example with RAG-Anything

This example demonstrates how to integrate LM Studio with RAG-Anything for local
text + image document processing and querying on Apple Silicon (MLX).

Defaults:
- LLM + VLM: lmstudio-community/qwen/qwen3.6-27b-4bit (multimodal, vision tower preserved)
- Embedding: text-embedding-qwen3-embedding-0.6b (1024-dim)

Requirements:
- LM Studio running locally with server enabled (default http://localhost:1234)
- Both models loaded in LM Studio
- OpenAI Python package: pip install openai
- RAG-Anything installed: pip install -e .

Environment Setup:
Create a .env file with:
LLM_BINDING=lmstudio
LLM_MODEL=lmstudio-community/qwen/qwen3.6-27b-4bit
LLM_BINDING_HOST=http://localhost:1234/v1
LLM_BINDING_API_KEY=lm-studio
EMBEDDING_BINDING=lmstudio
EMBEDDING_MODEL=text-embedding-qwen3-embedding-0.6b
EMBEDDING_BINDING_HOST=http://localhost:1234/v1
EMBEDDING_BINDING_API_KEY=lm-studio
EMBEDDING_DIM=1024

From inside a Podman/Docker container, replace `localhost` with `host.docker.internal`.
"""

import os
import uuid
import asyncio
from typing import List, Dict, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Load environment variables
load_dotenv()

# Neo4j graph storage defaults. User-provided env vars win (dotenv is already
# loaded above); these only fire if a key is still unset. Defaults assume a
# local Neo4j on bolt://localhost:7687 (Neo4j Desktop 2, Podman, brew service,
# or any other runtime) with password "raganything". Set LIGHTRAG_GRAPH_STORAGE
# to "NetworkXStorage" to fall back to the legacy file-based graph.
os.environ.setdefault("LIGHTRAG_GRAPH_STORAGE", "Neo4JStorage")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "raganything")
os.environ.setdefault("NEO4J_DATABASE", "raganything")

# RAG-Anything imports
from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache

LM_BASE_URL = os.getenv("LLM_BINDING_HOST", "http://localhost:1234/v1")
LM_API_KEY = os.getenv("LLM_BINDING_API_KEY", "lm-studio")
LM_MODEL_NAME = os.getenv(
    "LLM_MODEL", "lmstudio-community/qwen/qwen3.6-27b-4bit"
)
LM_EMBED_MODEL = os.getenv(
    "EMBEDDING_MODEL", "text-embedding-qwen3-embedding-0.6b"
)
LM_EMBED_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))


async def lmstudio_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    """Top-level LLM function for LightRAG (pickle-safe)."""
    return await openai_complete_if_cache(
        model=LM_MODEL_NAME,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=LM_BASE_URL,
        api_key=LM_API_KEY,
        **kwargs,
    )


async def lmstudio_vision_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    image_data: Optional[str] = None,
    messages: Optional[List[Dict]] = None,
    **kwargs,
) -> str:
    """Vision function for LightRAG. Reuses the multimodal LLM model."""
    if messages:
        return await openai_complete_if_cache(
            model=LM_MODEL_NAME,
            prompt="",
            messages=messages,
            base_url=LM_BASE_URL,
            api_key=LM_API_KEY,
            **kwargs,
        )

    if image_data:
        user_content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
            },
        ]
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": user_content})

        return await openai_complete_if_cache(
            model=LM_MODEL_NAME,
            prompt="",
            messages=msgs,
            base_url=LM_BASE_URL,
            api_key=LM_API_KEY,
            **kwargs,
        )

    return await lmstudio_llm_model_func(
        prompt, system_prompt, history_messages, **kwargs
    )


async def lmstudio_embedding_async(texts: List[str]) -> List[List[float]]:
    """Top-level embedding function for LightRAG (pickle-safe)."""
    from lightrag.llm.openai import openai_embed

    embeddings = await openai_embed(
        texts=texts,
        model=LM_EMBED_MODEL,
        base_url=LM_BASE_URL,
        api_key=LM_API_KEY,
    )
    return embeddings.tolist()


class LMStudioRAGIntegration:
    """Integration class for LM Studio with RAG-Anything."""

    def __init__(self):
        # LM Studio configuration using standard LLM_BINDING variables
        self.base_url = LM_BASE_URL
        self.api_key = LM_API_KEY
        self.model_name = LM_MODEL_NAME
        self.embedding_model = LM_EMBED_MODEL

        # RAG-Anything configuration
        # Use a fresh working directory each run to avoid legacy doc_status schema conflicts
        self.config = RAGAnythingConfig(
            working_dir=f"./rag_storage_lmstudio/{uuid.uuid4()}",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        print(f"📁 Using working_dir: {self.config.working_dir}")

        self.rag = None

    async def test_connection(self) -> bool:
        """Test LM Studio connection."""
        try:
            print(f"🔌 Testing LM Studio connection at: {self.base_url}")
            client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            models = await client.models.list()
            print(f"✅ Connected successfully! Found {len(models.data)} models")

            # Show available models
            print("📊 Available models:")
            for i, model in enumerate(models.data[:5]):
                marker = "🎯" if model.id == self.model_name else "  "
                print(f"{marker} {i+1}. {model.id}")

            if len(models.data) > 5:
                print(f"  ... and {len(models.data) - 5} more models")

            return True
        except Exception as e:
            print(f"❌ Connection failed: {str(e)}")
            print("\n💡 Troubleshooting tips:")
            print("1. Ensure LM Studio is running")
            print("2. Start the local server in LM Studio")
            print("3. Load a model or enable just-in-time loading")
            print(f"4. Verify server address: {self.base_url}")
            return False
        finally:
            try:
                await client.close()
            except Exception:
                pass

    async def test_chat_completion(self) -> bool:
        """Test basic chat functionality."""
        try:
            print(f"💬 Testing chat with model: {self.model_name}")
            client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            response = await client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful AI assistant."},
                    {
                        "role": "user",
                        "content": "Hello! Please confirm you're working and tell me your capabilities.",
                    },
                ],
                max_tokens=100,
                temperature=0.7,
            )

            result = response.choices[0].message.content.strip()
            print("✅ Chat test successful!")
            print(f"Response: {result}")
            return True
        except Exception as e:
            print(f"❌ Chat test failed: {str(e)}")
            return False
        finally:
            try:
                await client.close()
            except Exception:
                pass

    # Deprecated factory helpers removed to reduce redundancy

    def embedding_func_factory(self):
        """Create a completely serializable embedding function."""
        return EmbeddingFunc(
            embedding_dim=LM_EMBED_DIM,  # qwen3-embedding-0.6b default: 1024
            max_token_size=8192,
            func=lmstudio_embedding_async,
        )

    async def initialize_rag(self):
        """Initialize RAG-Anything with LM Studio functions."""
        print("Initializing RAG-Anything with LM Studio...")

        try:
            graph_storage = os.environ["LIGHTRAG_GRAPH_STORAGE"]
            print(f"🗂  Graph storage: {graph_storage} (uri={os.environ.get('NEO4J_URI','-')})")

            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=lmstudio_llm_model_func,
                vision_model_func=lmstudio_vision_model_func,
                embedding_func=self.embedding_func_factory(),
                lightrag_kwargs={"graph_storage": graph_storage},
            )

            # Compatibility: avoid writing unknown field 'multimodal_processed' to LightRAG doc_status
            # Older LightRAG versions may not accept this extra field in DocProcessingStatus
            async def _noop_mark_multimodal(doc_id: str):
                return None

            self.rag._mark_multimodal_processing_complete = _noop_mark_multimodal

            print("✅ RAG-Anything initialized successfully!")
            return True
        except Exception as e:
            print(f"❌ RAG initialization failed: {str(e)}")
            return False

    async def process_document_example(self, file_path: str):
        """Example: Process a document with LM Studio backend."""
        if not self.rag:
            print("❌ RAG not initialized. Call initialize_rag() first.")
            return

        try:
            print(f"📄 Processing document: {file_path}")
            await self.rag.process_document_complete(
                file_path=file_path,
                output_dir="./output_lmstudio",
                parse_method="auto",
                display_stats=True,
            )
            print("✅ Document processing completed!")
        except Exception as e:
            print(f"❌ Document processing failed: {str(e)}")

    async def query_examples(self):
        """Example queries with different modes."""
        if not self.rag:
            print("❌ RAG not initialized. Call initialize_rag() first.")
            return

        # Example queries
        queries = [
            ("What are the main topics in the processed documents?", "hybrid"),
            ("Summarize any tables or data found in the documents", "local"),
            ("What images or figures are mentioned?", "global"),
        ]

        print("\n🔍 Running example queries...")
        for query, mode in queries:
            try:
                print(f"\nQuery ({mode}): {query}")
                result = await self.rag.aquery(query, mode=mode)
                print(f"Answer: {result[:200]}...")
            except Exception as e:
                print(f"❌ Query failed: {str(e)}")

    async def simple_query_example(self):
        """Example basic text query with sample content."""
        if not self.rag:
            print("❌ RAG not initialized")
            return

        try:
            print("\nAdding sample content for testing...")

            # Create content list in the format expected by RAGAnything
            content_list = [
                {
                    "type": "text",
                    "text": """LM Studio Integration with RAG-Anything

This integration demonstrates how to connect LM Studio's local AI models with RAG-Anything's document processing capabilities. The system uses:

- LM Studio for local LLM inference
- nomic-embed-text-v1.5 for embeddings (768 dimensions)
- RAG-Anything for document processing and retrieval

Key benefits include:
- Privacy: All processing happens locally
- Performance: Direct API access to local models
- Flexibility: Support for various document formats
- Cost-effective: No external API usage""",
                    "page_idx": 0,
                }
            ]

            # Insert the content list using the correct method
            await self.rag.insert_content_list(
                content_list=content_list,
                file_path="lmstudio_integration_demo.txt",
                # Use a unique doc_id to avoid collisions and doc_status reuse across runs
                doc_id=f"demo-content-{uuid.uuid4()}",
                display_stats=True,
            )
            print("✅ Sample content added to knowledge base")

            print("\nTesting basic text query...")

            # Simple text query example
            result = await self.rag.aquery(
                "What are the key benefits of this LM Studio integration?",
                mode="hybrid",
            )
            print(f"✅ Query result: {result[:300]}...")

        except Exception as e:
            print(f"❌ Query failed: {str(e)}")


async def main():
    """Main example function."""
    print("=" * 70)
    print("LM Studio + RAG-Anything Integration Example")
    print("=" * 70)

    # Initialize integration
    integration = LMStudioRAGIntegration()

    # Test connection
    if not await integration.test_connection():
        return False

    print()
    if not await integration.test_chat_completion():
        return False

    # Initialize RAG
    print("\n" + "─" * 50)
    if not await integration.initialize_rag():
        return False

    # Example document processing (uncomment and provide a real file path)
    # await integration.process_document_example("path/to/your/document.pdf")

    # Example queries (uncomment after processing documents)
    # await integration.query_examples()

    # Example basic query
    await integration.simple_query_example()

    print("\n" + "=" * 70)
    print("Integration example completed successfully!")
    print("=" * 70)

    return True


if __name__ == "__main__":
    print("🚀 Starting LM Studio integration example...")
    success = asyncio.run(main())

    exit(0 if success else 1)
