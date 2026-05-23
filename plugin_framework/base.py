"""插件框架基础类型 — 定义了所有插件和连接器必须遵守的契约。

异常体系：
  DeployError → RetryableError（可重试，触发退避）
             → FatalError（不可恢复，直接失败并回滚）
  ConfigValidationError（配置校验失败，阻止执行）

数据类：
  DeployResult / RollbackResult：插件执行结果的标准封装
  TaskContext：传递给插件的运行时上下文（job_id、plan_id、node_id、logger）
"""
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any


class DeployError(Exception):
    """部署异常基类，所有插件抛出的部署相关异常应继承此类。"""
    pass


class RetryableError(DeployError):
    """可重试异常 — 瞬时故障（网络抖动、服务暂时不可用），系统将自动退避重试。"""
    pass


class FatalError(DeployError):
    """致命异常 — 不可恢复的错误（认证失败、硬件故障），跳过重试直接触发回滚。"""
    pass


class ConfigValidationError(Exception):
    """配置校验异常 — 插件 validate_config() 发现参数缺失或非法时抛出。"""
    pass


@dataclass
class DeployResult:
    """部署结果 — 插件 deploy() 方法的标准返回值。

    Attributes:
        success: 部署是否成功
        message: 人类可读的结果描述
        output: 结构化的命令输出，记录每一步的执行结果
    """
    success: bool
    message: str = ""
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackResult:
    """回滚结果 — 插件 rollback() 方法的标准返回值。"""
    success: bool
    message: str = ""
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    """运行时上下文 — 在 deploy/rollback 调用时传递给插件，提供当前任务的环境信息。

    插件可通过 ctx.logger 记录日志到 Celery 任务日志流。
    """
    job_id: str
    plan_id: str
    node_id: str
    logger: Any = None


class BasePlugin(ABC):
    """插件抽象基类 — 所有部署插件必须实现此接口。

    属性（由 loader 注入）：
        name: 插件名，与 plugin.json 一致
        version: 语义化版本
        manifest: plugin.json 完整内容，含 node_types、default_config 等

    生命周期方法：
        validate_config() → deploy() → verify()
        失败时：rollback()
    """

    name: str = ""
    version: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def validate_config(self, params: dict) -> bool:
        """校验部署参数是否完整且合法。返回 True 表示通过，否则抛 ConfigValidationError。"""
        ...

    @abstractmethod
    def deploy(self, params: dict, connector: "BaseConnector", ctx: TaskContext) -> DeployResult:
        """执行部署操作。通过 connector 向目标设备发送命令，返回 DeployResult。

        Args:
            params: 合并后的配置参数（节点 config → global_config → 插件 default_config）
            connector: 已建立连接的传输层实例（SSH/Telnet/API）
            ctx: 运行时上下文（job_id、plan_id、日志记录器）
        """
        ...

    @abstractmethod
    def rollback(self, params: dict, connector: "BaseConnector", ctx: TaskContext) -> RollbackResult:
        """回滚已完成的部署操作。仅在 deploy() 返回 success=True 后被调用。

        回滚失败不宜抛异常 — 返回 RollbackResult(success=False) 通知上层即可，
        保证后续节点的回滚能继续执行。
        """
        ...

    @abstractmethod
    def verify(self, params: dict, connector: "BaseConnector") -> bool:
        """部署后验证 — deploy() 成功后调用，确认配置已生效。

        返回 False 将触发回滚流程。适用于检查 hostname、服务状态等关键指标。
        """
        ...
