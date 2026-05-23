from plugin_framework.base import BasePlugin, DeployResult, RollbackResult, TaskContext, ConfigValidationError


class ServerGenericPlugin(BasePlugin):
    def validate_config(self, params: dict) -> bool:
        required = ["hostname", "management_ip"]
        for key in required:
            if key not in params or not params[key]:
                raise ConfigValidationError(f"Missing required config key: '{key}'")
        return True

    def deploy(self, params: dict, connector, ctx: TaskContext) -> DeployResult:
        hostname = params["hostname"]
        os_name = params.get("os", "ubuntu-22.04")

        output = {}
        # 1. Check connectivity
        result = connector.execute("hostname", timeout=30)
        output["hostname_check"] = result

        # 2. Set hostname
        connector.execute(f"hostnamectl set-hostname {hostname}", timeout=30)

        # 3. Configure network (example: apply netplan or ifcfg)
        if params.get("network_config"):
            net_config = params["network_config"]
            connector.execute(f"echo '{net_config}' > /etc/netplan/01-deploy.yaml", timeout=30)
            connector.execute("netplan apply", timeout=30)

        # 4. Install base packages
        if params.get("packages"):
            pkgs = " ".join(params["packages"])
            connector.execute(f"apt-get update && apt-get install -y {pkgs}", timeout=600)
            output["packages_installed"] = params["packages"]

        # 5. Run post-install script if provided
        if params.get("post_script"):
            connector.execute(f"bash -c '{params['post_script']}'", timeout=300)

        return DeployResult(success=True, message=f"Server {hostname} deployed with {os_name}", output=output)

    def rollback(self, params: dict, connector, ctx: TaskContext) -> RollbackResult:
        hostname = params["hostname"]
        try:
            # Remove packages if installed
            if params.get("packages"):
                pkgs = " ".join(params["packages"])
                connector.execute(f"apt-get remove -y {pkgs}", timeout=300)
            # Reset hostname
            connector.execute(f"hostnamectl set-hostname localhost", timeout=30)
            return RollbackResult(success=True, message=f"Rolled back {hostname}")
        except Exception as e:
            return RollbackResult(success=False, message=str(e))

    def verify(self, params: dict, connector) -> bool:
        hostname = params["hostname"]
        result = connector.execute("hostname", timeout=10)
        return hostname in result.get("stdout", "")
