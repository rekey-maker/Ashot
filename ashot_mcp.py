# -*- coding: utf-8 -*-
"""Ashot MCP 宿主接入 launcher（alrec_mcp 同款）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ashot.mcp import main  # noqa: E402

if __name__ == "__main__":
    main()
