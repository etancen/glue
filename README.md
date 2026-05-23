# Glue — 自动化部署平台

基于 Django 的自动化部署工具，加载设计工具导出的 CFG 拓扑配置文件（JSON），将目标对象匹配到部署插件，通过 DAG 并行任务系统执行部署。

## 功能概览

- **CFG 配置解析** — 解析 JSON 格式的拓扑配置文件，校验 schema 并合并多层配置（节点配置 / 全局配置 / 插件默认配置）
- **DAG 并行调度** — 基于 networkx 构建有向无环图，自动计算执行层级，同级节点并行执行
- **插件化部署** — 目录式插件结构（`plugin.json` + `deploy.py` / `rollback.py`），自动扫描加载
- **多协议连接器** — 内置 SSH (paramiko)、Telnet、REST API 三种连接器，可扩展
- **异步任务执行** — Celery + Redis 异步任务队列，支持失败重试（指数退避）和自动回滚
- **RBAC 权限控制** — JWT 认证，admin / operator / readonly 三种角色
- **可配置日志** — 通过 `LOG_LEVEL` 环境变量控制日志级别，INFO 级别输出函数参数和数据结构详情

## 技术栈

| 组件 | 选型 |
|------|------|
| Web 框架 | Django 5.x + Django REST Framework |
| 异步任务 | Celery 5.x + Redis |
| DAG 引擎 | networkx |
| SSH 连接 | paramiko |
| 认证 | djangorestframework-simplejwt (JWT) |
| API 文档 | drf-spectacular (OpenAPI 3.0) |
| 数据库 | SQLite (开发) / PostgreSQL (生产) |

## 目录结构

```
glue/
├── manage.py                  # Django 管理入口
├── requirements.txt           # Python 依赖
├── deploy_platform/           # Django 项目配置
│   ├── settings.py            # 全局配置（数据库、Celery、日志、插件路径等）
│   ├── urls.py                # 根路由
│   ├── celery.py              # Celery 应用配置
│   └── wsgi.py                # WSGI 入口
├── core/                      # 核心应用
│   ├── models.py              # 数据模型（User, DeploymentPlan, DeploymentNode, Plugin, DeploymentJob, AuditLog）
│   ├── views.py               # DRF ViewSets（计划 CRUD、执行/取消、插件扫描、健康检查）
│   ├── serializers.py         # DRF 序列化器
│   ├── permissions.py         # RBAC 权限类
│   ├── urls.py                # REST API 路由
│   └── auth_urls.py           # JWT 认证端点
├── plugin_framework/          # 插件框架
│   ├── base.py                # 基类（BasePlugin, BaseConnector, DeployResult, RollbackResult, TaskContext）
│   ├── registry.py            # 插件注册表（单例）
│   ├── loader.py              # 插件扫描与加载（importlib）
│   └── connectors/            # 连接器实现
│       ├── base.py            # BaseConnector 抽象类
│       ├── ssh.py             # SSH 连接器
│       ├── telnet.py          # Telnet 连接器
│       └── api.py             # REST API 连接器
├── cfg_engine/                # CFG 配置引擎
│   ├── parser.py              # CFG JSON 解析与 schema 校验
│   └── dag.py                 # DAG 构建、拓扑排序、执行层级计算
├── execution/                 # 执行引擎
│   ├── orchestrator.py        # 计划编排（6 步流程：解析→匹配→校验→DAG→入库→入队）
│   ├── tasks.py               # Celery 异步任务（部署执行、重试、失败回滚）
│   └── rollback.py            # 回滚编排（逆拓扑顺序）
└── plugins_dir/               # 插件目录
    ├── server-generic/        # Linux 服务器部署插件（PXE + SSH）
    │   ├── plugin.json
    │   ├── deploy.py
    │   └── rollback.py
    └── switch-cisco/          # Cisco 交换机部署插件（SSH / Telnet）
        ├── plugin.json
        ├── deploy.py
        └── rollback.py
```

