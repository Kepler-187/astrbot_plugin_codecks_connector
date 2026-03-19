# Codecks API 完整参考文档

> [!NOTE]
> 本文档基于 [Codecks API Quick Guide](https://manual.codecks.io/api/) 和 [API Reference](https://manual.codecks.io/api-reference/) 整理，版本日期 Aug 2023 (beta)。API 尚无稳定性保证，但大部分 schema 多年未变。

---

## 1. 认证

| Header | 说明 |
|---|---|
| `X-Auth-Token` | 认证令牌，从浏览器 cookie `at`（发往 `api.codecks.io`）提取 |
| `X-Account` | 组织子域名，如 `team123.codecks.io` → `team123` |
| `Content-Type` | `application/json` |

> [!CAUTION]
> Token 等同于用户身份，持有者拥有该用户的全部权限。建议用 observer 用户的 token 进行只读集成。

---

## 2. 端点

| 用途 | URL | 方法 |
|---|---|---|
| **读取（查询）** | `POST https://api.codecks.io/` | 请求体 `{"query": {...}}` |
| **写入（操作）** | `POST https://api.codecks.io/dispatch/{action}` | 请求体为操作数据 JSON |
| **文件上传签名** | `GET https://api.codecks.io/s3/sign?objectName={filename}` | 返回 S3 上传凭证 |

---

## 3. 速率限制

- **40 请求 / 5 秒 / IP**
- 超限返回 HTTP 429

---

## 4. 查询语法

Codecks 使用类 GraphQL 的 JSON 查询语言。

### 4.1 基本结构

```json
{
  "_root": [{
    "relname($query)": ["field1", "field2", {"nestedRel": ["field3"]}]
  }]
}
```

- `_root` 是顶层入口，代表当前认证上下文
- 可通过 `_root` 访问 `account`（当前组织）和 `user`（当前用户）
- 字段用字符串数组指定，嵌套关系用对象

### 4.2 按 ID 查询

```json
{
  "card(12345)": ["title", "status", "content"]
}
```

直接用 `modelname(id)` 获取单条记录。

### 4.3 过滤 `$query`

`$query` 部分需 `JSON.stringify()` 后嵌入 key 中：

```json
{
  "_root": [{
    "account": [{
      "cards({\"status\": \"started\", \"$order\": \"-createdAt\", \"$limit\": 10})": ["title"]
    }]
  }]
}
```

### 4.4 操作符 `$op`

| 操作符 | 说明 | 值类型 |
|---|---|---|
| `eq` | 等于（默认） | value \| null |
| `neq` | 不等于 | value \| null |
| `in` | 在数组中 | array |
| `notIn` | 不在数组中 | array |
| `gt` / `gte` | 大于 / 大于等于 | ordinal |
| `lt` / `lte` | 小于 / 小于等于 | ordinal |
| `inOrNull` | 在数组中或为 null | array |
| `contains` | 包含子串（仅 string 字段） | string |
| `search` | 全文搜索（仅 `card.content`） | string |
| `has` | 数组包含某值 | value |
| `overlaps` | 数组有交集 | array |

**快捷写法：** `{fieldName: value}` 等同于 `{fieldName: {"op": "eq", "value": value}}`

**数组快捷写法：** `{projectId: [123, 234]}` 等同于 `{projectId: {"op": "in", "value": [123, 234]}}`

### 4.5 特殊字段

| 字段 | 说明 |
|---|---|
| `$or` | 或条件 `[{cond1}, {cond2}]` |
| `$and` | 与条件 `[{cond1}, {cond2}]` |
| `$order` | 排序。`"fieldName"` 升序、`"-fieldName"` 降序、或 `[{"field": "name", "dir": "desc"}]` |
| `$first` | 仅返回第一条（需配合 `$order`） |
| `$limit` | 数量限制，最大 3000（需配合 `$order`） |
| `$offset` | 偏移量（需配合 `$limit`） |

### 4.6 关系字段过滤

可通过关系属性过滤，如查找有未关闭 block/review 的卡片：

```json
{"resolvables": {"context": ["block", "review"], "isClosed": false}}
```

否定用 `!` 前缀：`{"!resolvables": {...}}`

---

## 5. 核心数据模型

### 5.1 Card（卡片）— 最核心的实体

| 字段 | 类型 | 说明 |
|---|---|---|
| `accountSeq` | int | 账户内序号 |
| `content` | string | 卡片正文（Markdown） |
| `title` | string | 标题（从 content 首行派生，在创建时可单独指定） |
| `status` | string | 状态：`"created"` / `"started"` / `"done"` |
| `derivedStatus` | string | 派生状态（考虑子卡片等） |
| `type` | string | 卡片类型 |
| `priority` | int | 优先级 |
| `effort` | int | 工作量 |
| `dueDate` | day | 截止日期 |
| `createdAt` | date | 创建时间 |
| `lastUpdatedAt` | date | 最后更新时间 |
| `masterTags` | array | 主标签 |
| `tags` | array | 标签 |
| `isDoc` | bool | 是否为文档卡片 |
| `isPublic` | bool | 是否公开 |
| `checkboxStats` | json | 复选框统计 |
| `childCardInfo` | string | 子卡片信息 |
| `embeds` | json | 嵌入内容 |
| `hasBlockingDeps` | bool | 是否有阻塞依赖 |
| `mentionedUsers` | array | 提及的用户 |
| `meta` | json | 元数据 |
| `properties` | json | 自定义属性 |
| `publicToken` | string | 公开token |
| `recurringInfo` | json | 循环任务信息 |
| `milestoneSeq` | int | 里程碑内序号 |
| `nextScheduledDate` | day | 下次计划日期 |
| `tagDescription` | string | 标签描述 |
| `uniqueFriendlyId` | string | 唯一友好ID |
| `checkboxInfo` | array | 复选框详细信息 |

**关系（外键）：**

| 关系字段 | 说明 |
|---|---|
| `account` → account | 所属组织 |
| `deck` → deck | 所属卡组 |
| `project` → project(legacyProject) | 所属项目 |
| `milestone` → milestone | 所属里程碑 |
| `assignee` → user | 负责人 |
| `creator` → user | 创建者 |
| `owner` → user | 所有者 |
| `coverFile` → file | 封面文件 |
| `recurringSourceCard` → card | 循环来源卡片 |
| `pendingApprovalBy` → user[] | 待审批人 |

**子关系（一对多）：**
`resolvable[]`、`handCard[]`、`timeTrackingSegment[]`、`cardSubscription[]`、`cardOrder[]`、`resolvableEntry[]`、`queueEntry[]`、`attachment[]`、`cardHistory[]`、`timeTrackingSum`、`card[]`（子卡片）、`cardUpvote[]`

---

### 5.2 Deck（卡组）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 名称 |
| `description` | string | 描述 |
| `color` | string | 颜色 |
| `accountSeq` | int | 账户内序号 |
| `createdAt` | date | 创建时间 |
| `isDeleted` | bool | 是否已删除 |
| `isPublic` | bool | 是否公开 |
| `archived` | bool | 是否已归档 |
| `handSyncEnabled` | bool | 是否启用手牌同步 |
| `priority` | int | 优先级 |
| `projectSeq` | int | 项目内序号 |
| `properties` | json | 自定义属性 |
| `publicMessage` | string | 公开消息 |
| `publicPath` | string | 公开路径 |
| `visibility` | string | 可见性 |

**关系：** `account`、`project`、`creator`→user、`owner`→user、`coverFile`→file、`parentDeck`→deck
**子关系：** `card[]`、`workflowItem[]`、`cardOrderInDeck[]`、`activity[]`、`deckGuardian[]`

---

### 5.3 Project（项目）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 名称 |
| `accountSeq` | int | 账户内序号 |
| `createdAt` | date | 创建时间 |
| `visibility` | string | 可见性 |
| `isPublic` | bool | 是否公开 |
| `spaces` | json | 空间配置 |
| `markerColor` | unknown | 标记颜色 |
| `allowUpvotes` | bool | 允许投票 |
| `commentsArePublic` | bool | 评论公开 |
| `defaultUserAccess` | string | 默认用户访问级别 |
| `publicPath` | string | 公开路径 |
| `publicHeading` | string | 公开标题 |
| `publicMessage` | string | 公开消息 |
| `publicIsExplicit` | bool | 公开是否显式 |
| `publicLayoutVersion` | int | 公开布局版本 |
| `publicBackgroundColor` | string | 公开背景色 |
| `publicRegistryAgreement` | bool | 公开注册协议 |
| `effortIcon` | unknown | 工作量图标 |

**关系：** `account`、`coverFile`→file、`publicBackgroundImage`→file、`publicBannerFile`→file、`publicTileFile`→file
**子关系：** `deck[]`、`milestoneProject[]`、`sprintProject[]`、`projectTag[]`、`projectUser[]`、`userProjectAccess[]`、`publicProjectInfo`、`activity[]`、`cardUpvote[]`、`publicProjectVisit[]`

---

### 5.4 Account（组织/账户）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 组织名称 |
| `accountType` | string | 账户类型 |
| `appId` | string | 应用ID |
| `billingEmail` | string | 账单邮箱 |
| `createdAt` | date | 创建时间 |
| `nextInvoiceAt` | date | 下次账单日期 |
| `trialEndAt` | date | 试用期结束 |
| `publicToken` | string | 公开token |
| `properties` | json | 属性 |

**关系：** `creator`→user、`owner`→user、`faviconFile`→file、`logoFile`→file、`plan`
**子关系：** `card[]`、`deck[]`、`project[]`、`milestone[]`、`sprint[]`、`accountRole[]`、`workflowItem[]`、`handCard[]`、`resolvable[]`、`file[]`、`invoice[]`、`activity[]` 等

---

### 5.5 User（用户）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 用户名 |
| `firstName` | string | 名 |
| `lastName` | string | 姓 |
| `nickname` | string | 昵称 |
| `email` | string | 邮箱 |
| `initials` | string | 首字母缩写 |
| `createdAt` | date | 创建时间 |
| `lastSeenAt` | date | 最后上线时间 |
| `timezone` | string | 时区 |
| `status` | string | 状态 |
| `isDeleted` | bool | 是否已删除 |
| `publicToken` | string | 公开token |
| `properties` | json | 属性 |

**关系：** `account`、`creator`→user、`avatarFile`→file

---

### 5.6 Milestone（里程碑）

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 名称 |
| `description` | unknown | 描述 |
| `color` | string | 颜色 |
| `accountSeq` | int | 账户内序号 |
| `date` | day | 截止日期 |
| `startDate` | day | 开始日期 |
| `createdAt` | date | 创建时间 |
| `isDeleted` | bool | 是否已删除 |
| `isGlobal` | bool | 是否全局 |
| `handSyncEnabled` | bool | 手牌同步 |
| `stats` | json | 统计数据 |
| `manualOrderLabels` | json | 手动排序标签 |
| `userCapacities` | json | 用户容量 |
| `preferredOrder` | unknown | 首选排序 |

**关系：** `account`、`creator`→user、`coverFile`→file

---

## 6. 写操作（Dispatch）

通过 `POST /dispatch/{action}` 执行，请求体为 JSON。

### 6.1 已知的 dispatch 操作

| 操作 | 说明 | 关键参数 |
|---|---|---|
| `cards/create` | 创建卡片 | `content`, `deckId`, `milestoneId`, `assigneeId`, `effort`, `priority`, `userId`, `putOnHand`, `masterTags`, `attachments`, `childCards` |
| `cards/update` | 更新卡片 | `cardId`, `userId`, + 更新字段 |
| `cards/complete` | 完成卡片 | `cardId`, `userId` |
| `cards/reopen` | 重新打开卡片 | `cardId`, `userId` |
| `cards/addFile` | 附加文件到卡片 | `cardId`, `userId`, `fileData: {fileName, url, size, type}` |
| `comments/create` | 创建评论 | `cardId`, `userId`, `content` |

> [!TIP]
> 要发现更多 dispatch 操作，打开 Codecks Web 应用，在浏览器开发者工具的 Network 标签中观察 `/dispatch/` 请求。

### 6.2 优先级取值

在创建卡片时，`priority` 字段使用字母：`"a"` (最高) / `"b"` / `"c"` (默认) / `"d"` (最低)。

---

## 7. 文件上传流程

```
1. GET /s3/sign?objectName={filename}
   → 返回 {signedUrl, fields, publicUrl}

2. POST {signedUrl}  (multipart form-data)
   → 上传文件到 S3，包含 fields + Content-Type + file

3. POST /dispatch/cards/addFile
   → 将上传的文件关联到卡片
```

---

## 8. 响应结构

API 返回**扁平化引用结构**，而非嵌套对象：

```json
{
  "_root": {"account": "acc_123"},
  "account": {
    "acc_123": {"name": "My Org", "projects": ["proj_1", "proj_2"]}
  },
  "project": {
    "proj_1": {"name": "Project A"},
    "proj_2": {"name": "Project B"}
  }
}
```

- `_root` 包含顶层引用（ID 字符串或 ID 数组）
- 各实体数据以模型名为 key，值为 `{id: data}` 映射
- 客户端需自行解析引用关系（现有 `ResponseParser` 已实现）

---

## 9. 查询示例速查

```python
# 获取账户名称
{"_root": [{"account": ["name"]}]}

# 获取所有项目
{"_root": [{"account": [{"projects": ["name", "createdAt"]}]}]}

# 搜索卡片标题
{"_root": [{"account": [{"cards({\"title\":{\"op\":\"contains\",\"value\":\"搜索词\"}})": ["title"]}]}]}

# 10张卡片按创建时间排序
{"_root": [{"account": [{"cards({\"deckId\": 123, \"$order\": \"createdAt\", \"$limit\": 10})": ["title"]}]}]}

# 按ID获取卡片
{"card(12345)": ["title", "content", "status"]}

# 嵌套查询：卡片带负责人
{"_root": [{"account": [{"cards": ["title", {"assignee": ["name"]}]}]}]}

# 未完成卡片
{"_root": [{"account": [{"cards({\"status\":{\"op\":\"neq\",\"value\":\"done\"}})": ["title", "status"]}]}]}

# 复合条件
{"_root": [{"account": [{"cards({\"$or\":[{\"effort\":{\"op\":\"gt\",\"value\":5}},{\"effort\":{\"op\":\"lte\",\"value\":1}}]})": ["title", "effort"]}]}]}
```

---

## 10. 现有客户端实现分析

当前 [codecks_client.py](file:///c:/Users/Veewo/.astrbot/data/plugins/astrbot_plugin_codecks_connector/codecks_client.py) 已实现：

| 功能模块 | 方法 | 状态 |
|---|---|---|
| **核心** | `query()`, `dispatch()` | ✅ 含自动重试和速率限制 |
| **账户** | `get_account_info()` | ✅ |
| **项目** | `get_projects()`, `get_project()` | ✅ |
| **卡组** | `get_decks()`, `get_deck()` | ✅ |
| **卡片** | `get_cards()`, `get_card()`, `create_card()`, `update_card()`, `complete_card()`, `reopen_card()` | ✅ |
| **评论** | `add_comment()` | ✅ |
| **文件** | `upload_file()`, `attach_file_to_card()`, `upload_and_attach_file()` | ✅ |
| **里程碑** | `get_milestones()`, `get_milestone()` | ✅ |
| **用户** | `get_users()`, `get_user_by_id()`, `get_current_user()`, `get_current_user_id()` | ✅ |
| **手牌** | `get_hand_cards()` | ✅ |
| **标签** | `get_tags()` | ✅ |
| **冲刺** | `get_sprints()` | ✅ |
| **统计** | `get_card_stats()` | ✅ |

### 可能的扩展方向

- **Resolvable（讨论线程）**：获取 / 创建 / 关闭讨论
- **WorkflowItem（工作流项）**：工作流状态管理
- **Sprint 详细管理**：创建 / 更新冲刺
- **Deck 创建/更新**：创建新卡组
- **批量操作**：批量更新卡片状态
- **Webhook/实时通知**：（需进一步调查是否支持）
