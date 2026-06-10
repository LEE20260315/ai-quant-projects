#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_data_dir():
    env_dir = os.environ.get('FUTURES_DATA_DIR', '')
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    home = os.path.expanduser('~')
    for onedrive_name in ['OneDrive', 'OneDrive - Personal', 'OneDrive - Company']:
        for folder_name in ['My Project', 'My Project1']:
            base = os.path.join(home, onedrive_name, folder_name)
            if os.path.isdir(base):
                candidate = os.path.join(base, 'cta_research', 'futures', 'continuous')
                if os.path.isdir(candidate):
                    return candidate

    fallback = os.path.join(PROJECT_ROOT, '..', 'cta_research', 'futures', 'continuous')
    return os.path.abspath(fallback)


FUTURES_DATA_DIR = _find_data_dir()

PYTHON_EXE = os.environ.get('PYTHON_EXE', 'python')