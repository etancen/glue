"""Telnet 连接器 — 基于 telnetlib 实现，通过用户名/密码登录并执行命令。

适用于：老旧 Cisco 交换机、嵌入式设备等仅支持 Telnet 协议的目标。
"""
import logging
import telnetlib
import time
from .base import BaseConnector

logger = logging.getLogger(__name__)


class TelnetConnector(BaseConnector):
    """Telnet 连接器 — 建立 Telnet 会话，可选的 Username/Password 登录流程。

    命令执行后固定等待 2 秒再读取输出，适应交互式设备延迟。
    read_very_eager() 读取所有立即可用的数据，不等待更多输出。
    """

    def __init__(self, target: str, credentials: dict, port: int = 23, **kwargs):
        super().__init__(target, credentials, port=port, **kwargs)
        self.tn: telnetlib.Telnet | None = None

    def connect(self):
        """建立 Telnet 连接并完成 login 流程（如有凭据）。"""
        port = self.extra.get("port", 23)
        timeout = self.extra.get("timeout", 30)
        logger.info("Telnet connecting to %s:%s (timeout=%d)", self.target, port, timeout)
        self.tn = telnetlib.Telnet(self.target, port, timeout=timeout)
        username = self.credentials.get("username", "")
        password = self.credentials.get("password", "")
        # 按顺序等待提示符并发送凭据，避免先发密码而后服务端先问 username
        if username:
            logger.info("Telnet login: username=%s", username)
            self.tn.read_until(b"Username:", timeout=10)
            self.tn.write(username.encode("ascii") + b"\n")
        if password:
            self.tn.read_until(b"Password:", timeout=10)
            self.tn.write(password.encode("ascii") + b"\n")
        # 等待设备处理登录，随后清空缓冲区中的残留 MOTD 等无关输出
        time.sleep(1)
        self.tn.read_very_eager()
        logger.info("Telnet connected to %s", self.target)

    def disconnect(self):
        """关闭 Telnet 连接。"""
        if self.tn:
            self.tn.close()
            logger.info("Telnet disconnected from %s", self.target)

    def execute(self, command: str, timeout: int = 300) -> dict:
        """发送命令并读取输出。Telnet 协议没有退出码概念，始终返回 exit_code=0。"""
        if not self.tn:
            raise RuntimeError("TelnetConnector not connected")
        logger.info("Telnet execute on %s: command=%s", self.target, command[:200])
        self.tn.write(command.encode("ascii") + b"\n")
        # 固定等待 2s 确保设备完成命令处理，简单但可靠
        time.sleep(2)
        output = self.tn.read_very_eager().decode("ascii", errors="replace")
        logger.info("Telnet result on %s: output_len=%d", self.target, len(output))
        return {"stdout": output, "stderr": "", "exit_code": 0}
