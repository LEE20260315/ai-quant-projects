# install_ctpbee.ps1 —— 装 ctpbee 的完整脚本
# 用法: 用"Developer Command Prompt for VS 2026"打开, 然后跑这个脚本
#   (或者右键 "以管理员身份运行" PowerShell 后跑)

# 1) 加载 MSVC 环境
& "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

# 2) 配清华源 + 关代理
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
$env:HTTPS_PROXY = ""; $env:HTTP_PROXY = ""
$env:https_proxy = ""; $env:http_proxy = ""

# 3) 降级 setuptools (75+ 不认 MSVC v14.40)
pip install --upgrade "setuptools<70" wheel cython

# 4) 装 ctpbee (主包是纯 Python, 只有 ctpbee_api 是 C 扩展)
pip install ctpbee