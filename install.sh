#!/bin/bash
set -e

# ─── 颜色定义 ───
if [ -t 1 ]; then
    BOLD='\033[1m'
    DIM='\033[2m'
    CYAN='\033[36m'
    GREEN='\033[32m'
    RED='\033[31m'
    YELLOW='\033[33m'
    RESET='\033[0m'
else
    BOLD="" DIM="" CYAN="" GREEN="" RED="" YELLOW="" RESET=""
fi

info()  { printf "  ${CYAN}→${RESET} %s\n" "$1"; }
ok()    { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
warn()  { printf "  ${YELLOW}!${RESET} %s\n" "$1"; }
fail()  { printf "  ${RED}✗${RESET} %s\n" "$1"; exit 1; }

# ─── Banner ───
printf "\n"
printf "  ${BOLD}${CYAN}╻╻┏ ┏━╸┏━┓╻┏ ┏━╸┏━┓${RESET}\n"
printf "  ${BOLD}${CYAN}┣┻┓┣╸ ┣┳┛┣┻┓┣╸ ┣┳┛${RESET}\n"
printf "  ${BOLD}${CYAN}╹ ╹┗━╸╹┗╸╹ ╹┗━╸╹┗╸${RESET}\n"
printf "  ${DIM}Computational Agent Framework${RESET}\n"
printf "\n"

# ─── 系统检测 ───
OS="$(uname -s)"
case "$OS" in
    Linux*)   PLATFORM="Linux";;
    Darwin*)  PLATFORM="macOS";;
    MINGW*|MSYS*|CYGWIN*) PLATFORM="Windows(Git Bash)";;
    *)        PLATFORM="Unknown";;
esac
info "系统: ${BOLD}$PLATFORM${RESET}"

# ─── Python ───
if command -v python3 &> /dev/null; then
    PY="python3"
elif command -v python &> /dev/null; then
    PY="python"
else
    fail "未找到 Python，请先安装 Python 3.9+ (brew install python3 / apt install python3)"
fi

PY_VERSION=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PY -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PY -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    fail "Python 版本过低: $PY_VERSION (需要 >= 3.9)"
fi
ok "Python $PY_VERSION"

# ─── pip ───
if command -v pip3 &> /dev/null; then
    PIP="pip3"
elif command -v pip &> /dev/null; then
    PIP="pip"
elif $PY -m pip --version &> /dev/null; then
    PIP="$PY -m pip"
else
    fail "未找到 pip (尝试: $PY -m ensurepip --upgrade)"
fi
ok "pip 就绪"

# ─── git ───
if ! command -v git &> /dev/null; then
    fail "未找到 git，请先安装 git"
fi
ok "git 就绪"

printf "\n"

# ─── 克隆/更新 ───
REPO_URL="https://github.com/wxiangqi1202-cpu/kerker-computer-assistant.git"
INSTALL_DIR="$HOME/.kerker/src"

clone_repo() {
    # 强制 HTTP/1.1 解决国内 HTTP2 framing 错误
    git -c http.version=HTTP/1.1 clone --quiet --depth 1 "$REPO_URL" "$INSTALL_DIR"
}

if [ -d "$INSTALL_DIR/.git" ]; then
    info "更新已有安装..."
    cd "$INSTALL_DIR"
    git -c http.version=HTTP/1.1 pull --quiet 2>/dev/null || warn "git pull 失败，使用本地版本继续"
else
    [ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
    info "下载 KerKer..."
    if ! clone_repo 2>/dev/null; then
        warn "下载失败，尝试备用方式..."
        # 第二次尝试：关闭 HTTP/2 + 增加超时
        GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30 \
            git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 \
            clone --quiet --depth 1 "$REPO_URL" "$INSTALL_DIR" \
            || fail "下载失败，请检查网络或使用代理 (export https_proxy=...)"
    fi
    cd "$INSTALL_DIR"
fi
ok "源码就绪"

# ─── 安装依赖 ───
info "安装依赖..."
$PIP install --quiet -e . 2>/dev/null || $PY -m pip install --quiet -e .
ok "依赖安装完成"

printf "\n"

# ─── 验证 ───
if command -v kerker &> /dev/null; then
    printf "  ${GREEN}${BOLD}安装成功！${RESET}\n"
    printf "  ${DIM}路径: $(command -v kerker)${RESET}\n"
else
    printf "  ${GREEN}${BOLD}安装成功！${RESET}\n"
    warn "kerker 未在 PATH 中，可直接运行: $PY $INSTALL_DIR/main.py"
fi

printf "\n"
printf "  ${BOLD}使用方式:${RESET}\n"
printf "  ${CYAN}$ kerker${RESET}          启动交互式助手\n"
printf "  ${DIM}首次启动自动引导 API Key 配置${RESET}\n"
printf "\n"