## 快速开始

### 环境要求

- Python 3.11+
- Redis 6.0+（Celery broker）

### 安装

```bash
# 克隆项目
git clone <repo-url>
cd glue

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser
```

### 启动服务

```bash
# 终端 1：启动 Django 开发服务器
python manage.py runserver 0.0.0.0:8000

# 终端 2：启动 Celery Worker（需要先启动 Redis）
celery -A deploy_platform worker -l info -P solo

# Windows 下 Celery 使用 solo 池
# Linux/macOS 可使用默认 prefork 池
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DJANGO_SECRET_KEY` | `dev-secret-...` | Django 密钥（生产环境必须修改） |
| `DJANGO_DEBUG` | `True` | 调试模式 |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | 允许的主机名 |
| `LOG_LEVEL` | `INFO` | 全局日志级别（DEBUG / INFO / WARNING / ERROR） |
| `DJANGO_LOG_LEVEL` | `WARNING` | Django 框架日志级别 |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker 地址 |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery 结果后端 |
| `PLUGINS_DIR` | `./plugins_dir` | 插件扫描目录 |

## CFG 配置文件格式

CFG 文件为 JSON 格式，由设计工具导出：

```json
{
  "plan_name": "example-deployment",
  "global_config": {
    "dns_servers": ["8.8.8.8"],
    "ntp_server": "ntp.example.com"
  },
  "nodes": [
    {
      "id": "sw-core-01",
      "node_type": "switch",
      "plugin": "switch-cisco",
      "management_ip": "192.168.1.1",
      "credentials": {
        "username": "admin",
        "password": "cisco123"
      },
      "depends_on": [],
      "config": {
        "hostname": "core-switch-01",
        "vlans": [10, 20, 30]
      }
    },
    {
      "id": "srv-web-01",
      "node_type": "server",
      "plugin": "server-generic",
      "management_ip": "192.168.1.10",
      "credentials": {
        "username": "root",
        "password": "server123"
      },
      "depends_on": ["sw-core-01"],
      "config": {
        "hostname": "web-server-01",
        "packages": ["nginx", "python3"]
      }
    }
  ]
}
```

- `id` — 节点唯一标识
- `node_type` — 节点类型，用于匹配插件的 `node_types`
- `plugin` — 可选，显式指定插件名称
- `depends_on` — 依赖节点 ID 列表，决定 DAG 中的执行顺序
- `config` — 节点级配置，会与 `global_config` 和插件 `default_config` 合并
- 配置优先级：**节点 config > global_config > 插件 default_config**

## REST API

所有 API 需要 JWT 认证（除健康检查）。

### 认证

```
POST /api/v1/auth/token/          # 获取 JWT (username + password)
POST /api/v1/auth/token/refresh/  # 刷新 access token
POST /api/v1/auth/token/verify/   # 验证 token
```

### 部署计划

```
GET    /api/v1/plans/              # 计划列表
POST   /api/v1/plans/              # 创建计划
GET    /api/v1/plans/{id}/         # 计划详情
PUT    /api/v1/plans/{id}/         # 更新计划
DELETE /api/v1/plans/{id}/         # 删除计划（仅 admin/operator）
POST   /api/v1/plans/{id}/execute/ # 执行计划
POST   /api/v1/plans/{id}/cancel/  # 取消执行
GET    /api/v1/plans/{id}/jobs/    # 计划下所有作业
```

### 作业

```
GET    /api/v1/plans/{id}/jobs/{job_id}/       # 作业详情
GET    /api/v1/plans/{id}/jobs/{job_id}/log/   # 作业日志
POST   /api/v1/plans/{id}/jobs/{job_id}/retry/ # 重试失败作业
```

### 插件与系统

```
GET    /api/v1/plugins/         # 已注册插件列表
POST   /api/v1/plugins/scan/    # 重新扫描插件目录（仅 admin）
GET    /api/v1/system/health/   # 健康检查（无需认证）
GET    /api/v1/system/workers/  # Celery worker 状态（仅 admin）
```

