import requests
import json
from .base import BaseConnector


class APIConnector(BaseConnector):
    def __init__(self, target: str, credentials: dict, **kwargs):
        super().__init__(target, credentials, **kwargs)
        self.session: requests.Session | None = None
        self.base_url = kwargs.get("base_url", f"https://{target}")

    def connect(self):
        self.session = requests.Session()
        if "token" in self.credentials:
            self.session.headers["Authorization"] = f"Bearer {self.credentials['token']}"
        elif "api_key" in self.credentials:
            self.session.headers["X-API-Key"] = self.credentials["api_key"]
        self.session.headers.setdefault("Content-Type", "application/json")

    def disconnect(self):
        if self.session:
            self.session.close()

    def execute(self, command: str, timeout: int = 300) -> dict:
        """command is a JSON string: {"method":"GET","path":"/api/..."} or {"method":"POST","path":"/api/...","body":{}}"""
        if not self.session:
            raise RuntimeError("APIConnector not connected")
        try:
            cmd = json.loads(command)
        except json.JSONDecodeError:
            return {"stdout": "", "stderr": "Invalid JSON command", "exit_code": 1}
        method = cmd.get("method", "GET").upper()
        path = cmd.get("path", "/")
        body = cmd.get("body")
        resp = self.session.request(method, f"{self.base_url}{path}", json=body, timeout=timeout)
        return {
            "stdout": resp.text,
            "stderr": "",
            "exit_code": 0 if resp.ok else resp.status_code,
        }
