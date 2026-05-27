# 🎴 Codecks Connector for AstrBot

[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D4.5.7-blue)](https://astrbot.app)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

通过聊天命令连接、查询和管理 [Codecks](https://www.codecks.io/) 项目管理平台。

## ✨ 功能特性

- 📂 **项目管理** — 查看项目、卡组列表
- 🃏 **卡片操作** — 创建、搜索、更新、完成、分配卡片
- 💬 **评论系统** — 为卡片添加评论
- 🏁 **里程碑** — 查看里程碑，设置/清除卡片里程碑
- 👥 **团队协作** — 查看成员列表，分配/取消分配负责人
- 📊 **数据统计** — 查看卡片完成率、工作量统计
- 🏷️ **标签 & 冲刺** — 查看标签和冲刺列表
- 🖐️ **个人待办** — 查看手牌/我的任务

## 📦 安装

### 方式一：AstrBot 插件市场
在 AstrBot WebUI → 插件市场搜索 `codecks` 安装。

### 方式二：手动安装
```bash
cd <AstrBot 数据目录>/plugins/
git clone https://github.com/AstrBotDevs/astrbot_plugin_codecks_connector.git
```

## ⚙️ 配置

在 AstrBot WebUI → 插件管理 → Codecks Connector 中配置：

| 配置项 | 说明 | 必填 |
|---|---|---|
| **Token** | Codecks API 认证令牌 | ✅ |
| **子域名** | 组织子域名（如 `team123.codecks.io` → `team123`） | ✅ |
| 请求间隔 | API 请求最小间隔（秒），默认 0.15 | ❌ |
| 默认 Deck | 限定查询范围的 Deck 名称，多个用逗号分隔 | ❌ |

### 获取 Token

1. 登录 Codecks 网页版
2. 打开浏览器开发者工具（F12）→ Network 标签
3. 找到发往 `api.codecks.io` 的请求
4. 在请求 Cookie 中找到 `at` 的值，即为 Token

> ⚠️ **注意**：Token 等同于你的用户身份，拥有你账号的全部权限。请妥善保管，不要泄露。

### 默认 Deck 配置

设置 `default_decks` 后，AI 查询（`/ck ai`）只会在指定的 Deck 中搜索和筛选卡片。

- 名称需与 Codecks 中的 Deck 名称完全一致
- 多个 Deck 用半角逗号分隔：`Stable Bugs,疑难杂症`
- 留空则查询所有 Deck
- 已归档的卡片会自动被排除

## 📖 命令一览

所有命令使用 `/codecks` 或 `/ck` 前缀。

### AI 智能查询

| 命令 | 说明 |
|---|---|
| `/ck ai <自然语言>` | 用自然语言查询/筛选卡片 |

示例：
- `/ck ai 今天完成了哪些BUG`
- `/ck ai 搜索联机相关的问题`
- `/ck ai 最近3天的高优先级卡片`

### 查询命令

| 命令 | 别名 | 说明 |
|---|---|---|
| `/ck projects` | 项目 | 列出所有项目 |
| `/ck decks [项目ID]` | 牌组 | 列出卡组 |
| `/ck cards [卡组ID] [数量]` | 卡片 | 列出卡片 |
| `/ck card <ID>` | — | 查看卡片详情 |
| `/ck search <关键词>` | 搜索 | 搜索卡片 |
| `/ck milestones` | 里程碑 | 列出里程碑 |
| `/ck tags [项目ID]` | 标签 | 列出标签 |
| `/ck sprints [项目ID]` | 冲刺 | 列出冲刺 |
| `/ck users` | 用户、成员 | 列出组织成员 |
| `/ck me` | — | 当前用户信息 |
| `/ck hand` | 手牌、我的任务 | 我的待办 |
| `/ck stats [项目ID]` | 统计 | 卡片统计 |

### 操作命令

| 命令 | 别名 | 说明 |
|---|---|---|
| `/ck newcard <标题> [卡组ID] [工作量] [优先级]` | 新建卡片 | 创建卡片 |
| `/ck complete <ID>` | 完成 | 标记卡片完成 |
| `/ck reopen <ID>` | 重开 | 重新打开卡片 |
| `/ck update <ID> <字段> <值>` | 更新 | 更新卡片字段 |
| `/ck assign <卡片ID> <用户ID>` | 分配 | 分配负责人 |
| `/ck unassign <ID>` | 取消分配 | 取消分配 |
| `/ck comment <ID> <内容>` | 评论 | 添加评论 |
| `/ck setmilestone <卡片ID> <里程碑ID>` | 设置里程碑 | 设置里程碑 |
| `/ck clearmilestone <ID>` | 清除里程碑 | 清除里程碑 |

### 系统命令

| 命令 | 说明 |
|---|---|
| `/ck help` | 显示帮助信息 |
| `/ck config` | 查看配置状态 |
| `/ck debug` | 测试 API 连接 |

### 优先级说明

| 值 | 含义 |
|---|---|
| `a` | 🔴 最高 |
| `b` | 🟠 高 |
| `c` | 🟡 中（默认） |
| `d` | 🟢 低 |

### 可更新字段

`/ck update` 支持的字段：`title`、`content`、`effort`、`priority`、`duedate`

## 🏗️ 项目结构

```
astrbot_plugin_codecks_connector/
├── main.py               # 插件入口，命令注册
├── codecks_client.py     # Codecks API 客户端
├── nlu_handler.py        # AI 自然语言理解处理
├── formatters.py         # 输出格式化
├── codecks_nlu_skill.md  # NLU Skill 配置
├── metadata.yaml         # 插件元数据
├── _conf_schema.json     # 配置 Schema
├── requirements.txt      # Python 依赖
└── README.md             # 本文件
```

## 🔧 技术细节

- 基于 Codecks 类 GraphQL 的 JSON 查询 API
- 异步 HTTP 通信（aiohttp）
- 自动速率限制守卫（默认 0.15 秒间隔）
- 429/网络错误自动重试（最多 3 次指数退避）
- 扁平 ID 引用响应自动解析

## 📄 许可

MIT License

## Daily Excluded Tags

`/ck daily` now supports excluding cards by tag via plugin config `daily_excluded_tags`.

- Example: `#玩家报告`
- Multiple tags: `#玩家报告,#外部反馈`
- Supports values with or without `#`
- Matching is case-insensitive
