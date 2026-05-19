#!/bin/bash
set -e

echo ""
echo "  ╭─────────────────────────────────╮"
echo "  │  KerKer 安装脚本                │"
echo "  │  Computational Agent Framework  │"
echo "  ╰─────────────────────────────────╯"
echo ""

if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "  ✗ 未找到 Python，请先安装 Python 3.9+"
    exit 1
fi

PY=$(command -v python3 || command -v python)
echo "  使用 Python: $PY"

if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
    echo "  ✗ 未找到 pip，请先安装 pip"
    exit 1
fi

PIP=$(command -v pip3 || command -v pip)

INSTALL_DIR="$HOME/.kerker/src"

if [ -d "$INSTALL_DIR" ]; then
    echo "  更新已有安装..."
    cd "$INSTALL_DIR"
    git pull --quiet
else
    echo "  下载 KerKer..."
    git clone --quiet https://github.com/wxiangqi1202-cpu/kerker-computer-assistant.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "  安装依赖..."
$PIP install --quiet -e .

echo ""
echo "  ✓ 安装完成！"
echo ""
echo "  输入 kerker 启动"
echo ""
