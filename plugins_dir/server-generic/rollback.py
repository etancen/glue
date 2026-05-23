"""Linux 服务器回滚插件。

回滚逻辑实现在 deploy.py 的 ServerGenericPlugin.rollback() 方法中。
本文件仅为满足插件框架约定（要求每个插件目录下存在 rollback.py）。
"""
from plugin_framework.base import BasePlugin
