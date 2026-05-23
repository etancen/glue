import telnetlib
import time
from .base import BaseConnector


class TelnetConnector(BaseConnector):
    def __init__(self, target: str, credentials: dict, port: int = 23, **kwargs):
        super().__init__(target, credentials, port=port, **kwargs)
        self.tn: telnetlib.Telnet | None = None

    def connect(self):
        port = self.extra.get("port", 23)
        self.tn = telnetlib.Telnet(self.target, port, timeout=self.extra.get("timeout", 30))
        username = self.credentials.get("username", "")
        password = self.credentials.get("password", "")
        if username:
            self.tn.read_until(b"Username:", timeout=10)
            self.tn.write(username.encode("ascii") + b"\n")
        if password:
            self.tn.read_until(b"Password:", timeout=10)
            self.tn.write(password.encode("ascii") + b"\n")
        time.sleep(1)
        self.tn.read_very_eager()

    def disconnect(self):
        if self.tn:
            self.tn.close()

    def execute(self, command: str, timeout: int = 300) -> dict:
        if not self.tn:
            raise RuntimeError("TelnetConnector not connected")
        self.tn.write(command.encode("ascii") + b"\n")
        time.sleep(2)
        output = self.tn.read_very_eager().decode("ascii", errors="replace")
        return {"stdout": output, "stderr": "", "exit_code": 0}
