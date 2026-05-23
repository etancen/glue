"""Linux 服务器部署插件 — 通过 SSH 连接执行系统初始化和软件安装。

支持的操作：hostname 设置、netplan 网络配置、apt-get 软件包安装、部署后脚本。
回滚时卸载软件包并重置 hostname。
"""
from plugin_framework.base import BasePlugin, DeployResult, RollbackResult, TaskContext, ConfigValidationError


class ServerGenericPlugin(BasePlugin):
    """Linux 服务器部署插件 — SSH 连接后执行系统初始化流程。

    部署流程（5 步）：
      1. 连通性检查（hostname 命令）
      2. 设置主机名（hostnamectl set-hostname）
      3. 配置网络（写入 /etc/netplan/ + netplan apply）
      4. 安装基础软件包（apt-get update + install）
      5. 执行部署后脚本（bash -c）

    回滚：apt-get remove 卸载已安装软件包，hostname 重置为 localhost
    """

    def validate_config(self, params: dict) -> bool:
        """校验必填字段 hostname 和 management_ip 是否存在且非空。"""
        required = ["hostname", "management_ip"]
        for key in required:
            if key not in params or not params[key]:
                raise ConfigValidationError(f"Missing required config key: '{key}'")
        return True

    def deploy(self, params: dict, connector, ctx: TaskContext) -> DeployResult:
        """执行服务器部署流程，返回 DeployResult 和每步输出。

        Args:
            params: 合并后的配置（hostname, management_ip, network_config(可选),
                    packages(可选), post_script(可选)）
            connector: SSH 连接器实例
            ctx: 运行时上下文
        """
        hostname = params["hostname"]
        os_name = params.get("os", "ubuntu-22.04")

        output = {}
        # 1. 检查 SSH 连通性，确保服务器可达
        result = connector.execute("hostname", timeout=30)
        output["hostname_check"] = result

        # 2. 写入 hostname，使主机在网络中可识别
        connector.execute(f"hostnamectl set-hostname {hostname}", timeout=30)

        # 3. 写入 netplan 配置并生效，完成网络初始化
        if params.get("network_config"):
            net_config = params["network_config"]
            connector.execute(f"echo '{net_config}' > /etc/netplan/01-deploy.yaml", timeout=30)
            connector.execute("netplan apply", timeout=30)

        # 4. 安装业务所需的基础软件包——先 update 源再 install
        if params.get("packages"):
            pkgs = " ".join(params["packages"])
            connector.execute(f"apt-get update && apt-get install -y {pkgs}", timeout=600)
            output["packages_installed"] = params["packages"]

        # 5. 执行用户自定义的部署后脚本（如启动服务、初始化数据等）
        if params.get("post_script"):
            connector.execute(f"bash -c '{params['post_script']}'", timeout=300)

        return DeployResult(success=True, message=f"Server {hostname} deployed with {os_name}", output=output)

    def rollback(self, params: dict, connector, ctx: TaskContext) -> RollbackResult:
        """回滚部署操作 — 卸载软件包、重置 hostname 为 localhost。

        回滚失败返回 RollbackResult(success=False) 而非抛出异常，
        确保后续节点的回滚能继续执行。
        """
        hostname = params["hostname"]
        try:
            # 卸载部署阶段安装的软件包
            if params.get("packages"):
                pkgs = " ".join(params["packages"])
                connector.execute(f"apt-get remove -y {pkgs}", timeout=300)
            # 重置 hostname 避免残留自定义主机名
            connector.execute(f"hostnamectl set-hostname localhost", timeout=30)
            return RollbackResult(success=True, message=f"Rolled back {hostname}")
        except Exception as e:
            return RollbackResult(success=False, message=str(e))

    def verify(self, params: dict, connector) -> bool:
        """验证部署结果 — 检查当前 hostname 是否与预期一致。"""
        hostname = params["hostname"]
        result = connector.execute("hostname", timeout=10)
        return hostname in result.get("stdout", "")
