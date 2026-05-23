from plugin_framework.base import BasePlugin, DeployResult, RollbackResult, TaskContext, ConfigValidationError


class CiscoSwitchPlugin(BasePlugin):
    def validate_config(self, params: dict) -> bool:
        for key in ["management_ip", "admin_creds"]:
            if key not in params or not params[key]:
                raise ConfigValidationError(f"Missing required config key: '{key}'")
        return True

    def deploy(self, params: dict, connector, ctx: TaskContext) -> DeployResult:
        ip = params["management_ip"]
        output = {}

        # 1. Enter enable mode
        result = connector.execute("enable", timeout=30)
        output["enable"] = result

        # 2. Enter configuration mode
        result = connector.execute("configure terminal", timeout=30)
        output["config_mode"] = result

        # 3. Set hostname
        hostname = params.get("hostname", "cisco-switch")
        result = connector.execute(f"hostname {hostname}", timeout=30)
        output["hostname_set"] = result

        # 4. Configure VLANs
        vlans = params.get("vlans", [])
        for vlan_id in vlans:
            result = connector.execute(f"vlan {vlan_id}", timeout=30)
            output[f"vlan_{vlan_id}"] = result

        # 5. Configure interfaces if provided
        for iface_cfg in params.get("interfaces", []):
            iface = iface_cfg["name"]
            connector.execute(f"interface {iface}", timeout=30)
            if "description" in iface_cfg:
                connector.execute(f"description {iface_cfg['description']}", timeout=30)
            if "vlan" in iface_cfg:
                connector.execute(f"switchport access vlan {iface_cfg['vlan']}", timeout=30)
            if iface_cfg.get("enabled", True):
                connector.execute("no shutdown", timeout=30)
            output[f"interface_{iface}"] = "configured"

        # 6. Save config
        connector.execute("end", timeout=10)
        result = connector.execute("write memory", timeout=30)
        output["save_config"] = result

        return DeployResult(success=True, message=f"Switch at {ip} configured", output=output)

    def rollback(self, params: dict, connector, ctx: TaskContext) -> RollbackResult:
        try:
            connector.execute("enable", timeout=30)
            connector.execute("configure terminal", timeout=30)
            # Remove VLANs
            vlans = params.get("vlans", [])
            for vlan_id in vlans:
                connector.execute(f"no vlan {vlan_id}", timeout=30)
            connector.execute("end", timeout=10)
            connector.execute("write memory", timeout=30)
            return RollbackResult(success=True, message="Rolled back switch config")
        except Exception as e:
            return RollbackResult(success=False, message=str(e))

    def verify(self, params: dict, connector) -> bool:
        result = connector.execute("show running-config | include hostname", timeout=30)
        expected = params.get("hostname", "cisco-switch")
        return expected in result.get("stdout", "")
