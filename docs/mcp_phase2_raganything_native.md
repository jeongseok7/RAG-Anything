# Phase 2 — RAG-Anything Native MCP Server

Phase 1 (lightrag-mcp 컨테이너, `127.0.0.1:8000/mcp`)은 lightrag-server REST를
래핑하므로 RAG-Anything 고유 기능이 노출되지 않는다. Phase 2 는 Python 인프로세스
방식으로 `RAGAnything` 클래스를 직접 import 하여 멀티모달/풀파이프라인 메서드를
별도 MCP 엔드포인트로 노출한다.

## 결정사항 (확정)

| 항목 | 값 |
|---|---|
| 구현 방식 | **인프로세스** — `from raganything import RAGAnything` |
| Transport | streamable-http |
| 노출 위치 | `127.0.0.1:8001/mcp` (localhost only) |
| 인증 | `LIGHTRAG_API_KEY` 헤더 검증 (Phase 1과 동일 키 재사용) |
| 데이터 백엔드 | Phase 1과 같은 Neo4j(7687) + Qdrant(6333) 공유 |
| 별칭 | MCP 클라이언트 등록명 `raganything` (Phase 1은 `lightrag`) |

## 노출할 툴

lightrag-mcp 가 이미 커버하는 기능(query / insert_text / KG read / health)은
중복 노출하지 않는다. **lightrag-server REST 에 없는 것만** 노출:

| Tool | 매핑 메서드 | 용도 |
|---|---|---|
| `rag_query_multimodal` | `RAGAnything.aquery_with_multimodal` | 텍스트 + 이미지/표/수식 혼합 질의 |
| `rag_query_vlm_enhanced` | `RAGAnything.aquery_vlm_enhanced` | VLM 기반 검색 결과 재해석 |
| `rag_process_document` | `RAGAnything.process_document_complete` | PDF/Office/이미지 풀 파이프라인 인덱싱 (parser + modal processor 포함) |
| `rag_insert_content_list` | `RAGAnything.insert_content_list` | 사전 파싱된 콘텐츠 구조 직접 삽입 |
| `rag_doc_status` | `RAGAnything.get_document_processing_status` / `is_document_fully_processed` | 멀티모달 처리 상태 조회 |

각 메서드 시그니처는 `raganything/query.py`, `raganything/processor.py` 참고.

## 파일 레이아웃

```
RAG-Anything/
├── Dockerfile.mcp.native      # 신규 — Python 3.12 + raganything + fastmcp
├── raganything_mcp/           # 신규 패키지 — 기존 raganything/ 와 분리
│   ├── __init__.py
│   ├── server.py              # FastMCP 인스턴스 + tool 등록
│   ├── tools.py               # RAGAnything 메서드를 MCP tool 로 어댑팅
│   └── config.py              # 환경변수 → RAGAnythingConfig 매핑
├── compose.yaml               # raganything-mcp-native 서비스 추가
└── docs/mcp_phase2_raganything_native.md  # 이 문서
```

`raganything/` 본체는 건드리지 않는다. `raganything_mcp/` 는 `raganything` 을
의존성으로만 사용한다.

## 의존성

```
fastmcp>=2.0          # MCP Python 헬퍼 (streamable-http 지원)
raganything[all]      # 본 프로젝트
```

`fastmcp` 가 무거우면 공식 `mcp` SDK 의 `mcp.server.fastmcp` 직접 사용도 가능.

## Dockerfile.mcp.native 골격

`Dockerfile`(raganything 본체용)의 1~25 라인 시스템 의존성 구간을 거의 그대로
재사용. 차이점은:

- `lightrag-server` 가 아니라 `python -m raganything_mcp.server` 를 CMD 로 실행
- `EXPOSE 8001`
- `ENTRYPOINT` 또는 CMD 에 streamable-http 인자 포함

빌드 캐시 공유를 위해 `raganything` base image 를 재사용하는 멀티스테이지가
이상적:

```dockerfile
FROM raganything:local AS base
COPY raganything_mcp ./raganything_mcp
RUN uv pip install --system fastmcp
EXPOSE 8001
CMD ["python", "-m", "raganything_mcp.server", \
     "--host", "0.0.0.0", "--port", "8001", "--path", "/mcp"]
```

`raganything:local` 이 먼저 빌드되어 있어야 한다 (compose 의 build order 로
강제).

## compose.yaml 추가 골격

