"""
common.execution —— 跨策略共享的实盘执行层
=====================================

所有 path1 / path2 都要用到的实盘基础设施:
  - ctp_broker            CTP 抽象层 (Mock / openctp-ctp / ctpbee)
  - risk_manager          风控 (4 级状态机, 40% 硬熔断)
  - push_notifier         钉钉 / Bark 推送
  - confirmation_bridge   FastAPI 手机确认桥
  - bridge_publisher      桥 HTTP 客户端
  - execution_engine      信号→风控→仓位→下单 通用编排器

用法 (在 path1/path2 任意位置):
    from common.execution.ctp_broker import build_broker, MockCtpBroker
    from common.execution.risk_manager import RiskManager
    from common.execution.execution_engine import ExecutionEngine

依赖:
    - common 包必须在 Python sys.path 上
    - 推荐在 ai-quant-projects-merged/ 根目录运行, 或将根加入 PYTHONPATH
"""
from .ctp_broker import (
    CtpBroker, MockCtpBroker, OpenCtpBroker, CtpbeeBroker,
    OrderRequest, OrderResult, build_broker,
    infer_exchange_id,
    EXCHANGE_SHFE, EXCHANGE_DCE, EXCHANGE_CZCE,
    EXCHANGE_CFFEX, EXCHANGE_INE, EXCHANGE_GFEX,
)
from .risk_manager import (RiskManager, RiskConfig, RiskLevel, AccountSnapshot,)
from .push_notifier import (DingTalkNotifier, BarkNotifier, MultiNotifier, SignalCard,)
from .execution_engine import (ExecutionEngine, PendingSignal, ExecutionEngineError,)
from .base_sizer import (BaseSizer, FixedSizer, SizerDecision,)
from .bridge_publisher import publish as bridge_publish_signal, is_alive as bridge_is_alive

# confirmation_bridge 需要 fastapi, 懒加载 (避免仅做单元测试时强制安装 fastapi)
def __getattr__(name):
    if name == "confirmation_bridge_app":
        from .confirmation_bridge import app as _app
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # broker
    "CtpBroker", "MockCtpBroker", "OpenCtpBroker", "CtpbeeBroker",
    "OrderRequest", "OrderResult", "build_broker",
    "infer_exchange_id",
    "EXCHANGE_SHFE", "EXCHANGE_DCE", "EXCHANGE_CZCE",
    "EXCHANGE_CFFEX", "EXCHANGE_INE", "EXCHANGE_GFEX",
    # risk
    "RiskManager", "RiskConfig", "RiskLevel", "AccountSnapshot",
    # push
    "DingTalkNotifier", "BarkNotifier", "MultiNotifier", "SignalCard",
    # engine
    "ExecutionEngine", "PendingSignal", "ExecutionEngineError",
    # bridge
    "bridge_publish_signal", "bridge_is_alive", "confirmation_bridge_app",
]
