#!/bin/bash
set -e

echo ""
echo "  ╭─────────────────────────────────╮"
echo "  │  KerKer 安装脚本                │"
echo "  │  Computational Agent Framework  │"
echo "  ╰─────────────────────────────────╯"
echo ""

# ---------- 系统检测 ----------
OS="$(uname -s)"
case "$OS" in
    Linux*)   PLATFORM="Linux";;
    Darwin*)  PLATFORM="macOS";;
    MINGW*|MSYS*|CYGWIN*) PLATFORM="Windows(Git Bash)";;
    *)        PLATFORM="Unknown";;
esac
echo "  系统: $PLATFORM ($OS)"

# ---------- Python 检测 ----------
if command -v python3 &> /dev/null; then
    PY="python3"
elif command -v python &> /dev/null; then
    PY="python"
else
    echo "  ✗ 未找到 Python，请先安装 Python 3.9+"
    echo "    macOS:  brew install python3"
    echo "    Ubuntu: sudo apt install python3 python3-pip"
    exit 1
fi

PY_VERSION=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PY -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PY -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    echo "  ✗ Python 版本过低: $PY_VERSION (需要 >= 3.9)"
    exit 1
fi
echo "  Python: $PY ($PY_VERSION)"

# ---------- pip 检测 ----------
if command -v pip3 &> /dev/null; then
    PIP="pip3"
elif command -v pip &> /dev/null; then
    PIP="pip"
elif $PY -m pip --version &> /dev/null; then
    PIP="$PY -m pip"
else
    echo "  ✗ 未找到 pip，请先安装 pip"
    echo "    尝试: $PY -m ensurepip --upgrade"
    exit 1
fi
echo "  pip: $PIP"
echo ""

# ---------- git 检测 ----------
if ! command -v git &> /dev/null; then
    echo "  ✗ 未找到 git，请先安装 git"
    exit 1
fi

# ---------- 安装 ----------
INSTALL_DIR="$HOME/.kerker/src"

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  更新已有安装..."
    cd "$INSTALL_DIR"
    git pull --quiet || echo "  ⚠ git pull 失败，使用本地版本继续"
else
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
    fi
    echo "  下载 KerKer..."
    git clone --quiet --depth 1 https://github.com/wxiangqi1202-cpu/kerker-computer-assistant.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "  安装依赖..."
$PIP install --quiet -e .

# ---------- 验证安装 ----------
if command -v kerker &> /dev/null; then
    KERKER_PATH=$(command -v kerker)
    echo ""
    echo "  ✓ 安装完成！"
    echo "  路径: $KERKER_PATH"
else
    echo ""
    echo "  ✓ 安装完成！"
    echo "  ⚠ kerker 命令未在 PATH 中找到"
    echo "    可能需要: export PATH=\"\$PATH:\$($PIP show kerker 2>/dev/null | grep Location | cut -d' ' -f2)/../../../bin\""
    echo "    或者直接运行: $PY $INSTALL_DIR/main.py"
fi

echo ""
echo "  输入 kerker 启动"
echo "  首次启动会引导你完成 API Key 配置"
echo ""
