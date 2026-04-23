#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# start.sh — RAG-Anything + LM Studio (host) TUI launcher
#
# 호스트에서 실행. LM Studio는 네이티브, RAG-Anything은 Podman 컨테이너.
# ──────────────────────────────────────────────────────────────────────
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SERVICE="raganything"
CONTAINER="raganything-lmstudio"
IMAGE="raganything-lmstudio:local"
WEB_UI_URL="http://localhost:9621"
LM_STUDIO_URL="http://localhost:1234/v1"  # 실제 값은 아래에서 LLM_BINDING_HOST 기반으로 재계산

# ── Colors ────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    C_RESET="\033[0m"; C_BOLD="\033[1m"; C_DIM="\033[2m"
    C_RED="\033[31m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"
    C_BLUE="\033[34m"; C_CYAN="\033[36m"
else
    C_RESET=""; C_BOLD=""; C_DIM=""
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""
fi

ok()    { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn()  { printf "${C_YELLOW}!${C_RESET} %s\n" "$*"; }
err()   { printf "${C_RED}✗${C_RESET} %s\n" "$*"; }
info()  { printf "${C_CYAN}·${C_RESET} %s\n" "$*"; }
hdr()   { printf "\n${C_BOLD}${C_BLUE}== %s ==${C_RESET}\n" "$*"; }

pause() { printf "\n${C_DIM}[Enter] 계속...${C_RESET}"; read -r _; }

# ── Host cache paths (resolved before compose reads them) ─────────────
# podman-compose 1.5.0 은 compose.yaml 의 중첩 ${...} 치환을 잘못 파싱하므로
# 호스트 경로를 셸에서 먼저 전개해서 export 한다.
export HF_HOME_HOST="${HF_HOME_HOST:-$HOME/.cache/huggingface}"
export MODELSCOPE_CACHE_HOST="${MODELSCOPE_CACHE_HOST:-$HOME/.cache/modelscope}"
mkdir -p "$HF_HOME_HOST" "$MODELSCOPE_CACHE_HOST"

# ── LM Studio defaults (overrides any .env Ollama settings) ───────────
# 셸 export 는 compose 의 .env 파일 로드보다 우선 적용된다.
# 기존 셸 환경에 값이 이미 있으면 그대로 존중.
# lightrag-server 의 --llm-binding 선택지에 lmstudio 가 없어 openai 로 연결 (LM Studio 는 OpenAI 호환)
export LLM_BINDING="${LLM_BINDING:-openai}"
export LLM_MODEL="${LLM_MODEL:-qwen/qwen3.6-27b}"
export LLM_BINDING_HOST="${LLM_BINDING_HOST:-http://host.docker.internal:1234/v1}"
export LLM_BINDING_API_KEY="${LLM_BINDING_API_KEY:-lm-studio}"
export EMBEDDING_BINDING="${EMBEDDING_BINDING:-openai}"
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-qwen3-embedding-0.6b}"
export EMBEDDING_BINDING_HOST="${EMBEDDING_BINDING_HOST:-http://host.docker.internal:1234/v1}"
export EMBEDDING_BINDING_API_KEY="${EMBEDDING_BINDING_API_KEY:-lm-studio}"

# LM_STUDIO_URL 은 컨테이너 기준(host.docker.internal)이므로,
# 호스트에서 curl 로 상태 확인할 때는 localhost 로 치환
LM_STUDIO_URL_HOST="${LLM_BINDING_HOST/host.docker.internal/localhost}"

# ── Compose wrapper ───────────────────────────────────────────────────
compose() {
    if podman compose version >/dev/null 2>&1; then
        podman compose "$@"
    elif command -v podman-compose >/dev/null 2>&1; then
        podman-compose "$@"
    else
        err "podman compose / podman-compose 를 찾을 수 없습니다."
        return 1
    fi
}

