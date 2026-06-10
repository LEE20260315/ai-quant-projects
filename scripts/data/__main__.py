#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts.data 包入口"""
from .download_futures_continuous import main as download_main
from .verify_cta_research import main as verify_main

if __name__ == "__main__":
    import sys
    print("Usage:")
    print("  python -m scripts.data download --start 2024-01-01")
    print("  python -m scripts.data verify")
    sys.exit(0)
