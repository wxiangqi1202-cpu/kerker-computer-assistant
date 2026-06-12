#!/bin/bash
set -e

# ─── 颜色 ───
if [ -t 1 ]; then
    BOLD='\033[1m' DIM='\033[2m' CYAN='\033[36m'
    GREEN='\033[32m' RED='\033[31m' YELLOW='\033[33m' RESET='\033[0m'
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

# ─── 配置（发布时修改） ───
VERSION="0.2.0"
GITEE_USER="wxiangqi1202"
GITEE_REPO="kerker"
INSTALL_DIR="$HOME/.kerker"
BIN_DIR="$HOME/.local/bin"

# ─── 系统和架构检测 ───
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin*)  PLATFORM="macos";;
    Linux*)   PLATFORM="linux";;
    *) fail "暂不支持 $OS，Windows 请使用 install.ps1";;
esac

case "$ARCH" in
    x86_64|amd64) ARCH="x86_64";;
    arm64|aarch64) ARCH="arm64";;
    *) fail "暂不支持架构: $ARCH";;
esac

info "系统: ${BOLD}$PLATFORM-$ARCH${RESET}"

# ─── 下载二进制 ───
FILENAME="kerker-${PLATFORM}-${ARCH}"
DOWNLOAD_URL="https://gitee.com/${GITEE_USER}/${GITEE_REPO}/releases/download/v${VERSION}/${FILENAME}"

info "下载 KerKer v${VERSION}..."

mkdir -p "$INSTALL_DIR" "$BIN_DIR"
TARGET="$INSTALL_DIR/kerker"

if command -v curl &> /dev/null; then
    HTTP_CODE=$(curl -fSL --progress-bar -w "%{http_code}" "$DOWNLOAD_URL" -o "$TARGET" 2>/dev/null) || true
    if [ ! -s "$TARGET" ]; then
        fail "下载失败 (HTTP $HTTP_CODE)，请检查网络或版本号"
    fi
elif command -v wget &> /dev/null; then
    wget -q --show-progress "$DOWNLOAD_URL" -O "$TARGET" || fail "下载失败，请检查网络"
else
    fail "需要 curl 或 wget"
fi

chmod +x "$TARGET"
ok "下载完成 ($(du -h "$TARGET" | cut -f1))"

# ─── 链接到 PATH ───
ln -sf "$TARGET" "$BIN_DIR/kerker"

if ! echo "$PATH" | tr ':' '\n' | grep -q "^$BIN_DIR$"; then
    warn "$BIN_DIR 不在 PATH 中"

    SHELL_NAME="$(basename "$SHELL")"
    case "$SHELL_NAME" in
        zsh)  RC="$HOME/.zshrc";;
        bash) RC="$HOME/.bashrc";;
        *)    RC="";;
    esac

    if [ -n "$RC" ] && [ -f "$RC" ]; then
        if ! grep -q '.local/bin' "$RC" 2>/dev/null; then
            printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
            ok "已添加到 $RC（重启终端生效）"
        fi
    else
        printf "  请手动添加: ${CYAN}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}\n"
    fi
fi

printf "\n"
printf "  ${GREEN}${BOLD}安装成功！${RESET}\n"
printf "\n"
printf "  ${BOLD}使用:${RESET}  ${CYAN}kerker${RESET}\n"
printf "  ${DIM}首次启动自动引导 API Key 配置${RESET}\n"
printf "\n"
