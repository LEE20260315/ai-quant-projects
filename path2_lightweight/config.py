#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _find_data_dir():
    # 使用项目本地的数据目录
    local_data_dir = os.path.join(PROJECT_ROOT, 'data', 'futures')
    os.makedirs(local_data_dir, exist_ok=True)
    return local_data_dir


FUTURES_DATA_DIR = _find_data_dir()

PYTHON_EXE = os.environ.get('PYTHON_EXE', 'python')