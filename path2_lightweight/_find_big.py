# -*- coding: utf-8 -*-
# 列出 C:\\Users\\MR.Dong 下占用空间最大的目录
import os
import sys

def dir_size(path):
    total = 0
    try:
        for root, dirs, files in os.walk(path, topdown=True):
            depth = root.count(os.sep) - path.count(os.sep)
            if depth > 4:
                dirs.clear()
                continue
            for f in files:
                try:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total

base = r"C:\Users\MR.Dong"
if not os.path.exists(base):
    print(f"ERR: {base} not found")
    sys.exit(1)

sizes = []
for entry in os.listdir(base):
    full = os.path.join(base, entry)
    if os.path.isdir(full):
        s = dir_size(full)
        sizes.append((s, entry))
    elif os.path.isfile(full):
        try:
            s = os.path.getsize(full)
        except OSError:
            s = 0
        sizes.append((s, entry))

sizes.sort(reverse=True)
print("Top 15 占用空间最大的项 (C:\\Users\\MR.Dong):")
for s, name in sizes[:15]:
    print(f"  {s/1024/1024/1024:8.2f} GB  {name}")