# ── Preflight ─────────────────────────────────────────────────────────
preflight() {
    command -v podman >/dev/null 2>&1 || { err "podman 이 설치돼 있지 않습니다."; exit 1; }

    # macOS: podman machine 이 필요할 수 있음
    if [[ "$(uname -s)" == "Darwin" ]]; then
        if ! podman info >/dev/null 2>&1; then
            warn "Podman machine 이 실행 중이 아닐 수 있습니다. 'podman machine start' 를 먼저 실행하세요."
        fi
    fi

    [[ -f "$SCRIPT_DIR/compose.yaml" ]] || { err "compose.yaml 이 없습니다: $SCRIPT_DIR"; exit 1; }
}

# ── Actions ───────────────────────────────────────────────────────────
status() {
    hdr "컨테이너 상태"
    if podman ps -a --filter "name=^${CONTAINER}$" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" \
            | tail -n +1 | grep -q "$CONTAINER"; then
        podman ps -a --filter "name=^${CONTAINER}$" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        info "컨테이너가 아직 생성되지 않았습니다."
    fi

    hdr "이미지"
    if podman images --format "{{.Repository}}:{{.Tag}}" | grep -qx "$IMAGE"; then
        podman images --filter "reference=${IMAGE}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.Created}}"
    else
        info "이미지가 아직 빌드되지 않았습니다. (메뉴 8번)"
    fi
}

check_lmstudio() {
    hdr "LM Studio 연결 확인 ($LM_STUDIO_URL_HOST)"
    if ! curl -sf --max-time 3 "$LM_STUDIO_URL_HOST/models" >/dev/null; then
        err "LM Studio Local Server 에 접속할 수 없습니다."
        echo
        echo "  1) LM Studio 실행 중인지 확인"
        echo "  2) Developer 탭 → Start Server (포트 1234)"
        echo "  3) 모델 2개 로드:"
        echo "       - lmstudio-community/qwen/qwen3.6-27b-4bit"
        echo "       - text-embedding-qwen3-embedding-0.6b"
        return 1
    fi
    ok "LM Studio 응답 정상"
    echo
    info "로드된 모델:"
    curl -s "$LM_STUDIO_URL_HOST/models" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for m in d.get('data', []):
    print(f'   · {m[\"id\"]}')
" 2>/dev/null || curl -s "$LM_STUDIO_URL_HOST/models"
}

start() {
    hdr "컨테이너 시작 (detached)"
    check_lmstudio || { warn "LM Studio 가 준비 안 됐지만 그대로 진행합니다."; }
    # 이미지를 재빌드했을 때 기존 컨테이너가 그대로 남아있으면 옛 CMD 로 기동되므로
    # 이미지 id 가 바뀌었는지 확인 후 필요 시 강제 재생성
    local current_img running_img
    current_img=$(podman image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)
    running_img=$(podman inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true)
    if [[ -n "$current_img" && -n "$running_img" && "$current_img" != "$running_img" ]]; then
        info "이미지가 갱신되어 컨테이너를 재생성합니다."
        compose down || true
    fi
    compose up -d
    ok "시작 완료."
    echo
    info "웹 UI:  ${WEB_UI_URL}   (메뉴 14번으로 브라우저 열기)"
    info "로그:   메뉴 5번"
}

stop() {
    hdr "컨테이너 중단"
    compose stop
    ok "중단 완료."
}

restart() {
    hdr "컨테이너 재시작"
    compose restart
    ok "재시작 완료."
}

logs() {
    hdr "로그 (Ctrl-C 로 종료)"
    compose logs -f --tail=100 "$SERVICE" || true
}

shell() {
    hdr "컨테이너 셸 진입"
    if podman ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -qx "$CONTAINER"; then
        podman exec -it "$CONTAINER" bash
    else
        info "컨테이너가 실행 중이 아닙니다. 일회성 컨테이너로 셸을 엽니다."
        compose run --rm "$SERVICE" bash
    fi
}