### 角色权限

| 操作 | admin | operator | readonly |
|------|-------|----------|----------|
| 查看计划/作业/插件 | ✓ | ✓ | ✓ |
| 创建/修改/删除计划 | ✓ | ✓ | ✗ |
| 执行/取消计划 | ✓ | ✓ | ✗ |
| 扫描插件 | ✓ | ✗ | ✗ |
| 查看 worker | ✓ | ✗ | ✗ |

## 开发插件

插件是 `plugins_dir/` 下的一个目录，包含 `plugin.json` 和 `deploy.py` / `rollback.py`。

### plugin.json 示例

```json
{
  "name": "switch-cisco",
  "version": "1.0.0",
  "node_types": ["switch"],
  "default_config": {
    "_connector_type": "ssh"
  }
}
```

- `name` — 插件唯一名称
- `version` — 语义化版本
- `node_types` — 该插件支持的节点类型列表
- `default_config` — 默认配置（`_connector_type` 指定默认连接器：`ssh` / `telnet` / `api`）

### deploy.py 示例

```python
from plugin_framework.base import BasePlugin, DeployResult, TaskContext

class MyPlugin(BasePlugin):
    def validate_config(self, params: dict) -> bool:
        return "hostname" in params

    def deploy(self, params: dict, connector, ctx: TaskContext) -> DeployResult:
        result = connector.execute("hostname " + params["hostname"])
        ok = result["exit_code"] == 0
        return DeployResult(success=ok, message="hostname set", output=result)

    def rollback(self, params: dict, connector, ctx: TaskContext) -> RollbackResult:
        result = connector.execute("no hostname " + params["hostname"])
        return RollbackResult(success=True, message="reverted", output=result)

    def verify(self, params: dict, connector) -> bool:
        result = connector.execute("show running-config | include hostname")
        return params["hostname"] in result.get("stdout", "")
```

### 异常类型

- `DeployError` — 通用部署异常
- `RetryableError` — 可重试错误（触发 Celery 自动重试，最多 3 次，退避 30s/60s/120s）
- `FatalError` — 致命错误（立即标记失败，不重试）
- `ConfigValidationError` — 配置校验异常

## 执行流程

```
API 请求 → orchestrate_plan()
  ├── Step 1: 解析并校验 CFG (parse_and_validate)
  ├── Step 2: 匹配插件 (_match_plugin)
  ├── Step 3: 校验节点配置 (merge_config + validate_config)
  ├── Step 4: 构建 DAG (build_dag + get_execution_levels)
  ├── Step 5: 创建 DeploymentNode / DeploymentJob 数据库记录
  └── Step 6: 入队所有 Celery 任务
        └── execute_job_task (Celery)
              ├── 构建连接器 (_build_connector)
              ├── 执行部署 (plugin.deploy)
              ├── 验证 (plugin.verify)
              ├── 成功 → 检查计划是否完成 (_check_plan_complete)
              ├── 可重试错误 → 退避重试 (max 3 次)
              └── 失败 → 触发回滚 (_maybe_rollback_plan)
                    └── orchestrate_rollback (逆拓扑顺序逐节点回滚)
```

## 日志

通过 `LOG_LEVEL` 环境变量控制输出级别：

- `DEBUG` — 所有日志，含内部状态和中间值
- `INFO` — 函数参数、数据结构详情、状态转换（开发/调试推荐）
- `WARNING` — 非致命问题、校验失败
- `ERROR` — 执行失败、异常

日志格式：`LEVEL TIMESTAMP [module] message`

```bash
# 开发调试
LOG_LEVEL=DEBUG python manage.py runserver

# 日常运维
LOG_LEVEL=INFO celery -A deploy_platform worker -l info

# 生产环境
LOG_LEVEL=WARNING celery -A deploy_platform worker -l warning
```
