from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any


class DeployError(Exception):
    pass


class RetryableError(DeployError):
    """Plugin raises this for transient failures. System will retry."""
    pass


class FatalError(DeployError):
    """Plugin raises this for unrecoverable failures. Skips retry, triggers rollback."""
    pass


class ConfigValidationError(Exception):
    pass


@dataclass
class DeployResult:
    success: bool
    message: str = ""
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackResult:
    success: bool
    message: str = ""
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskContext:
    """Context object passed to plugin methods during execution."""
    job_id: str
    plan_id: str
    node_id: str
    logger: Any = None  # Celery task logger


class BasePlugin(ABC):
    """Every deployment plugin must implement this interface."""

    name: str = ""
    version: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def validate_config(self, params: dict) -> bool: ...

    @abstractmethod
    def deploy(self, params: dict, connector: "BaseConnector", ctx: TaskContext) -> DeployResult: ...

    @abstractmethod
    def rollback(self, params: dict, connector: "BaseConnector", ctx: TaskContext) -> RollbackResult: ...

    @abstractmethod
    def verify(self, params: dict, connector: "BaseConnector") -> bool: ...
