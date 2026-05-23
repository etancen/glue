"""连接器基础抽象 — 定义传输层的统一接口，屏蔽 SSH/Telnet/API 的协议差异。

插件通过 BaseConnector.execute() 与目标设备交互，无需关心底层连接细节。
上下文管理器协议支持 with 语句安全使用连接。
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """传输层抽象基类 — 插件调用 execute() 而非直接操作原始协议。

    子类需实现 connect/disconnect/execute 三个方法。
    支持 with 语句（__enter__/__exit__），自动管理连接生命周期。

    Attributes:
        target: 目标设备地址（IP 或主机名）
        credentials: 认证凭据字典（可能含 username/password/token/key_file 等）
        extra: 额外参数（port、timeout 等），由 kwargs 传入
    """

    def __init__(self, target: str, credentials: dict, **kwargs):
        self.target = target
        self.credentials = credentials
        self.extra = kwargs
        logger.info(
            "%s initialized: target=%s auth_method=%s extra_keys=%s",
            type(self).__name__,
            target,
            self._auth_summary(),
            sorted(kwargs.keys()) if kwargs else [],
        )

    def _auth_summary(self) -> str:
        """生成认证方式摘要 — 暴露用户名/密钥路径，掩码敏感凭据（token/api_key），避免日志泄露。"""
        if "key_file" in self.credentials:
            return f"key_file={self.credentials['key_file']}"
        if "token" in self.credentials:
            return "token=***"
        if "api_key" in self.credentials:
            return "api_key=***"
        if "username" in self.credentials:
            return f"username={self.credentials['username']}"
        return "none"

    @abstractmethod
    def connect(self) -> None:
        """建立与目标设备的连接。"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """关闭连接并释放资源。"""
        ...

    @abstractmethod
    def execute(self, command: str, timeout: int = 300) -> dict[str, Any]:
        """执行一条命令，返回 {'stdout': str, 'stderr': str, 'exit_code': int}。"""
        ...

    def __enter__(self):
        """上下文管理器入口 — 自动调用 connect()，支持 with 语句。"""
        self.connect()
        return self

    def __exit__(self, *args):
        """上下文管理器出口 — 自动调用 disconnect()，即使发生异常也会执行。"""
        self.disconnect()
