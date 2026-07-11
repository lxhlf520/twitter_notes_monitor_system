# Twitter Community Notes Monitor

基于 curl\_cffi 直连架构的 Twitter Community Notes 监控系统。无需 RPC 服务或 Playwright 浏览器，通过多账号轮询实现高并发采集。

## 架构

```
┌──────────────────────────────────────────────────┐
│                   main.py                        │
│  ┌─────────────┐  ┌──────────────┐              │
│  │  AccountPool │  │   Monitor    │              │
│  │  (多账号轮询) │  │ (定时调度引擎) │              │
│  └──────┬──────┘  └──────┬───────┘              │
│         │                │                       │
│         ▼                ▼                       │
│  ┌──────────────────────────────────────┐        │
│  │            Client                    │        │
│  │  ┌─────────┐  ┌────────┐  ┌──────┐  │        │
│  │  │ GQLClient│  │ RPC    │  │ curl │  │        │
│  │  │(GraphQL) │  │(备用)   │  │_cffi │  │        │
│  │  └─────────┘  └────────┘  └──────┘  │        │
│  └──────────────────────────────────────┘        │
│         │                                        │
│         ▼                                        │
│  ┌──────────────────────────────────────┐        │
│  │           Storage (MongoDB)          │        │
│  │  x_com_post_new / x_com_post_helpful │        │
│  │  x_com_notes / x_com_contributors    │        │
│  │  x_com_health_snapshots / ...        │        │
│  └──────────────────────────────────────┘        │
│         │                                        │
│         ▼                                        │
│  ┌──────────────────────────────────────┐        │
│  │        HealthMonitor                 │        │
│  │   (账号状态 / 任务健康度 / 看板)        │        │
│  └──────────────────────────────────────┘        │
└──────────────────────────────────────────────────┘
```

## 功能特性

- **curl\_cffi 直连** — 浏览器指纹模拟，无需 Playwright/RPC
- **多账号并发** — 批量 Cookie 校验、自动冷却、请求间隔控制
- **双源追踪** — `new`（待评级）和 `helpful`（已评级）推文独立更新策略
- **笔记提取** — 从 `birdwatch_pivot` 自动提取社区笔记内容
- **指标更新** — 定时刷新推文互动数据（点赞/转发/评论/阅读数）
- **健康监控** — 实时看板：账号池状态、任务执行率、错误率
- **滚动日志** — 控制台 + 文件双输出，自动按天分割

## 快速开始

### 环境要求

- Python >= 3.12
- MongoDB（本地或远程）

### 安装

```bash
# 克隆项目后进入目录
cd twitter-notes-monitor

# 推荐使用 uv
uv sync

# 或使用 pip
pip install -e .
```

### 配置

复制或编辑 `config.toml`：

```toml
[mongodb]
uri = "mongodb://localhost:27017"
database = "community_notes"

[proxy]
url = "http://127.0.0.1:7890"

[monitor]
note_crawl = 10          # 抓取间隔（秒）
metrics_update = 10      # 指标更新间隔（秒）
```

### 初始化数据库

```bash
python init_db.py
```

### 添加账号

```bash
# 单个添加
python manage_accounts.py add my_username "auth_token=xxx; ct0=yyy; ..."

# 导入 cookie JSON 文件
python manage_accounts.py import-cookies ./cookies.json

# 查看账号列表
python manage_accounts.py list
```

### 启动监控

```bash
# 仅抓取新笔记
python main.py --task crawl

# 仅更新指标
python main.py --task update

# 同时运行（默认）
python main.py --task all
```

## MongoDB 集合说明

| 集合 | 用途 |
|------|------|
| `twitter_accounts` | Twitter 账号池（Cookie 存储） |
| `x_com_post_new` | 待评级笔记推文 |
| `x_com_post_new_metrics` | 待评级推文指标历史 |
| `x_com_post_helpful` | 已评级 helpful 推文 |
| `x_com_post_helpful_metrics` | helpful 推文指标历史 |
| `x_com_notes` | 社区笔记内容 |
| `x_com_contributors` | 笔记贡献者信息 |
| `x_com_api_raw` | API 原始响应（可选） |
| `x_com_health_snapshots` | 健康看板快照 |
| `x_com_signature_cache` | 签名材料缓存 |
| `x_com_post_update_status` | 推文更新状态追踪 |

## 数据字段说明

### x_com_notes

| 字段 | 类型 | 说明 |
|------|------|------|
| note_id | string | 笔记唯一 ID |
| note_status | string | 评级状态（CurrentlyRatedHelpful 等） |
| note_content | string | 笔记正文 |
| note_source_links | list[string] | 引用来源链接 |
| note_create_time | string | 创建时间 |
| note_type | string | 笔记分类 |
| AI_note | string | AI 笔记标记 |
| language | string | 语言代码 |
| classification | string | 误导性分类 |
| misleading_tags | list | 误导标签 |
| helpful_tags | list | 有帮助标签 |
| not_helpful_tags | list | 无帮助标签 |

### x_com_contributors

| 字段 | 类型 | 说明 |
|------|------|------|
| note_id | string | 关联笔记 ID |
| author_name | string | 贡献者名称 |
| author_id | string | 贡献者标识 |
| author_AI | string | 是否 AI 笔记作者 |

## 命令行工具

| 脚本 | 用途 |
|------|------|
| `main.py` | 监控主程序 |
| `manage_accounts.py` | 账号池管理（增/删/查/导入 Cookie） |
| `init_db.py` | 初始化 MongoDB 集合和索引 |
| `dashboard.py` | 终端仪表盘 |
| `check_db.py` | 数据库状态检查 |
| `setup_local.py` | 本地环境一键配置 |

## 配置参考

完整配置项见 `config.toml`：

- **proxy** — HTTP 代理地址
- **account** — 冷却时间、请求间隔、并发数
- **monitor** — 抓取/更新频率、双源追踪策略（间隔和最大追踪天数）
- **health** — 健康看板间隔、快照持久化开关
- **storage** — 原始 API 响应落库开关
- **mode** — curl\_cffi 直连 / RPC 模式切换

## 目录结构

```
twitter-notes-monitor/
├── main.py                     # 主入口
├── config.toml                 # 配置文件
├── init_db.py                  # 数据库初始化
├── manage_accounts.py          # 账号管理
├── dashboard.py                # 仪表盘
├── pyproject.toml              # 项目元数据
└── twitter/
    ├── client/                 # API 客户端
    │   ├── client.py           # 核心客户端
    │   ├── gql.py              # GraphQL 端点封装
    │   ├── rpc_client.py       # RPC 客户端（备用）
    │   └── constants.py        # JS 提取的端点参数
    ├── storage.py              # MongoDB 存储
    ├── monitor.py              # 调度引擎
    ├── account_pool.py         # 多账号轮询池
    ├── health_monitor.py       # 健康监控
    ├── parser.py               # 数据解析器
    ├── tweet.py                # Tweet 数据模型
    ├── user.py                 # User 数据模型
    ├── media.py                # 媒体数据模型
    ├── errors.py               # 异常定义
    └── utils.py                # 工具函数
```
