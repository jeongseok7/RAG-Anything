"""
Fully Local RAG-Anything Example — gemma4:26b + qwen3-embedding:0.6b

Runs the entire RAG pipeline locally on Apple Silicon via Ollama.
No external API calls required after initial model download.

Models:
- LLM + VLM: gemma4:26b  (25.8B, Q4_K_M, 17 GB — vision + thinking)
- Embedding: qwen3-embedding:0.6b  (1024-dim, 639 MB)

Requirements:
    pip install raganything ollama
    ollama pull gemma4:26b
    ollama pull qwen3-embedding:0.6b

Usage:
    python examples/local_gemma4_example.py
    python examples/local_gemma4_example.py --file path/to/document.pdf
    python examples/local_gemma4_example.py --file doc.pdf --device mps
"""

import asyncio
import argparse
import os
import uuid
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache

# ---------------------------------------------------------------------------
# Configuration (override via env vars)
# ---------------------------------------------------------------------------
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "gemma4:26b")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
EMBEDDING_DIM = int(os.getenv("OLLAMA_EMBEDDING_DIM", "1024"))

OLLAMA_BASE_URL = f"{OLLAMA_HOST}/v1"
OLLAMA_API_KEY = "ollama"  # Ollama ignores the key but the client requires one


# ---------------------------------------------------------------------------
# LLM function (text)
# ---------------------------------------------------------------------------
async def llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[List[Dict]] = None,
    **kwargs,
) -> str:
    return await openai_complete_if_cache(
        model=LLM_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=OLLAMA_BASE_URL,
        api_key=OLLAMA_API_KEY,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Vision function (image analysis + VLM-enhanced query)
#
# RAGAnything calls this in three modes:
#   1. messages=<list>  → VLM-enhanced query (OpenAI message format)
#   2. image_data=<str> → indexing (base64-encoded image bytes)
#   3. neither          → plain text fallback
# ---------------------------------------------------------------------------
async def vision_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[List[Dict]] = None,
    image_data: Optional[str] = None,
    messages: Optional[List[Dict]] = None,
    **kwargs,
) -> str:
    if messages:
        # VLM-enhanced query — pass full OpenAI-format messages
        return await openai_complete_if_cache(
            model=LLM_MODEL,
            prompt="",
            messages=messages,
            base_url=OLLAMA_BASE_URL,
            api_key=OLLAMA_API_KEY,
            **kwargs,
        )

    if image_data:
        # Indexing — build multimodal message from base64 image
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
            model=LLM_MODEL,
            prompt="",
            messages=msgs,
            base_url=OLLAMA_BASE_URL,
            api_key=OLLAMA_API_KEY,
            **kwargs,
        )

    # Plain text fallback
    return await llm_model_func(
        prompt, system_prompt, history_messages, **kwargs
    )


# ---------------------------------------------------------------------------
# Embedding function (native Ollama /api/embed)
# ---------------------------------------------------------------------------
async def embedding_func(texts: List[str]):
    import numpy as np
    import ollama

    client = ollama.AsyncClient(host=OLLAMA_HOST)
    response = await client.embed(model=EMBEDDING_MODEL, input=texts)
    return np.array(response.embeddings)


# ---------------------------------------------------------------------------
# Connectivity checks
# ---------------------------------------------------------------------------
async def preflight() -> bool:
    import ollama

    client = ollama.AsyncClient(host=OLLAMA_HOST)

    # Check Ollama is reachable
    try:
        models_resp = await client.list()
    except Exception as e:
        print(f"Ollama connection failed: {e}")
        print(f"  Is Ollama running?  Try: ollama serve")
        return False

    available = [m.model for m in models_resp.models]
    print(f"Ollama connected — {len(available)} model(s)")

    ok = True
    for name in (LLM_MODEL, EMBEDDING_MODEL):
        found = any(m.startswith(name.split(":")[0]) for m in available)
        status = "ok" if found else "MISSING"
        print(f"  [{status}] {name}")
        if not found:
            print(f"        Run: ollama pull {name}")
            ok = False

    if not ok:
        return False

    # Quick embedding sanity check
    vecs = await embedding_func(["test"])
    dim = len(vecs[0])
    print(f"  Embedding dim: {dim} (configured: {EMBEDDING_DIM})")
    if dim != EMBEDDING_DIM:
        print(f"  WARNING: set OLLAMA_EMBEDDING_DIM={dim}")
        return False

    # Quick LLM check
    resp = await llm_model_func("Say OK.", system_prompt="Reply in one word.")
    print(f"  LLM check: {resp.strip()[:40]}")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(file_path: Optional[str] = None, device: str = "cpu"):
    if not await preflight():
        return False

    config = RAGAnythingConfig(
        working_dir=f"./rag_storage_local/{uuid.uuid4().hex[:8]}",
        parser="mineru",
        parse_method="auto",
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )
    print(f"\nWorking dir: {config.working_dir}")

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=8192,
            func=embedding_func,
        ),
    )

    if file_path:
        # Process a real document
        print(f"\nProcessing: {file_path}")
        await rag.process_document_complete(
            file_path=file_path,
            output_dir="./output_local",
            parse_method="auto",
            device=device,
            display_stats=True,
        )
    else:
        # Demo with sample content
        content_list = [
            {
                "type": "text",
                "text": (
                    "Local RAG Pipeline with Gemma 4\n\n"
                    "This setup runs entirely on Apple Silicon via Ollama:\n"
                    "- gemma4:26b handles both text generation and image understanding\n"
                    "- qwen3-embedding:0.6b produces 1024-dim dense vectors\n"
                    "- MinerU parses documents with MPS acceleration\n"
                    "- LightRAG builds a knowledge graph from extracted entities\n\n"
                    "No cloud APIs are required after the initial model download."
                ),
                "page_idx": 0,
            }
        ]
        print("\nInserting sample content ...")
        await rag.insert_content_list(
            content_list=content_list,
            file_path="local_demo.txt",
            doc_id=f"demo-{uuid.uuid4().hex[:8]}",
            display_stats=True,
        )

    # Run a sample query
    print("\nQuerying ...")
    result = await rag.aquery(
        "What models are used in this local RAG pipeline?",
        mode="hybrid",
    )
    print(f"Answer: {result[:600]}")

    print("\nDone.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Local RAG-Anything with gemma4:26b")
    parser.add_argument("--file", help="Document to process (PDF, DOCX, PPTX, ...)")
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "mps", "cuda"],
        help="Device for MinerU parser (default: cpu, use mps for Apple Silicon)",
    )
    args = parser.parse_args()

    success = asyncio.run(run(file_path=args.file, device=args.device))
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