```yaml
  raganything-mcp-native:
    build:
      context: .
      dockerfile: Dockerfile.mcp.native
    image: raganything-mcp-native:local
    container_name: raganything-mcp-native
    ports:
      - "127.0.0.1:8001:8001"   # localhost only
    env_file:
      - .env
    environment:
      NEO4J_URI: bolt://neo4j:7687
      QDRANT_URL: http://qdrant:6333
      # raganything 본체와 같은 working dir 공유 (인덱스 재사용)
      WORKING_DIR: /app/rag_storage
    volumes:
      - ./rag_storage:/app/rag_storage
      - ./inputs:/app/inputs
      - ./output:/app/output
      - ./tiktoken_cache:/app/tiktoken_cache
      - ${HF_HOME_HOST:-~/.cache/huggingface}:/root/.cache/huggingface
    depends_on:
      neo4j:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      raganything:
        condition: service_started
```

raganything 본체와 **동일한 `rag_storage` 볼륨을 공유**하여 인덱스/캐시 재사용.
다만 LightRAG 내부 SQLite/JSON 상태 파일에 동시 쓰기 락이 있을 수 있으므로,
초기 구현은 **MCP 측을 read/query 전용**으로 시작하고 `process_document_complete`
같은 쓰기 작업은 raganything 본체 컨테이너에서 수행하는 것이 안전. 동시 쓰기를
허용하려면 LightRAG storage layer 의 락 동작 검증 필요.

## RAGAnything 초기화 비용

`RAGAnything()` 생성 시 LightRAG 초기화(임베딩 모델 로드, Neo4j/Qdrant 연결)가
일어난다. MCP 서버 프로세스는 **기동 시 1회만** 초기화하고 module-global 인스턴스를
재사용해야 한다 (`server.py` 의 lifespan 훅에서 `await rag._ensure_lightrag_initialized()`).

## MCP 클라이언트 등록 (Phase 2 완료 후)

```json
{
  "mcpServers": {
    "lightrag": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    },
    "raganything": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

에이전트는 일반 RAG 질의는 `lightrag`, 멀티모달/문서 인덱싱은 `raganything` 으로
호출 분기. 두 MCP 모두 같은 backing store 를 보므로 데이터 일관성은 유지된다.

## 참고: lightrag-mcp 코드 구조

`shemhamforash23/lightrag-mcp` (master) 의 레퍼런스 패턴:

- `src/lightrag_mcp/main.py` — argparse + FastMCP 인스턴스 생성 + transport 분기
- 각 tool 은 `@mcp.tool()` 데코레이터 + httpx.AsyncClient 로 lightrag-server 호출
- `--mcp-stateless-http`, `--mcp-json-response` 플래그로 streamable-http 동작 미세조정

Phase 2 는 httpx 호출 부분을 `await raganything.aquery_with_multimodal(...)` 같은
직접 호출로 치환하는 형태가 됨.

## 미해결 사항 (구현 전 결정 필요)

1. **동시 쓰기 안전성** — `process_document_complete` 를 MCP 에서 트리거할 경우
   raganything 본체 컨테이너의 lightrag-server 와의 storage 락 충돌 검증.
   문제 시 MCP 측은 read-only, 또는 lightrag-server REST 의 `/documents/upload`
   엔드포인트를 프록시하는 형태로 우회.
2. **VLM 호출 비용** — `aquery_vlm_enhanced` 는 vision 모델 호출이 추가됨.
   에이전트가 무절제하게 부르면 비용 폭증. tool description 에 비용 경고 명시.
3. **fastmcp vs mcp SDK** — 의존성 무게/업데이트 빈도 비교 후 선택.
4. **인증 헤더 형식** — Phase 1 lightrag-mcp 와 동일하게 `X-API-Key` 헤더 또는
   Bearer 토큰 중 어느 쪽으로 통일할지.

## 작업 순서 (실행 시)

1. `raganything_mcp/` 패키지 작성 (server, tools, config)
2. read-only 툴(`rag_query_multimodal`, `rag_query_vlm_enhanced`, `rag_doc_status`)
   먼저 구현
3. 로컬에서 stdio transport 로 단위 동작 검증
4. `Dockerfile.mcp.native` + compose 서비스 추가
5. streamable-http 로 `127.0.0.1:8001/mcp` 노출 검증
6. 동시 쓰기 안전성 검증 후 `rag_process_document`, `rag_insert_content_list`
   추가
