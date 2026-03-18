"""
Codecks API 客户端
用于与 Codecks 项目管理平台进行交互
"""

import json
from typing import Any, Optional
import aiohttp


class CodecksClient:
    """Codecks API 客户端"""
    
    BASE_URL = "https://api.codecks.io"
    
    def __init__(self, token: str, subdomain: str):
        """
        初始化 Codecks 客户端
        
        Args:
            token: 认证令牌（从 cookie 'at' 获取）
            subdomain: 组织子域名（如 team123.codecks.io 中的 team123）
        """
        self.token = token
        self.subdomain = subdomain
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    def _get_headers(self) -> dict:
        """获取请求头"""
        return {
            "X-Auth-Token": self.token,
            "X-Account": self.subdomain,
            "Content-Type": "application/json",
        }
    
    async def close(self):
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def query(self, query: dict) -> dict:
        """
        执行查询操作
        
        Args:
            query: 查询字典，如 {"_root": [{"account": ["name"]}]}
        
        Returns:
            查询结果
        """
        session = await self._get_session()
        headers = self._get_headers()
        
        async with session.post(
            f"{self.BASE_URL}/",
            headers=headers,
            data=json.dumps({"query": query})
        ) as response:
            response.raise_for_status()
            return await response.json()
    
    async def dispatch(self, action: str, data: dict) -> dict:
        """
        执行写入操作
        
        Args:
            action: 操作名称，如 "cards/create"
            data: 操作数据
        
        Returns:
            操作结果
        """
        session = await self._get_session()
        headers = self._get_headers()
        
        async with session.post(
            f"{self.BASE_URL}/dispatch/{action}",
            headers=headers,
            data=json.dumps(data)
        ) as response:
            response.raise_for_status()
            return await response.json()
    
    # ==================== 账户/组织相关 ====================
    
    async def get_account_info(self) -> dict:
        """获取账户/组织信息"""
        result = await self.query({
            "_root": [{"account": ["id", "name", "createdAt"]}]
        })
        return result.get("account", {})
    
    # ==================== 项目相关 ====================
    
    async def get_projects(self) -> list:
        """获取所有项目"""
        result = await self.query({
            "_root": [{"account": [{"projects": ["id", "name", "description", "createdAt", "isArchived"]}]}]
        })
        return result.get("account", {}).get("projects", [])
    
    async def get_project(self, project_id: int) -> dict:
        """获取单个项目详情"""
        result = await self.query({
            f"project({project_id})": ["id", "name", "description", "createdAt", "isArchived"]
        })
        return result.get("project", {})
    
    # ==================== 牌组相关 ====================
    
    async def get_decks(self, project_id: Optional[int] = None) -> list:
        """
        获取牌组列表
        
        Args:
            project_id: 可选，按项目筛选
        """
        if project_id:
            query = {
                "_root": [{
                    "account": [{
                        f'decks({{"projectId": {project_id}}})': ["id", "name", "createdAt", "isArchived"]
                    }]
                }]
            }
        else:
            query = {
                "_root": [{"account": [{"decks": ["id", "name", "createdAt", "isArchived"]}]}]
            }
        result = await self.query(query)
        return result.get("account", {}).get("decks", [])
    
    async def get_deck(self, deck_id: int) -> dict:
        """获取单个牌组详情"""
        result = await self.query({
            f"deck({deck_id})": ["id", "name", "createdAt", "isArchived", "projectId"]
        })
        return result.get("deck", {})
    
    # ==================== 卡片相关 ====================
    
    async def get_cards(
        self,
        deck_id: Optional[int] = None,
        project_id: Optional[int] = None,
        milestone_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        order: str = "-createdAt"
    ) -> list:
        """
        获取卡片列表
        
        Args:
            deck_id: 牌组 ID
            project_id: 项目 ID
            milestone_id: 里程碑 ID
            assignee_id: 负责人 ID
            status: 状态（如 "done", "inProgress"）
            search: 搜索关键词
            limit: 返回数量限制
            order: 排序字段（- 表示降序）
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
        result = await self.query({
            "_root": [{
                "account": [{
                    f"cards({query_str})": [
                        "id", "title", "content", "status", "effort", "priority",
                        "createdAt", "updatedAt", "completedAt", "dueDate",
                        "deckId", "milestoneId", "assigneeId", "userId"
                    ]
                }]
            }]
        })
        return result.get("account", {}).get("cards", [])
    
    async def get_card(self, card_id: int) -> dict:
        """获取单个卡片详情"""
        result = await self.query({
            f"card({card_id})": [
                "id", "title", "content", "status", "effort", "priority",
                "createdAt", "updatedAt", "completedAt", "dueDate",
                "deckId", "milestoneId", "assigneeId", "userId"
            ]
        })
        return result.get("card", {})
    
    async def create_card(
        self,
        title: str,
        content: str = "",
        deck_id: Optional[int] = None,
        milestone_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        effort: int = 0,
        priority: str = "c",
        user_id: Optional[int] = None,
        put_on_hand: bool = False
    ) -> dict:
        """
        创建卡片
        
        Args:
            title: 卡片标题
            content: 卡片内容
            deck_id: 牌组 ID
            milestone_id: 里程碑 ID
            assignee_id: 负责人 ID
            effort: 工作量
            priority: 优先级（a, b, c, d）
            user_id: 创建者 ID
            put_on_hand: 是否放入手牌
        """
        data = {
            "title": title,
            "content": content,
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
    
    async def update_card(self, card_id: int, user_id: int, **kwargs) -> dict:
        """
        更新卡片
        
        Args:
            card_id: 卡片 ID
            user_id: 操作者 ID
            **kwargs: 要更新的字段
        """
        data = {"cardId": card_id, "userId": user_id}
        data.update(kwargs)
        return await self.dispatch("cards/update", data)
    
    async def complete_card(self, card_id: int, user_id: int) -> dict:
        """完成卡片"""
        return await self.dispatch("cards/complete", {"cardId": card_id, "userId": user_id})
    
    async def reopen_card(self, card_id: int, user_id: int) -> dict:
        """重新打开卡片"""
        return await self.dispatch("cards/reopen", {"cardId": card_id, "userId": user_id})
    
    # ==================== 里程碑相关 ====================
    
    async def get_milestones(self, project_id: Optional[int] = None) -> list:
        """
        获取里程碑列表
        
        Args:
            project_id: 可选，按项目筛选
        """
        if project_id:
            query = {
                "_root": [{
                    "account": [{
                        f'milestones({{"projectId": {project_id}}})': ["id", "name", "description", "dueDate", "completedAt", "createdAt"]
                    }]
                }]
            }
        else:
            query = {
                "_root": [{"account": [{"milestones": ["id", "name", "description", "dueDate", "completedAt", "createdAt"]}]}]
            }
        result = await self.query(query)
        return result.get("account", {}).get("milestones", [])
    
    async def get_milestone(self, milestone_id: int) -> dict:
        """获取单个里程碑详情"""
        result = await self.query({
            f"milestone({milestone_id})": ["id", "name", "description", "dueDate", "completedAt", "createdAt", "projectId"]
        })
        return result.get("milestone", {})
    
    # ==================== 用户相关 ====================
    
    async def get_users(self) -> list:
        """获取组织成员列表"""
        result = await self.query({
            "_root": [{"account": [{"users": ["id", "name", "email", "createdAt"]}]}]
        })
        return result.get("account", {}).get("users", [])
    
    async def get_current_user(self) -> dict:
        """获取当前用户信息"""
        result = await self.query({
            "_root": [{"user": ["id", "name", "email"]}]
        })
        return result.get("user", {})
    
    # ==================== 手牌相关 ====================
    
    async def get_hand_cards(self, user_id: Optional[int] = None) -> list:
        """
        获取手牌（个人任务）
        
        Args:
            user_id: 用户 ID，不指定则获取当前用户
        """
        if user_id:
            query = {
                "_root": [{
                    "account": [{
                        f'cards({{"assigneeId": {user_id}, "status": {{"op": "neq", "value": "done"}}}})': [
                            "id", "title", "status", "effort", "priority", "dueDate"
                        ]
                    }]
                }]
            }
        else:
            query = {
                "_root": [{
                    "user": [{
                        "hand": ["id", "title", "status", "effort", "priority", "dueDate"]
                    }]
                }]
            }
        result = await self.query(query)
        if "user" in result:
            return result.get("user", {}).get("hand", [])
        return result.get("account", {}).get("cards", [])
    
    # ==================== 统计相关 ====================
    
    async def get_card_stats(self, project_id: Optional[int] = None) -> dict:
        """
        获取卡片统计信息
        
        Args:
            project_id: 项目 ID，不指定则统计全部
        """
        filters = {}
        if project_id:
            filters["projectId"] = project_id
        
        query_str = json.dumps(filters) if filters else ""
        
        result = await self.query({
            "_root": [{
                "account": [{
                    f"cards({query_str})": ["id", "status", "effort", "priority"]
                }]
            }]
        })
        
        cards = result.get("account", {}).get("cards", [])
        
        stats = {
            "total": len(cards),
            "done": sum(1 for c in cards if c.get("status") == "done"),
            "inProgress": sum(1 for c in cards if c.get("status") == "inProgress"),
            "todo": sum(1 for c in cards if c.get("status") == "todo"),
            "totalEffort": sum(c.get("effort", 0) for c in cards),
        }
        stats["completedEffort"] = sum(
            c.get("effort", 0) for c in cards if c.get("status") == "done"
        )
        
        return stats
