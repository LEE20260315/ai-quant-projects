# -*- coding: utf-8 -*-
# 找 AppData 下最大子目录
import os
def dir_size(path, max_depth=3, cur_depth=0):
    total = 0
    try:
        for entry in os.listdir(path):
            full = os.path.join(path, entry)
            if os.path.isfile(full):
                try: total += os.path.getsize(full)
                except OSError: pass
            elif os.path.isdir(full):
                if cur_depth < max_depth:
                    total += dir_size(full, max_depth, cur_depth + 1)
                else:
                    for r, d, f in os.walk(full):
                        for x in f:
                            try: total += os.path.getsize(os.path.join(r, x))
                            except OSError: pass
    except (OSError, PermissionError):
        pass
    return total

base = r"C:\Users\MR.Dong\AppData"
sizes = []
for entry in os.listdir(base):
    full = os.path.join(base, entry)
    if os.path.isdir(full):
        s = dir_size(full, max_depth=2)
        sizes.append((s, entry))
sizes.sort(reverse=True)
print("Top 15 AppData 占用 (depth=2):")
for s, n in sizes[:15]:
    print(f"  {s/1024/1024/1024:8.2f} GB  {n}")
