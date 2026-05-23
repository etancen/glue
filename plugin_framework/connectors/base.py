import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Transport abstraction. Plugins call execute(), not raw protocols."""

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
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def execute(self, command: str, timeout: int = 300) -> dict[str, Any]:
        """Execute a command. Returns {'stdout': str, 'stderr': str, 'exit_code': int}."""
        ...

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
