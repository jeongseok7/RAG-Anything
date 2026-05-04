# Claude Code 에 RAG-Anything MCP 연결하기

Phase 1 컨테이너(`lightrag-mcp`)는 `http://127.0.0.1:8000/mcp` 에 streamable-http
transport 로 떠 있다. 이 문서는 Claude Code(CLI) 에 해당 서버를 등록하는 절차다.

## 0. 사전 확인

```bash
# 컨테이너 기동
podman compose up -d lightrag-mcp

# 헬스 확인 — 405/406/200 중 하나면 정상 (HEAD/GET 거부는 정상 동작)
curl -i http://127.0.0.1:8000/mcp

# 컨테이너 로그
podman logs -f raganything-mcp
```

응답이 없거나 connection refused 면 등록해도 의미 없으니 `podman ps` 로
`raganything-mcp` 가 Up 상태인지 먼저 확인.

## 1. 등록 (CLI 방식, 권장)

`.env` 의 `LIGHTRAG_API_KEY` 와 동일한 값을 헤더로 전달한다.

```bash
claude mcp add --transport http raganything http://127.0.0.1:8000/mcp \
  --header "X-API-Key: $LIGHTRAG_API_KEY"
```

scope 미지정 시 기본 `local` (현재 프로젝트, 본인만). 다른 프로젝트에서도 쓰려면:

```bash
claude mcp add --transport http raganything http://127.0.0.1:8000/mcp \
  --header "X-API-Key: $LIGHTRAG_API_KEY" \
  -s user
```

> **Scope 선택 가이드**
> - `local` (기본): 현재 프로젝트, 개인용 — `~/.claude.json` 의 프로젝트 섹션
> - `user`: 모든 프로젝트, 개인용 — `~/.claude.json` 사용자 섹션
> - `project`: 팀 공유 — 리포 루트 `.mcp.json` (커밋됨)
>
> URL 이 `127.0.0.1` 인 로컬 전용 설정이라 **`project` scope 는 권장하지 않는다.**
> 팀원도 본인 머신에서 같은 compose 를 띄워야 동작하므로, 각자 `local` 또는 `user`
> 로 등록하는 것이 자연스럽다.

## 2. 등록 (JSON 직접 편집 방식)

CLI 대신 직접 작성하려면, scope 에 따라 아래 위치의 파일을 편집:

| Scope | 파일 | 비고 |
|---|---|---|
| `local` | `~/.claude.json` | `projects[<현재경로>].mcpServers` 에 추가 |
| `user` | `~/.claude.json` | 최상위 `mcpServers` 에 추가 |
| `project` | `<repo>/.mcp.json` | 신규 파일 — 권장 X (위 가이드 참고) |

JSON 스키마 (어느 위치든 동일):

```json
{
  "mcpServers": {
    "raganything": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "X-API-Key": "your-secure-api-key-here"
      }
    }
  }
}
```

> `type` 필드는 `"http"` 가 streamable-http 의식별자다. (`"sse"` 는 deprecated 된
> 별도 transport. `"streamable-http"` 라는 값은 사용하지 않음.)

## 3. 검증

```bash
# CLI 에서 등록 확인
claude mcp list
claude mcp get raganything
```

Claude Code TUI 안에서:

```
/mcp
```

`raganything` 항목이 `connected` 로 보이면 성공. `failed` / `pending` 이면 4번 항목.

실제 도구 호출 테스트 — Claude Code 세션에서 자연어로:

> "raganything 으로 'hello' 라는 쿼리를 mix mode 로 실행해 결과 보여줘"

또는 직접 툴 이름(`mcp__raganything__query_document` 같은 형태)을 호출하도록 요청.

## 4. 트러블슈팅

| 증상 | 확인 사항 |
|---|---|
| `/mcp` 에서 `failed` | 1) `curl http://127.0.0.1:8000/mcp` 응답 확인 2) `podman logs raganything-mcp` 에러 확인 |
| `401 Unauthorized` | 헤더의 `X-API-Key` 값과 `.env` 의 `LIGHTRAG_API_KEY` 일치 여부 |
| `connection refused` | `podman ps` 로 컨테이너 Up 상태인지 / `127.0.0.1:8000` 포트 LISTEN 확인: `lsof -iTCP:8000 -sTCP:LISTEN` |
| 등록은 됐는데 툴이 안 보임 | Claude Code 재시작 (TUI 종료 후 `claude` 재실행). MCP 서버는 세션 시작 시 1회 연결 |
| lightrag-server 자체 5xx | `podman logs raganything` (MCP 가 정상이어도 backing API 가 죽었을 수 있음) |
| `MCP_TIMEOUT` 관련 에러 | 환경변수 `MCP_TIMEOUT=30000` (ms) 으로 늘려 재시작 |

세션 안에서 raw 로그를 더 보고 싶으면 Claude Code 를 디버그 모드로:

```bash
claude --debug
```

`/mcp` 출력에 server 측 stderr 가 따라온다.

## 5. 제거 / 갱신

```bash
# 제거
claude mcp remove raganything            # local scope
claude mcp remove raganything -s user    # user scope

# 헤더/URL 변경 — 제거 후 재등록 권장
```

## 6. Phase 2 추가 시

`raganything-mcp-native` 가 `127.0.0.1:8001/mcp` 로 추가되면 같은 방식으로 한 번 더
등록한다. 이름만 다르게 (`raganything-native` 등):

```bash
claude mcp add --transport http raganything-native http://127.0.0.1:8001/mcp \
  --header "X-API-Key: $LIGHTRAG_API_KEY"
```

두 서버를 동시에 등록해 두면 Claude Code 가 일반 RAG 질의/KG 조작은 `raganything`
(lightrag-mcp), 멀티모달/문서 인덱싱은 `raganything-native` 로 자동 분기 가능.

---

**참고**
- 공식 문서: https://docs.claude.com/en/docs/claude-code/mcp
- Phase 1 구성: `compose.yaml` 의 `lightrag-mcp` 서비스, `Dockerfile.mcp`
- Phase 2 청사진: `docs/mcp_phase2_raganything_native.md`
