import paramiko
from .base import BaseConnector


class SSHConnector(BaseConnector):
    def __init__(self, target: str, credentials: dict, port: int = 22, **kwargs):
        super().__init__(target, credentials, port=port, **kwargs)
        self.client: paramiko.SSHClient | None = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.target,
            "port": self.extra.get("port", 22),
            "timeout": self.extra.get("timeout", 30),
        }
        if "key_file" in self.credentials:
            connect_kwargs["key_filename"] = self.credentials["key_file"]
        else:
            connect_kwargs["username"] = self.credentials.get("username")
            connect_kwargs["password"] = self.credentials.get("password", "")
        self.client.connect(**connect_kwargs)

    def disconnect(self):
        if self.client:
            self.client.close()

    def execute(self, command: str, timeout: int = 300) -> dict:
        if not self.client:
            raise RuntimeError("SSHConnector not connected")
        _, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        return {
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": stdout.channel.recv_exit_status(),
        }
