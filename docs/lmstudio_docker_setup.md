# LM Studio (Host) + RAG-Anything (Container) Setup

Run RAG-Anything inside a Podman container while LM Studio runs natively on the
macOS host. This preserves MLX/Metal acceleration (which cannot work inside a
Linux container on macOS) and keeps the Python pipeline hermetic.

## Architecture

```
┌─ macOS host ───────────────────────────────┐
│  LM Studio (native, MLX)                   │
│    - lmstudio-community/                   │
│        qwen/qwen3.6-27b-4bit  (VLM)  │
│    - text-embedding-qwen3-embedding-0.6b   │
│  Local Server on :1234                     │
└────────────────────────┬───────────────────┘
                         │ host.docker.internal:1234
┌────────────────────────▼───────────────────┐
│  Podman container: raganything-lmstudio    │
│    - Python 3.12                           │
│    - RAG-Anything + MinerU + LibreOffice   │
│    - HF_HOME mounted from host             │
└────────────────────────────────────────────┘
```

## 1. Prepare LM Studio on the host

1. Install LM Studio (https://lmstudio.ai)
2. Download both models from the model catalog:
   - `lmstudio-community/qwen/qwen3.6-27b-4bit` (LLM + VLM, ~15 GB)
   - `text-embedding-qwen3-embedding-0.6b` (Embedding, ~1.2 GB)
3. Load both models (LM Studio supports multiple simultaneous loads; turn on
   **Just-In-Time Model Loading** if memory pressure is high)
4. Start **Local Server** (Developer tab → Start Server). Verify:
   ```bash
   curl -s http://localhost:1234/v1/models | jq '.data[].id'
   ```
   Both model IDs must appear.

## 2. Build and run the container

From the project root:

```bash
podman compose build
podman compose up
```

The first run downloads the MinerU models (layout / OCR / table / formula,
~2–4 GB total) into the host `HF_HOME`. Subsequent runs reuse the cache.

### Override cache locations

```bash
HF_HOME_HOST=/Volumes/Work/hf_cache \
MODELSCOPE_CACHE_HOST=/Volumes/Work/modelscope_cache \
  podman compose up
```

### Override models

```bash
LLM_MODEL=other/model-id \
EMBEDDING_MODEL=other/embed-id \
  podman compose up
```

## 3. Process a document

Drop a file into `./inputs/` on the host, then:

```bash
podman compose run --rm raganything \
    python examples/lmstudio_integration_example.py
```

Or with a specific document, modify the example to call
`integration.process_document_example("/app/inputs/your.pdf")`.

Outputs land in `./output_lmstudio/` and the knowledge graph in
`./rag_storage_lmstudio/`.

## 4. Interactive shell

```bash
podman compose run --rm raganything bash
```

Inside: LibreOffice, MinerU CLI, and the full RAG-Anything package are
available.

## Troubleshooting

### `Connection refused` to host.docker.internal:1234
- Verify LM Studio Local Server is running on the host: `curl http://localhost:1234/v1/models`
- On Linux hosts, `host.docker.internal` maps via `extra_hosts: host-gateway`.
  For older Podman (< 4.1) you may need `--network=slirp4netns:allow_host_loopback=true`.

### Embedding dimension mismatch
- Qwen3-Embedding-0.6B outputs **1024** dims. `EMBEDDING_DIM=1024` is set in
  `compose.yaml`. If you change models, update both the env var and
  `EmbeddingFunc(embedding_dim=...)` if you copy the example.

### MinerU re-downloads models on every run
- Confirm `${HF_HOME_HOST}` (default `~/.cache/huggingface`) is writable and
  the mount appears in `podman compose config`.

### Office parsing fails with "LibreOffice not found"
- The Dockerfile installs `libreoffice` + Korean locale pack. Rebuild if you
  edited the Dockerfile: `podman compose build --no-cache`.

### Vision requests return empty / model refuses images
- Confirm the loaded Gemma 4 build is the `lmstudio-community` MLX-4bit
  variant (vision tower preserved). The `Jiunsong/supergemma4-...-mlx-v2`
  fine-tune is text-only — its vision tower was stripped during MLX
  conversion.

## File map

| Path | Purpose |
|---|---|
| `Dockerfile` | Python 3.12 + LibreOffice + MinerU deps |
| `compose.yaml` | Podman service definition, volumes, host-gateway wiring |
| `.dockerignore` | Excludes venv / runtime data from build context |
| `examples/lmstudio_integration_example.py` | LLM + VLM + embedding wiring |
