import json
import logging
import requests
from .base import BaseConnector

logger = logging.getLogger(__name__)


class APIConnector(BaseConnector):
    def __init__(self, target: str, credentials: dict, **kwargs):
        super().__init__(target, credentials, **kwargs)
        self.session: requests.Session | None = None
        self.base_url = kwargs.get("base_url", f"https://{target}")

    def connect(self):
        logger.info("API connector: base_url=%s", self.base_url)
        self.session = requests.Session()
        if "token" in self.credentials:
            self.session.headers["Authorization"] = f"Bearer {self.credentials['token']}"
            logger.info("API auth: Bearer token")
        elif "api_key" in self.credentials:
            self.session.headers["X-API-Key"] = self.credentials["api_key"]
            logger.info("API auth: X-API-Key")
        self.session.headers.setdefault("Content-Type", "application/json")

    def disconnect(self):
        if self.session:
            self.session.close()
            logger.info("API session closed for %s", self.base_url)

    def execute(self, command: str, timeout: int = 300) -> dict:
        """command is a JSON string: {"method":"GET","path":"/api/..."} or {"method":"POST","path":"/api/...","body":{}}"""
        if not self.session:
            raise RuntimeError("APIConnector not connected")
        try:
            cmd = json.loads(command)
        except json.JSONDecodeError:
            logger.error("API execute: invalid JSON command: %s", command[:200])
            return {"stdout": "", "stderr": "Invalid JSON command", "exit_code": 1}

        method = cmd.get("method", "GET").upper()
        path = cmd.get("path", "/")
        body = cmd.get("body")
        full_url = f"{self.base_url}{path}"
        logger.info("API request: %s %s body=%s", method, full_url, body)
        resp = self.session.request(method, full_url, json=body, timeout=timeout)
        result = {
            "stdout": resp.text,
            "stderr": "",
            "exit_code": 0 if resp.ok else resp.status_code,
        }
        logger.info(
            "API response: %s %s → status=%d content_len=%d",
            method, full_url, resp.status_code, len(resp.text),
        )
        return result
