"""
Codecks API 客户端
用于与 Codecks 项目管理平台进行交互

基于 Codecks API 文档: https://manual.codecks.io/api/
API Reference: https://manual.codecks.io/api-reference/
"""

import json
import asyncio
import mimetypes
import time
from typing import Any, Optional
import aiohttp


# ==================== 异常类 ====================

class CodecksError(Exception):
    """Codecks API 错误基类"""
    pass


class AuthenticationError(CodecksError):
    """认证错误"""
    pass


class RateLimitError(CodecksError):
    """速率限制错误"""
    def __init__(self, message: str, retry_after: float = 5.0):
        super().__init__(message)
        self.retry_after = retry_after


class NotFoundError(CodecksError):
    """资源未找到错误"""
    pass


class NetworkError(CodecksError):
    """网络错误"""
    pass


# ==================== 响应解析器 ====================

class ResponseParser:
    """
    Codecks API 响应解析器

    Codecks API 返回扁平化引用结构，如：
    {
      "_root": {"account": "acc_123"},
      "account": {"acc_123": {"name": "My Org", "projects": ["p1", "p2"]}},
      "project": {"p1": {"name": "A"}, "p2": {"name": "B"}}
    }

    本解析器将其转为常规嵌套对象。
    """

    def parse(self, raw_result: dict) -> dict:
        """解析 Codecks API 返回的引用结构"""
        if "_root" not in raw_result:
            return raw_result

        result = {}
        root = raw_result.get("_root", {})

        for key, ref_value in root.items():
            if key == "_root":
                continue

            entity_data = raw_result.get(key, {})

            if isinstance(ref_value, str):
                # 单个 ID 引用
                item = entity_data.get(ref_value, {})
                result[key] = self._resolve_item(item, raw_result)

            elif isinstance(ref_value, list):
                # ID 列表引用
                items = []
                for id_val in ref_value:
                    item = entity_data.get(str(id_val), {})
                    if item:
                        items.append(self._resolve_item(item, raw_result))
                result[key] = items

            elif isinstance(ref_value, dict):
                result[key] = self._resolve_nested(ref_value, entity_data, raw_result)
            else:
                result[key] = entity_data

        return result

    def _find_entity_data(self, key: str, raw_result: dict) -> dict:
        """
        在 raw_result 中查找实体数据，处理单复数映射

        Codecks API 的关系名用复数（如 projects），但实体数据键用单数（如 project）
        """
        if key in raw_result:
            return raw_result[key]
        if key.endswith("s") and key[:-1] in raw_result:
            return raw_result[key[:-1]]
        if key.endswith("es") and key[:-2] in raw_result:
            return raw_result[key[:-2]]
        if key.endswith("ies"):
            singular = key[:-3] + "y"
            if singular in raw_result:
                return raw_result[singular]
        return None

    def _resolve_item(self, item: dict, raw_result: dict) -> dict:
        """解析单个项目中的嵌套引用"""
        if not isinstance(item, dict):
            return item

        resolved = dict(item)

        for key, value in list(resolved.items()):
            if isinstance(value, list) and len(value) > 0:
                if isinstance(value[0], str):
                    entity_data = self._find_entity_data(key, raw_result)
                    if entity_data and isinstance(entity_data, dict):
                        items = []
                        for id_val in value:
                            entity = entity_data.get(id_val)
                            if isinstance(entity, dict):
                                items.append(self._resolve_item(entity, raw_result))
                        if items:
                            resolved[key] = items
                elif isinstance(value[0], dict):
                    resolved[key] = [self._resolve_item(v, raw_result) for v in value]

            elif isinstance(value, str) and key.endswith("Id") and len(key) > 2:
                entity_key = key[:-2]
                entity_lookup = entity_key
                if entity_key == "assignee":
                    entity_lookup = "user"
                entity_data = self._find_entity_data(entity_lookup, raw_result)
                if entity_data and isinstance(entity_data, dict):
                    if value in entity_data:
                        resolved[entity_key] = entity_data[value]

        return resolved

    def _resolve_nested(self, refs: dict, entity_data: dict, raw_result: dict) -> dict:
        """递归解析嵌套的引用结构"""
        result = {}
        for key, ref_id in refs.items():
            if isinstance(ref_id, str):
                item = entity_data.get(ref_id, {})
                result[key] = self._resolve_item(item, raw_result)
            elif isinstance(ref_id, list):
                result[key] = [
                    self._resolve_item(entity_data.get(str(id_val), {}), raw_result)
                    for id_val in ref_id
                ]
            elif isinstance(ref_id, dict):
                result[key] = self._resolve_nested(ref_id, entity_data, raw_result)
            else:
                result[key] = ref_id
        return result


