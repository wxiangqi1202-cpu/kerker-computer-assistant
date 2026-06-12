#!/bin/bash
# KerKer 构建脚本 — 使用 PyInstaller 打包为单文件可执行程序
# 用法: ./build.sh
# 产出: dist/kerker (macOS/Linux) 或 dist/kerker.exe (Windows)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ╻╻┏ ┏━╸┏━┓╻┏ ┏━╸┏━┓  Build"
echo "  ┣┻┓┣╸ ┣┳┛┣┻┓┣╸ ┣┳┛"
echo "  ╹ ╹┗━╸╹┗╸╹ ╹┗━╸╹┗╸"
echo ""

# 确保 PyInstaller 已安装
if ! python3 -m PyInstaller --version &> /dev/null; then
    echo "  → 安装 PyInstaller..."
    pip3 install pyinstaller --quiet
fi

# 清理旧构建
rm -rf build/ dist/ *.spec

# 检测平台
OS="$(uname -s)"
case "$OS" in
    Darwin*)  PLATFORM="macos";;
    Linux*)   PLATFORM="linux";;
    MINGW*|MSYS*) PLATFORM="windows";;
    *)        PLATFORM="unknown";;
esac

echo "  → 平台: $PLATFORM"
echo "  → 开始打包..."

# PyInstaller 打包
python3 -m PyInstaller \
    --onefile \
    --name kerker \
    --clean \
    --noconfirm \
    --add-data "core:core" \
    --add-data "cli:cli" \
    --add-data "display:display" \
    --add-data "skills:skills" \
    --add-data "agents:agents" \
    --hidden-import=openai \
    --hidden-import=rich \
    --hidden-import=prompt_toolkit \
    --hidden-import=requests \
    --hidden-import=bs4 \
    main.py

# 重命名产出文件带平台标识
ARCH="$(uname -m)"
if [ "$PLATFORM" = "windows" ]; then
    OUTPUT="dist/kerker-${PLATFORM}-${ARCH}.exe"
    mv dist/kerker.exe "$OUTPUT" 2>/dev/null || true
else
    OUTPUT="dist/kerker-${PLATFORM}-${ARCH}"
    mv dist/kerker "$OUTPUT" 2>/dev/null || true
    chmod +x "$OUTPUT"
fi

# 清理中间文件
rm -rf build/ *.spec

echo ""
echo "  ✓ 打包完成: $OUTPUT"
echo "  大小: $(du -h "$OUTPUT" | cut -f1)"
echo ""
echo "  下一步: 将 $OUTPUT 上传到 Gitee Release"
echo ""