run_example() {
    hdr "예제 실행 (examples/lmstudio_integration_example.py)"
    check_lmstudio || return 1
    compose run --rm "$SERVICE" python examples/lmstudio_integration_example.py
}

build() {
    hdr "이미지 빌드"
    compose build
    ok "빌드 완료."
}

rebuild() {
    hdr "이미지 재빌드 (--no-cache)"
    compose build --no-cache
    ok "재빌드 완료."
}

clean() {
    hdr "컨테이너/네트워크 제거 (볼륨·이미지는 유지)"
    printf "${C_YELLOW}실행 중인 컨테이너와 네트워크를 제거합니다. 계속? [y/N] ${C_RESET}"
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]] || { info "취소됨."; return; }
    compose down
    ok "정리 완료. (볼륨·이미지 유지)"
}

nuke() {
    hdr "완전 초기화 (이미지·볼륨 포함)"
    printf "${C_RED}${C_BOLD}이미지와 rag_storage_lmstudio / output_lmstudio 내부 데이터가 남아있을 수 있습니다.${C_RESET}\n"
    printf "${C_YELLOW}compose down + 이미지 제거를 진행합니다. 계속? [y/N] ${C_RESET}"
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]] || { info "취소됨."; return; }
    compose down -v || true
    podman rmi -f "$IMAGE" || true
    ok "초기화 완료."
}

open_browser() {
    hdr "브라우저에서 웹 UI 열기"
    if ! podman ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
        err "컨테이너가 실행 중이 아닙니다. 먼저 메뉴 2 로 시작하세요."
        return 1
    fi

    info "상태 확인: $WEB_UI_URL"
    local retries=10
    while (( retries > 0 )); do
        if curl -sf --max-time 2 "$WEB_UI_URL/health" >/dev/null 2>&1 \
                || curl -sf --max-time 2 "$WEB_UI_URL/" >/dev/null 2>&1; then
            ok "웹 UI 응답 확인"
            break
        fi
        printf "."
        sleep 1
        retries=$((retries - 1))
    done
    [[ $retries -eq 0 ]] && warn "아직 준비 중일 수 있습니다. 브라우저에서 새로고침 하세요."

    if [[ "$(uname -s)" == "Darwin" ]]; then
        open "$WEB_UI_URL"
        ok "브라우저에서 $WEB_UI_URL 를 열었습니다."
    else
        info "다음 주소를 직접 여세요: $WEB_UI_URL"
    fi
}

install_corp_ca() {
    hdr "사내망 CA 를 Podman machine 에 설치"
    echo "Zscaler/Netskope/Bluecoat 등 사내망 SSL 검사 프록시 CA 를 찾아"
    echo "Podman machine VM 의 트러스트 스토어와 registry cert 디렉토리에 설치합니다."
    echo
    info "1) macOS 시스템 키체인에서 CA 후보 추출..."
    local tmp_ca="/tmp/corp-ca.pem"
    : > "$tmp_ca"
    for name in Zscaler Netskope Bluecoat "Palo Alto" Fortinet; do
        security find-certificate -a -c "$name" -p /Library/Keychains/System.keychain 2>/dev/null >> "$tmp_ca" || true
    done
    local count
    count=$(grep -c 'BEGIN CERT' "$tmp_ca" || echo 0)
    if [[ "$count" -eq 0 ]]; then
        err "시스템 키체인에서 사내망 CA 를 찾지 못했습니다."
        echo "   키워드(Zscaler/Netskope/Bluecoat/Palo Alto/Fortinet) 외라면"
        echo "   먼저 Keychain Access 에서 Root CA 를 System 에 추가하세요."
        return 1
    fi
    ok "$count 개 CA 추출: $tmp_ca"
    security find-certificate -a -c Zscaler -p /Library/Keychains/System.keychain 2>/dev/null \
        | openssl x509 -noout -subject 2>/dev/null | head -3
    echo

    info "2) Podman machine VM 으로 복사..."
    podman machine ssh "cat > /tmp/corp-ca.pem" < "$tmp_ca" || {
        err "podman machine ssh 실패. 'podman machine start' 로 먼저 VM 을 시작하세요."
        return 1
    }

    info "3) VM 시스템 트러스트 + Docker Hub registry cert 디렉토리에 설치..."
    podman machine ssh "\
        sudo cp /tmp/corp-ca.pem /etc/pki/ca-trust/source/anchors/corp-ca.pem && \
        sudo update-ca-trust && \
        for d in docker.io auth.docker.io registry-1.docker.io; do \
            sudo mkdir -p /etc/containers/certs.d/\$d && \
            sudo cp /tmp/corp-ca.pem /etc/containers/certs.d/\$d/ca.crt; \
        done && \
        echo OK" || { err "VM 내부 설치 실패"; return 1; }

    info "4) TLS 확인..."
    if podman machine ssh "curl -sSI https://auth.docker.io/ >/dev/null 2>&1"; then
        ok "VM 에서 TLS 검증 성공"
    else
        warn "curl 은 실패했지만 podman pull 은 될 수 있습니다 (다음 단계에서 확인)."
    fi

    if podman pull docker.io/library/hello-world:latest >/dev/null 2>&1; then
        ok "podman pull 테스트 성공"
    else
        err "podman pull 테스트 실패. 다른 프록시/CA 가 필요할 수 있습니다."
        return 1
    fi
}