# ==================== API 客户端 ====================

class CodecksClient:
    """
    Codecks API 客户端

    提供查询（读取）和 dispatch（写入）两类操作。
    """

    BASE_URL = "https://api.codecks.io"
    MAX_RETRIES = 3

    def __init__(
        self,
        token: str,
        subdomain: str,
        rate_limit_delay: float = 0.15
    ):
        """
        Args:
            token: 认证令牌（从 cookie 'at' 获取）
            subdomain: 组织子域名
            rate_limit_delay: 请求间隔（秒）
        """
        self.token = token
        self.subdomain = subdomain
        self.rate_limit_delay = rate_limit_delay
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_request_time: float = 0
        self._parser = ResponseParser()
        self._cached_user_id: Optional[str] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _get_headers(self) -> dict:
        return {
            "X-Auth-Token": self.token,
            "X-Account": self.subdomain,
            "Content-Type": "application/json",
        }

    async def _wait_for_rate_limit(self):
        if self.rate_limit_delay > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit_delay:
                await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    async def close(self):
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()

    # ==================== 核心请求方法 ====================

    async def query(self, query: dict, retries: int = 0) -> dict:
        """
        执行查询操作（读取数据）

        Args:
            query: 查询字典，如 {"_root": [{"account": ["name"]}]}
        """
        await self._wait_for_rate_limit()
        session = await self._get_session()
        headers = self._get_headers()

        try:
            async with session.post(
                f"{self.BASE_URL}/",
                headers=headers,
                data=json.dumps({"query": query}),
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 401:
                    raise AuthenticationError("认证失败，请检查 Token 是否正确")
                if response.status == 429:
                    if retries < self.MAX_RETRIES:
                        wait_time = 5.0 * (retries + 1)
                        await asyncio.sleep(wait_time)
                        return await self.query(query, retries + 1)
                    raise RateLimitError("请求过于频繁，已达到最大重试次数")
                if response.status == 500:
                    body = await response.text()
                    raise CodecksError(f"服务器内部错误 (500): {body[:200]}")

                response.raise_for_status()
                raw_result = await response.json()

            return self._parser.parse(raw_result)

        except aiohttp.ClientError as e:
            raise NetworkError(f"网络请求失败: {e}")

    async def dispatch(self, action: str, data: dict, retries: int = 0) -> dict:
        """
        执行写入操作

        Args:
            action: 操作名称，如 "cards/create"
            data: 操作数据
        """
        await self._wait_for_rate_limit()
        session = await self._get_session()
        headers = self._get_headers()

        try:
            async with session.post(
                f"{self.BASE_URL}/dispatch/{action}",
                headers=headers,
                data=json.dumps(data),
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 401:
                    raise AuthenticationError("认证失败，请检查 Token 是否正确")
                if response.status == 429:
                    if retries < self.MAX_RETRIES:
                        wait_time = 5.0 * (retries + 1)
                        await asyncio.sleep(wait_time)
                        return await self.dispatch(action, data, retries + 1)
                    raise RateLimitError("请求过于频繁，已达到最大重试次数")
                if response.status == 404:
                    raise NotFoundError(f"资源未找到: {action}")
                if response.status == 500:
                    body = await response.text()
                    raise CodecksError(f"服务器内部错误 (500): {body[:200]}")

                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientError as e:
            raise NetworkError(f"网络请求失败: {e}")

    # ==================== 账户 ====================

    async def get_account_info(self) -> dict:
        """获取账户/组织信息"""
        result = await self.query({
            "_root": [{"account": ["name", "createdAt"]}]
        })
        return result.get("account", {})

    # ==================== 项目 ====================

    async def get_projects(self) -> list:
        """获取所有项目"""
        result = await self.query({
            "_root": [{"account": [{"projects": [
                "name", "createdAt", "visibility", "accountSeq"
            ]}]}]
        })
        return result.get("account", {}).get("projects", [])

    async def get_project(self, project_id: str) -> dict:
        """获取单个项目详情"""
        result = await self.query({
            f"project({project_id})": [
                "name", "createdAt", "visibility", "accountSeq"
            ]
        })
        return result.get("project", {})

    # ==================== 卡组 ====================

    async def get_decks(self, project_id: str = None) -> list:
        """获取卡组列表，可选按项目筛选"""
        deck_fields = [
            "title", "description", "createdAt", "isDeleted",
            "accountSeq"
        ]
        if project_id:
            query = {
                "_root": [{"account": [{
                    f'decks({{"projectId": "{project_id}"}})': deck_fields
                }]}]
            }
        else:
            query = {
                "_root": [{"account": [{"decks": deck_fields}]}]
            }
        result = await self.query(query)
        decks = result.get("account", {}).get("decks", [])
        # 过滤已删除项
        return [d for d in decks if not d.get("isDeleted")]

    async def get_deck(self, deck_id: str) -> dict:
        """获取单个卡组详情"""
        result = await self.query({
            f"deck({deck_id})": [
                "title", "description", "createdAt", "isDeleted",
                "accountSeq"
            ]
        })
        return result.get("deck", {})

    # ==================== 卡片 ====================

    async def get_cards(
        self,
        deck_id: str = None,
        project_id: str = None,
        milestone_id: str = None,
        assignee_id: str = None,
        status: str = None,
        search: str = None,
        limit: int = 50,
        order: str = "-createdAt"
    ) -> list:
        """
        获取卡片列表

        Args:
            deck_id: 卡组 ID
            project_id: 项目 ID
            milestone_id: 里程碑 ID
            assignee_id: 负责人 ID
            status: 状态（"created" / "started" / "done"）
            search: 搜索关键词（全文搜索 content）
            limit: 返回数量限制（最大 3000）
            order: 排序字段（"-" 前缀表示降序）
        """
        filters = {}
        if deck_id:
            filters["deckId"] = deck_id
        if project_id:
            filters["projectId"] = project_id
        if milestone_id:
            filters["milestoneId"] = milestone_id
        if assignee_id:
            filters["assigneeId"] = assignee_id
        if status:
            filters["status"] = status
        if search:
            filters["content"] = {"op": "search", "value": search}

        filters["$order"] = order
        filters["$limit"] = min(limit, 3000)

        query_str = json.dumps(filters)
        card_fields = [
            "title", "content", "status", "effort", "priority",
            "createdAt", "lastUpdatedAt", "dueDate", "derivedStatus",
            "masterTags", "tags", "accountSeq",
        ]
        result = await self.query({
            "_root": [{"account": [{
                f"cards({query_str})": card_fields
            }]}]
        })
        return result.get("account", {}).get("cards", [])

    async def get_card(self, card_id: str) -> dict:
        """获取单个卡片详情"""
        result = await self.query({
            f"card({card_id})": [
                "title", "content", "status", "effort", "priority",
                "createdAt", "lastUpdatedAt", "dueDate", "derivedStatus",
                "masterTags", "tags", "accountSeq",
                "checkboxStats", "childCardInfo",
            ]
        })
        return result.get("card", {})

    async def create_card(
        self,
        title: str,
        content: str = "",
        deck_id: str = None,
        milestone_id: str = None,
        assignee_id: str = None,
        effort: int = 0,
        priority: str = "c",
        user_id: str = None,
        put_on_hand: bool = False
    ) -> dict:
        """
        创建卡片

        Args:
            title: 卡片标题（会作为 content 第一行）
            content: 卡片正文
            deck_id: 卡组 ID
            effort: 工作量
            priority: 优先级（a=最高, b, c=默认, d=最低）
            put_on_hand: 是否放入手牌
        """
        full_content = title if not content else f"{title}\n{content}"
        data = {
            "content": full_content,
            "deckId": deck_id,
            "milestoneId": milestone_id,
            "assigneeId": assignee_id,
            "effort": effort,
            "priority": priority,
            "userId": user_id,
            "putOnHand": put_on_hand,
            "masterTags": [],
            "attachments": [],
            "childCards": []
        }
        return await self.dispatch("cards/create", data)

    async def update_card(self, card_id: str, user_id: str, **kwargs) -> dict:
        """更新卡片字段"""
        data = {"cardId": card_id, "userId": user_id}
        data.update(kwargs)
        return await self.dispatch("cards/update", data)

    async def complete_card(self, card_id: str, user_id: str) -> dict:
        """完成卡片"""
        return await self.dispatch("cards/complete", {
            "cardId": card_id, "userId": user_id
        })

    async def reopen_card(self, card_id: str, user_id: str) -> dict:
        """重新打开卡片"""
        return await self.dispatch("cards/reopen", {
            "cardId": card_id, "userId": user_id
        })

    async def add_comment(self, card_id: str, user_id: str, content: str) -> dict:
        """添加评论"""
        return await self.dispatch("comments/create", {
            "cardId": card_id, "userId": user_id, "content": content
        })

    # ==================== 文件上传 ====================

    async def get_upload_url(self, file_name: str) -> dict:
        """获取文件上传签名 URL"""
        await self._wait_for_rate_limit()
        session = await self._get_session()
        headers = self._get_headers()

        try:
            async with session.get(
                f"{self.BASE_URL}/s3/sign",
                params={"objectName": file_name},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            raise NetworkError(f"获取上传 URL 失败: {e}")

    async def upload_file(self, file_name: str, file_data: bytes) -> dict:
        """上传文件到 S3"""
        sign_data = await self.get_upload_url(file_name)
        signed_url = sign_data["signedUrl"]
        fields = sign_data.get("fields", {})

        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        fields["Content-Type"] = content_type

        session = await self._get_session()
        form_data = aiohttp.FormData()
        for k, v in fields.items():
            form_data.add_field(k, v)
        form_data.add_field("file", file_data, filename=file_name, content_type=content_type)

        async with session.post(signed_url, data=form_data) as response:
            response.raise_for_status()

        return sign_data

    async def attach_file_to_card(
        self, card_id: str, sign_data: dict,
        file_name: str, file_size: int, user_id: str
    ) -> dict:
        """将已上传的文件附加到卡片"""
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        return await self.dispatch("cards/addFile", {
            "cardId": card_id,
            "userId": user_id,
            "fileData": {
                "fileName": file_name,
                "url": sign_data.get("publicUrl", ""),
                "size": file_size,
                "type": content_type,
            }
        })

    async def upload_and_attach_file(
        self, card_id: str, file_name: str,
        file_data: bytes, user_id: str
    ) -> dict:
        """上传文件并附加到卡片（一步完成）"""
        sign_data = await self.upload_file(file_name, file_data)
        return await self.attach_file_to_card(
            card_id, sign_data, file_name, len(file_data), user_id
        )

    # ==================== 里程碑 ====================

    async def get_milestones(self) -> list:
        """获取里程碑列表"""
        result = await self.query({
            "_root": [{"account": [{"milestones": [
                "name", "date", "startDate",
                "createdAt", "isDeleted", "isGlobal", "color", "accountSeq"
            ]}]}]
        })
        milestones = result.get("account", {}).get("milestones", [])
        return [m for m in milestones if not m.get("isDeleted")]

    async def get_milestone(self, milestone_id: str) -> dict:
        """获取单个里程碑详情"""
        result = await self.query({
            f"milestone({milestone_id})": [
                "name", "date", "startDate",
                "createdAt", "isDeleted", "isGlobal", "color", "accountSeq"
            ]
        })
        return result.get("milestone", {})

    # ==================== 用户 ====================

    async def get_current_user(self) -> dict:
        """获取当前用户信息"""
        result = await self.query({
            "_root": [{"user": ["name", "createdAt"]}]
        })
        return result.get("user", {})

    async def get_current_user_id(self) -> Optional[str]:
        """获取当前用户 ID（缓存）"""
        if self._cached_user_id is not None:
            return self._cached_user_id
        try:
            user = await self.get_current_user()
            uid = user.get("id")
            if uid:
                self._cached_user_id = uid
                return uid
        except Exception:
            pass
        return None

    async def get_users(self) -> list:
        """获取组织成员列表"""
        users_map = {}

        # 方法1: 当前用户
        try:
            current_user = await self.get_current_user()
            if current_user and current_user.get("id"):
                users_map[current_user["id"]] = current_user
        except Exception:
            pass

        # 方法2: 通过项目的 projectUsers 获取
        try:
            result = await self.query({
                "_root": [{"account": [{"projects": [{
                    "projectUsers": [{"user": [
                        "name"
                    ]}]
                }]}]}]
            })
            projects = result.get("account", {}).get("projects", [])
            for project in projects:
                for pu in project.get("projectUsers", []):
                    user = pu.get("user", {})
                    if user and user.get("id") and user["id"] not in users_map:
                        users_map[user["id"]] = user
        except Exception:
            pass

        return list(users_map.values())

    async def get_user_by_id(self, user_id: str) -> dict:
        """通过 ID 获取用户信息"""
        result = await self.query({
            f"user({user_id})": ["name"]
        })
        return result.get("user", {})

    # ==================== 手牌 ====================

    async def get_hand_cards(self, user_id: str = None) -> list:
        """获取手牌（个人待办）"""
        card_fields = [
            "title", "status", "effort", "priority",
            "dueDate", "accountSeq"
        ]
        if user_id:
            query = {
                "_root": [{"account": [{
                    f'cards({{"assigneeId": "{user_id}", "status": {{"op": "neq", "value": "done"}}}})': card_fields
                }]}]
            }
            result = await self.query(query)
            return result.get("account", {}).get("cards", [])
        else:
            query = {"_root": [{"user": [{"hand": card_fields}]}]}
            result = await self.query(query)
            return result.get("user", {}).get("hand", [])

    # ==================== 标签 ====================

    async def get_tags(self, project_id: str = None) -> list:
        """获取标签列表"""
        tag_fields = ["name", "color"]
        if project_id:
            query = {
                "_root": [{"account": [{
                    f'projectTags({{"projectId": "{project_id}"}})': tag_fields
                }]}]
            }
        else:
            query = {"_root": [{"account": [{"projectTags": tag_fields}]}]}
        result = await self.query(query)
        return result.get("account", {}).get("projectTags", [])

    # ==================== 冲刺 ====================

    async def get_sprints(self, project_id: str = None) -> list:
        """获取冲刺列表"""
        sprint_fields = ["name", "createdAt"]
        if project_id:
            query = {
                "_root": [{"account": [{
                    f'sprints({{"projectId": "{project_id}"}})': sprint_fields
                }]}]
            }
        else:
            query = {"_root": [{"account": [{"sprints": sprint_fields}]}]}
        result = await self.query(query)
        return result.get("account", {}).get("sprints", [])

    # ==================== 统计 ====================

    async def get_card_stats(self, project_id: str = None) -> dict:
        """获取卡片统计信息"""
        filters = {}
        if project_id:
            filters["projectId"] = project_id

        if filters:
            query_str = json.dumps(filters)
            card_key = f"cards({query_str})"
        else:
            card_key = "cards"

        result = await self.query({
            "_root": [{"account": [{
                card_key: ["status", "effort", "priority"]
            }]}]
        })

        cards = result.get("account", {}).get("cards", [])

        stats = {
            "total": len(cards),
            "done": sum(1 for c in cards if c.get("status") == "done"),
            "started": sum(1 for c in cards if c.get("status") == "started"),
            "created": sum(1 for c in cards if c.get("status") not in ("done", "started")),
            "totalEffort": sum(c.get("effort", 0) or 0 for c in cards),
            "doneEffort": sum(
                (c.get("effort", 0) or 0) for c in cards if c.get("status") == "done"
            ),
            "startedEffort": sum(
                (c.get("effort", 0) or 0) for c in cards if c.get("status") == "started"
            ),
        }
        return stats
