from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Transport abstraction. Plugins call execute(), not raw protocols."""

    def __init__(self, target: str, credentials: dict, **kwargs):
        self.target = target
        self.credentials = credentials
        self.extra = kwargs

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
