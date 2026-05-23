"""REST API 连接器 — 基于 requests 库，支持 Bearer token 和 API Key 两种认证。

命令格式为 JSON 字符串：{"method":"GET/POST","path":"/api/...","body":{}}（body 可选）。
适用于：可通过 RESTful API 管理的设备（如 SDN 控制器、存储阵列、云平台等）。
"""
import json
import logging
import requests
from .base import BaseConnector

logger = logging.getLogger(__name__)


class APIConnector(BaseConnector):
    """REST API 连接器 — 基于 requests.Session 实现持久连接和认证头管理。

    支持 Bearer token 和 X-API-Key 两种认证方式，自动设置 Content-Type: application/json。
    通过 Session 复用底层 TCP 连接，减少频繁建立连接的开销。
    """

    def __init__(self, target: str, credentials: dict, **kwargs):
        super().__init__(target, credentials, **kwargs)
        self.session: requests.Session | None = None
        # base_url 默认从 target 构建，也可通过 kwarg 显式传入（如使用非标准端口）
        self.base_url = kwargs.get("base_url", f"https://{target}")

    def connect(self):
        """创建 requests.Session 并配置认证头。不会立即发起 HTTP 请求。"""
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
        """关闭 Session，释放底层连接池。"""
        if self.session:
            self.session.close()
            logger.info("API session closed for %s", self.base_url)

    def execute(self, command: str, timeout: int = 300) -> dict:
        """执行 API 请求。command 为 JSON 字符串编码的 HTTP 请求参数。

        command 格式:
            {"method":"GET","path":"/api/v1/things"}
            {"method":"POST","path":"/api/v1/things","body":{"key":"value"}}

        非 2xx 响应不会抛异常，而是通过 exit_code 返回 HTTP 状态码供上层判断。
        """
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
            # 非 2xx 响应以 HTTP 状态码作为 exit_code，便于调用方判断
            "exit_code": 0 if resp.ok else resp.status_code,
        }
        logger.info(
            "API response: %s %s → status=%d content_len=%d",
            method, full_url, resp.status_code, len(resp.text),
        )
        return result
