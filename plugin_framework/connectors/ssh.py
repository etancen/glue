import logging
import paramiko
from .base import BaseConnector

logger = logging.getLogger(__name__)


class SSHConnector(BaseConnector):
    def __init__(self, target: str, credentials: dict, port: int = 22, **kwargs):
        super().__init__(target, credentials, port=port, **kwargs)
        self.client: paramiko.SSHClient | None = None

    def connect(self):
        logger.info("SSH connecting to %s:%s", self.target, self.extra.get("port", 22))
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.target,
            "port": self.extra.get("port", 22),
            "timeout": self.extra.get("timeout", 30),
        }
        if "key_file" in self.credentials:
            connect_kwargs["key_filename"] = self.credentials["key_file"]
            logger.info("SSH auth method: key_file=%s", self.credentials["key_file"])
        else:
            connect_kwargs["username"] = self.credentials.get("username")
            connect_kwargs["password"] = self.credentials.get("password", "")
            logger.info("SSH auth method: username=%s", self.credentials.get("username"))
        self.client.connect(**connect_kwargs)
        logger.info("SSH connected to %s", self.target)

    def disconnect(self):
        if self.client:
            self.client.close()
            logger.info("SSH disconnected from %s", self.target)

    def execute(self, command: str, timeout: int = 300) -> dict:
        if not self.client:
            raise RuntimeError("SSHConnector not connected")
        logger.info("SSH execute on %s: command=%s timeout=%d", self.target, command[:200], timeout)
        _, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        result = {
            "stdout": stdout_text,
            "stderr": stderr_text,
            "exit_code": exit_code,
        }
        logger.info(
            "SSH result on %s: exit_code=%d stdout_len=%d stderr_len=%d",
            self.target, exit_code, len(stdout_text), len(stderr_text),
        )
        return result
