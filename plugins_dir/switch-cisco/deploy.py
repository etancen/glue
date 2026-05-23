"""Cisco 交换机部署插件 — 通过 SSH/Telnet 执行 IOS CLI 命令完成交换机初始化。

连接方式由 _connector_type 参数控制（默认 ssh，可配置 telnet）。
配置操作：hostname、VLAN 创建、接口配置（description/access vlan/no shutdown）、配置持久化。
"""
from plugin_framework.base import BasePlugin, DeployResult, RollbackResult, TaskContext, ConfigValidationError


class CiscoSwitchPlugin(BasePlugin):
    """Cisco 交换机部署插件 — 通过 SSH/Telnet 逐条下发 IOS CLI 命令。

    部署流程（6 步）：
      1. enable — 进入特权模式
      2. configure terminal — 进入全局配置模式
      3. hostname — 设置交换机主机名
      4. vlan — 逐条创建 VLAN
      5. interface — 配置接口（description/access vlan/no shutdown）
      6. end + write memory — 退出配置模式并持久化到 startup-config

    回滚：删除部署时创建的 VLAN，保存配置。
    """

    def validate_config(self, params: dict) -> bool:
        """校验必填字段 management_ip 和 admin_creds 是否存在且非空。"""
        for key in ["management_ip", "admin_creds"]:
            if key not in params or not params[key]:
                raise ConfigValidationError(f"Missing required config key: '{key}'")
        return True

    def deploy(self, params: dict, connector, ctx: TaskContext) -> DeployResult:
        """执行交换机部署流程，返回 DeployResult 和每步输出。

        Args:
            params: 合并后的配置（management_ip, admin_creds, hostname(可选),
                    vlans(可选), interfaces(可选)）
            connector: SSH/Telnet 连接器实例
            ctx: 运行时上下文
        """
        ip = params["management_ip"]
        output = {}

        # 1. 进入特权模式，获取配置权限
        result = connector.execute("enable", timeout=30)
        output["enable"] = result

        # 2. 进入全局配置模式，后续命令在此模式下生效
        result = connector.execute("configure terminal", timeout=30)
        output["config_mode"] = result

        # 3. 设置交换机主机名，便于网络管理中识别
        hostname = params.get("hostname", "cisco-switch")
        result = connector.execute(f"hostname {hostname}", timeout=30)
        output["hostname_set"] = result

        # 4. 逐条创建 VLAN，为二层网络隔离做准备
        vlans = params.get("vlans", [])
        for vlan_id in vlans:
            result = connector.execute(f"vlan {vlan_id}", timeout=30)
            output[f"vlan_{vlan_id}"] = result

        # 5. 配置物理接口：description、access vlan、no shutdown（默认开启）
        for iface_cfg in params.get("interfaces", []):
            iface = iface_cfg["name"]
            connector.execute(f"interface {iface}", timeout=30)
            if "description" in iface_cfg:
                connector.execute(f"description {iface_cfg['description']}", timeout=30)
            if "vlan" in iface_cfg:
                connector.execute(f"switchport access vlan {iface_cfg['vlan']}", timeout=30)
            # 未显式设置 enabled=False 则默认开启端口
            if iface_cfg.get("enabled", True):
                connector.execute("no shutdown", timeout=30)
            output[f"interface_{iface}"] = "configured"

        # 6. 退出配置模式并 write memory 持久化 running-config → startup-config，防止重启丢失
        connector.execute("end", timeout=10)
        result = connector.execute("write memory", timeout=30)
        output["save_config"] = result

        return DeployResult(success=True, message=f"Switch at {ip} configured", output=output)

    def rollback(self, params: dict, connector, ctx: TaskContext) -> RollbackResult:
        """回滚交换机配置 — 用 no vlan 命令删除部署阶段创建的 VLAN。

        回滚失败返回 RollbackResult(success=False) 而非抛出异常，
        确保后续节点的回滚能继续执行。
        """
        try:
            connector.execute("enable", timeout=30)
            connector.execute("configure terminal", timeout=30)
            # 用 no 命令逐条删除部署时创建的 VLAN，恢复原状
            vlans = params.get("vlans", [])
            for vlan_id in vlans:
                connector.execute(f"no vlan {vlan_id}", timeout=30)
            connector.execute("end", timeout=10)
            connector.execute("write memory", timeout=30)
            return RollbackResult(success=True, message="Rolled back switch config")
        except Exception as e:
            return RollbackResult(success=False, message=str(e))

    def verify(self, params: dict, connector) -> bool:
        """验证部署结果 — 检查 running-config 中的 hostname 是否与预期一致。"""
        result = connector.execute("show running-config | include hostname", timeout=30)
        expected = params.get("hostname", "cisco-switch")
        return expected in result.get("stdout", "")