# ── Menu ──────────────────────────────────────────────────────────────
menu() {
    clear
    printf "${C_BOLD}${C_CYAN}"
    cat <<'BANNER'
┌────────────────────────────────────────────────┐
│  RAG-Anything + LM Studio (host) 관리 콘솔    │
└────────────────────────────────────────────────┘
BANNER
    printf "${C_RESET}"
    printf "${C_DIM}LM Studio: %s${C_RESET}\n" "$LM_STUDIO_URL_HOST"
    printf "${C_DIM}Web UI:    %s${C_RESET}\n" "$WEB_UI_URL"
    printf "${C_DIM}Container: %s${C_RESET}\n\n" "$CONTAINER"

    # 실시간 상태 표시
    local running_state
    if podman ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
        running_state="${C_GREEN}● running${C_RESET}"
    elif podman ps -a --filter "name=^${CONTAINER}$" --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
        running_state="${C_YELLOW}○ stopped${C_RESET}"
    else
        running_state="${C_DIM}· not created${C_RESET}"
    fi
    printf "상태: %b\n\n" "$running_state"

    echo "  1)  상태 확인"
    echo "  2)  시작 (detached)"
    echo "  3)  중단"
    echo "  4)  재시작"
    echo "  5)  로그 tail"
    echo "  6)  셸 진입"
    echo "  7)  예제 실행 (1회성)"
    echo "  8)  이미지 빌드"
    echo "  9)  이미지 재빌드 (--no-cache)"
    echo "  10) LM Studio 연결 확인"
    echo "  11) 컨테이너 제거 (down)"
    echo "  12) 완전 초기화 (down -v + rmi)"
    echo "  13) 사내망 CA 설치 (Podman machine)"
    echo "  14) 브라우저에서 웹 UI 열기"
    echo "  0)  종료"
    echo
    printf "${C_BOLD}선택: ${C_RESET}"
}

dispatch() {
    case "$1" in
        1)  status ;;
        2)  start ;;
        3)  stop ;;
        4)  restart ;;
        5)  logs ;;
        6)  shell ;;
        7)  run_example ;;
        8)  build ;;
        9)  rebuild ;;
        10) check_lmstudio ;;
        11) clean ;;
        12) nuke ;;
        13) install_corp_ca ;;
        14) open_browser ;;
        0)  echo "bye."; exit 0 ;;
        "") return 0 ;;
        *)  err "알 수 없는 선택: $1" ;;
    esac
}

main() {
    preflight
    while true; do
        menu
        read -r choice
        echo
        dispatch "$choice" || true
        pause
    done
}

main "$@"
