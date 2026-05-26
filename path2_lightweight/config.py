#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _find_data_dir():
    env_dir = os.environ.get('FUTURES_DATA_DIR', '')
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    fallback = os.path.join(PROJECT_ROOT, 'data', 'futures')
    os.makedirs(fallback, exist_ok=True)
    return os.path.abspath(fallback)


FUTURES_DATA_DIR = _find_data_dir()

PYTHON_EXE = os.environ.get('PYTHON_EXE', 'python')