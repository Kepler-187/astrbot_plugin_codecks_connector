# API 架构说明

本页面介绍 Codecks API 的技术细节，帮助开发者理解和扩展插件。

## 端点

| 用途 | URL | 方法 |
|---|---|---|
| 查询（读取） | `POST https://api.codecks.io/` | 请求体 `{"query": {...}}` |
| 写入（操作） | `POST https://api.codecks.io/dispatch/{action}` | 请求体为操作数据 |
| 文件上传签名 | `GET https://api.codecks.io/s3/sign?objectName={filename}` | 返回上传凭证 |

## 认证

通过 HTTP Headers 认证：

```
X-Auth-Token: <Token>
X-Account: <子域名>
Content-Type: application/json
```

Token 来自浏览器 cookie `at`（发往 `api.codecks.io` 的请求）。

## 查询语法

Codecks 使用类 GraphQL 的 JSON 查询语言：

```json
{
  "_root": [{
    "account": [{
      "cards({\"status\": \"started\", \"$limit\": 10})": ["title", "status"]
    }]
  }]
}
```

### 关键概念

- **`_root`**：顶层入口，可访问 `account`（当前组织）和 `user`（当前用户）
- **关系嵌套**：用对象表示，如 `{"assignee": ["name"]}`
- **过滤**：在关系名后面用 JSON 字符串传递查询条件
- **ID 查询**：`"card(12345)": [fields]` 直接按 ID 获取

### 操作符

`eq`(默认)、`neq`、`in`、`notIn`、`gt`、`gte`、`lt`、`lte`、`contains`、`search`(仅 card.content)

### 特殊字段

- `$order`: 排序，`"fieldName"` 升序，`"-fieldName"` 降序
- `$limit`: 数量限制（最大 3000）
- `$offset`: 偏移量
- `$first`: 仅返回第一条
- `$or` / `$and`: 逻辑组合

## 响应结构

API 返回**扁平化 ID 引用**，而非嵌套对象：

```json
{
  "_root": {"account": "acc_123"},
  "account": {
    "acc_123": {"name": "My Org", "projects": ["p1", "p2"]}
  },
  "project": {
    "p1": {"name": "Project A"},
    "p2": {"name": "Project B"}
  }
}
```

插件的 `ResponseParser` 类负责将这种结构解析为常规嵌套对象。

## 写操作（Dispatch）

通过 `POST /dispatch/{action}` 执行：

| Action | 说明 |
|---|---|
| `cards/create` | 创建卡片 |
| `cards/update` | 更新卡片 |
| `cards/complete` | 完成卡片 |
| `cards/reopen` | 重新打开卡片 |
| `cards/addFile` | 附加文件到卡片 |
| `comments/create` | 创建评论 |

> 💡 要发现更多 action，在 Codecks 网页版执行操作时观察浏览器 Network 中的 `/dispatch/` 请求。

## 速率限制

- **40 请求 / 5 秒 / IP**
- 超限返回 HTTP 429
- 插件内置速率限制守卫和自动重试机制

## 核心数据模型

| 模型 | 说明 | 关键字段 |
|---|---|---|
| `account` | 组织 | name, createdAt |
| `project` | 项目 | name, visibility, accountSeq |
| `deck` | 卡组 | title, description, isDeleted |
| `card` | 卡片 | title, content, status, priority, effort, dueDate |
| `milestone` | 里程碑 | name, date, startDate, isGlobal |
| `user` | 用户 | name, createdAt |
| `projectTag` | 标签 | name, color |
| `sprint` | 冲刺 | name, createdAt |

完整的 API 参考请查看 [codecks_api_reference.md](../codecks_api_reference.md)。
