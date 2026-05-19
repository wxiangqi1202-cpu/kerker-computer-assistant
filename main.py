"""
KerKer —— 面向计算加速的 Agent 框架
启动: python main.py 或 kerker (pip install 后)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli.loop import main

if __name__ == "__main__":
    main()
