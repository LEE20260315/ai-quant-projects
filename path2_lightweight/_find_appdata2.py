# -*- coding: utf-8 -*-
import os
def dir_size(path, max_depth=2, cur_depth=0):
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

for top in ["Local", "Roaming"]:
    base = r"C:\Users\MR.Dong\AppData\\" + top
    if not os.path.isdir(base):
        continue
    print(f"\n=== AppData\\{top} (depth=2) ===")
    sizes = []
    for entry in os.listdir(base):
        full = os.path.join(base, entry)
        if os.path.isdir(full):
            s = dir_size(full, max_depth=2)
            sizes.append((s, entry))
    sizes.sort(reverse=True)
    for s, n in sizes[:15]:
        if s > 100*1024*1024:  # 只显示 >100MB
            print(f"  {s/1024/1024/1024:8.2f} GB  {n}")
