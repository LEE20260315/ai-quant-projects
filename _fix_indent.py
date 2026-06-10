"""Cleanly rewrite the ctpbee section with proper indentation."""
path = r'common\execution\ctp_broker.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the broken ctpbee section with a clean version
# Find the section bounds
start_marker = '# ctpbee 封装'
end_marker = 'def build_broker('

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx < 0 or end_idx < 0:
    print(f'ERROR: markers not found. start={start_idx}, end={end_idx}')
    exit(1)

# Find the start of the line (line beginning) for the start marker
# Go back to find the start of the line
line_start = content.rfind('\n', 0, start_idx) + 1

# Find the start of the line for end_marker
end_line_start = content.rfind('\n', 0, end_idx) + 1

print(f'ctpbee section: chars {line_start} to {end_line_start}')

# Replace this section with a clean version
# Find the header comment lines before the section
# Look back from start_marker for the first non-blank line
# The structure should be:
# # ============================================================
# # ctpbee 封装 —— 仅在 ctpbee 可用时真正启用 (旧, 已被 openctp-ctp 替代)
# # ============================================================
# try:
#     from ctpbee import CtpBee, OrderRequest as CtpbeeOrderRequest
#     _CTPBEE_OK = True
# except Exception as e:
#     _CTPBEE_OK = False
#     _CTPBEE_IMPORT_ERR = e

# For now, just delete the entire ctpbee section and the broken OpenCtpBroker class
# and replace with stubs

# Actually let me just delete the entire ctpbee section (from start_marker to end_marker)
# and put a clean version

# But before that, the OpenCtpBroker class is also broken. Let me check that first.
# Find the OpenCtpBroker class
ob_start = content.find('class OpenCtpBroker(')
ob_end = content.find('\n# ============================================================\n# ctpbee 封装', ob_start)

print(f'OpenCtpBroker: chars {ob_start} to {ob_end}')

# Save the file content for reference
print('File total length:', len(content))

# Strategy: replace the entire ctpbee section (from "# ====" before ctpbee to before "def build_broker")
# with a clean version. Also need to fix OpenCtpBroker indent.

# For now, just delete the ctpbee section and put a stub
new_section = '''
# ============================================================
# ctpbee 封装 —— 仅在 ctpbee 可用时真正启用 (旧, 已被 openctp-ctp 替代)
# ============================================================
try:
    from ctpbee import CtpBee, OrderRequest as CtpbeeOrderRequest  # type: ignore
    _CTPBEE_OK = True
except Exception as e:  # noqa: BLE001
    _CTPBEE_OK = False
    _CTPBEE_IMPORT_ERR = e


if _CTPBEE_OK:
    class CtpbeeBroker(CtpBroker):
        """ctpbee 封装层 (旧, 已被 openctp-ctp 替代)"""
        def __init__(self, front_addr, broker_id, app_id, auth_code, investor_id, password, md_address=None):
            if not _CTPBEE_OK:
                raise RuntimeError("ctpbee 未安装或 import 失败")
            # 实际实现需要 ctpbee 库, 这里是占位
            raise NotImplementedError("CtpbeeBroker 完整实现需要 ctpbee 库, 推荐使用 OpenCtpBroker (openctp-ctp)")
else:
    class CtpbeeBroker(CtpBroker):
        """ctpbee 不可用时的占位类"""
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "ctpbee 未安装或 import 失败: %s. "
                "请先安装 Microsoft C++ Build Tools, 再执行 `pip install ctpbee`. "
                "或使用 OpenCtpBroker (openctp-ctp, 预编译 wheel 无需 MSVC)." % _CTPBEE_IMPORT_ERR
            )


'''

# Replace the section
new_content = content[:line_start] + new_section.lstrip('\n') + '\n' + content[end_line_start:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Done. New file length:', len(new_content))
