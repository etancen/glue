"""SSH 连接器 — 基于 paramiko 实现，支持密码和密钥文件两种认证方式。

适用于：Linux 服务器、Cisco 交换机等所有支持 SSH 协议的设备。
"""
import logging
import paramiko
from .base import BaseConnector

logger = logging.getLogger(__name__)


class SSHConnector(BaseConnector):
    """SSH 连接器 — 使用 paramiko 建立 SSH 连接并执行远程命令。

    认证方式：优先 key_file（密钥文件），否则使用 username/password。
    AutoAddPolicy 自动信任未知主机密钥，适用于内部网络环境。
    """

    def __init__(self, target: str, credentials: dict, port: int = 22, **kwargs):
        super().__init__(target, credentials, port=port, **kwargs)
        self.client: paramiko.SSHClient | None = None

    def connect(self):
        """建立 SSH 连接 — 自动选择认证方式（密钥 > 用户名密码）。"""
        logger.info("SSH connecting to %s:%s", self.target, self.extra.get("port", 22))
        self.client = paramiko.SSHClient()
        # AutoAddPolicy：自动添加未知主机密钥，避免首次连接时的手动确认
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
        """关闭 SSH 连接并释放资源。"""
        if self.client:
            self.client.close()
            logger.info("SSH disconnected from %s", self.target)

    def execute(self, command: str, timeout: int = 300) -> dict:
        """执行远程命令，返回 stdout/stderr 和退出码。

        timeout 作用于整个命令执行周期（读取 stdout/stderr 包含在内）。
        """
        if not self.client:
            raise RuntimeError("SSHConnector not connected")
        logger.info("SSH execute on %s: command=%s timeout=%d", self.target, command[:200], timeout)
        _, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        # 通过 channel 获取真实退出码（而非 stderr 内容判断）
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
