"""
Codecks 连接器 - AstrBot 插件
让 AstrBot 可以操作、查询、收集 Codecks 项目管理平台的信息
"""

import os
from typing import Optional
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

from .codecks_client import CodecksClient
from .config_manager import ConfigManager, CodecksConfig


class CodecksConnectorPlugin(Star):
    """Codecks 连接器插件"""
    
    def __init__(self, context: Context):
        super().__init__(context)
        
        # 获取插件数据目录
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data",
            "codecks_connector"
        )
        
        # 初始化配置管理器
        self.config_manager = ConfigManager(self.data_dir)
        self.config: Optional[CodecksConfig] = None
        self.client: Optional[CodecksClient] = None
    
    async def _ensure_client(self) -> tuple[bool, str]:
        """
        确保 Codecks 客户端已初始化
        
        Returns:
            (是否成功, 错误消息)
        """
        if self.config is None:
            self.config = self.config_manager.load()
        
        if not self.config.is_valid():
            return False, "Codecks 未配置，请使用 /codecks config 命令进行配置"
        
        if self.client is None:
            self.client = CodecksClient(
                token=self.config.token,
                subdomain=self.config.subdomain
            )
        
        return True, ""
    
    def _format_card(self, card: dict) -> str:
        """格式化卡片信息"""
        status_emoji = {
            "done": "✅",
            "inProgress": "🔄",
            "todo": "📋"
        }.get(card.get("status", ""), "📌")
        
        priority_emoji = {
            "a": "🔴",
            "b": "🟠",
            "c": "🟡",
            "d": "🟢"
        }.get(card.get("priority", ""), "⚪")
        
        lines = [
            f"{status_emoji} **{card.get('title', '无标题')}** (ID: {card.get('id')})",
            f"   优先级: {priority_emoji} | 工作量: {card.get('effort', 0)}",
        ]
        
        if card.get("dueDate"):
            lines.append(f"   截止日期: {card.get('dueDate')}")
        
        if card.get("content"):
            content = card.get("content", "")[:100]
            if len(card.get("content", "")) > 100:
                content += "..."
            lines.append(f"   内容: {content}")
        
        return "\n".join(lines)
    
    def _format_milestone(self, milestone: dict) -> str:
        """格式化里程碑信息"""
        completed = milestone.get("completedAt") is not None
        status = "✅ 已完成" if completed else "🚧 进行中"
        
        lines = [
            f"🎯 **{milestone.get('name', '无名称')}** (ID: {milestone.get('id')})",
            f"   状态: {status}",
        ]
        
        if milestone.get("dueDate"):
            lines.append(f"   截止日期: {milestone.get('dueDate')}")
        
        if milestone.get("description"):
            lines.append(f"   描述: {milestone.get('description')}")
        
        return "\n".join(lines)
    
    # ==================== 配置命令 ====================
    
    @filter.command_group("codecks", alias={"ck"})
    def codecks(self):
        """Codecks 项目管理命令组"""
        pass
    
    @codecks.command("config")
    async def config_cmd(self, event: AstrMessageEvent, key: str = "", value: str = ""):
        """
        配置 Codecks 连接信息
        
        用法:
        /codecks config - 查看当前配置
        /codecks config token <token> - 设置 API Token
        /codecks config subdomain <subdomain> - 设置组织子域名
        /codecks config userid <user_id> - 设置用户 ID
        """
        if not key:
            # 显示当前配置
            config = self.config_manager.get_config()
            masked_token = config.token[:8] + "..." if config.token else "未设置"
            lines = [
                "📋 **Codecks 配置信息**",
                f"Token: {masked_token}",
                f"组织子域名: {config.subdomain or '未设置'}",
                f"用户 ID: {config.user_id or '未设置'}",
                f"状态: {'✅ 已配置' if config.is_valid() else '❌ 未完成配置'}"
            ]
            yield event.plain_result("\n".join(lines))
            return
        
        key = key.lower()
        
        if key == "token":
            if not value:
                yield event.plain_result("请提供 Token 值，例如: /codecks config token your_token_here")
                return
            self.config_manager.update(token=value)
            self.client = None  # 重置客户端
            yield event.plain_result("✅ Token 已更新")
        
        elif key == "subdomain":
            if not value:
                yield event.plain_result("请提供子域名，例如: /codecks config subdomain team123")
                return
            self.config_manager.update(subdomain=value)
            self.client = None
            yield event.plain_result("✅ 组织子域名已更新")
        
        elif key == "userid":
            if not value:
                yield event.plain_result("请提供用户 ID，例如: /codecks config userid 123")
                return
            try:
                user_id = int(value)
                self.config_manager.update(user_id=user_id)
                yield event.plain_result("✅ 用户 ID 已更新")
            except ValueError:
                yield event.plain_result("❌ 用户 ID 必须是数字")
        
        else:
            yield event.plain_result(f"未知的配置项: {key}\n可配置项: token, subdomain, userid")
    
    # ==================== 项目命令 ====================
    
    @codecks.command("projects", alias={"项目"})
    async def projects(self, event: AstrMessageEvent):
        """获取所有项目列表"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            projects = await self.client.get_projects()
            
            if not projects:
                yield event.plain_result("📭 没有找到任何项目")
                return
            
            lines = ["📁 **项目列表**\n"]
            for p in projects:
                archived = " (已归档)" if p.get("isArchived") else ""
                lines.append(f"• **{p.get('name')}** (ID: {p.get('id')}){archived}")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取项目失败: {e}")
            yield event.plain_result(f"❌ 获取项目失败: {str(e)}")
    
    # ==================== 牌组命令 ====================
    
    @codecks.command("decks", alias={"牌组"})
    async def decks(self, event: AstrMessageEvent, project_id: int = 0):
        """获取牌组列表，可选按项目筛选"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            pid = project_id if project_id > 0 else None
            decks = await self.client.get_decks(project_id=pid)
            
            if not decks:
                yield event.plain_result("📭 没有找到任何牌组")
                return
            
            lines = ["🃏 **牌组列表**\n"]
            for d in decks:
                archived = " (已归档)" if d.get("isArchived") else ""
                lines.append(f"• **{d.get('name')}** (ID: {d.get('id')}){archived}")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取牌组失败: {e}")
            yield event.plain_result(f"❌ 获取牌组失败: {str(e)}")
    
    # ==================== 卡片命令 ====================
    
    @codecks.command("cards", alias={"卡片"})
    async def cards(
        self, 
        event: AstrMessageEvent, 
        deck_id: int = 0,
        limit: int = 10
    ):
        """获取卡片列表，可选按牌组筛选"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            did = deck_id if deck_id > 0 else None
            cards = await self.client.get_cards(deck_id=did, limit=limit)
            
            if not cards:
                yield event.plain_result("📭 没有找到任何卡片")
                return
            
            lines = ["📋 **卡片列表**\n"]
            for c in cards[:limit]:
                lines.append(self._format_card(c))
                lines.append("")
            
            if len(cards) > limit:
                lines.append(f"... 还有 {len(cards) - limit} 张卡片")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取卡片失败: {e}")
            yield event.plain_result(f"❌ 获取卡片失败: {str(e)}")
    
    @codecks.command("card")
    async def card(self, event: AstrMessageEvent, card_id: int):
        """获取单个卡片详情"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            card = await self.client.get_card(card_id)
            
            if not card:
                yield event.plain_result(f"❌ 未找到卡片 ID: {card_id}")
                return
            
            lines = [
                "📋 **卡片详情**\n",
                self._format_card(card),
            ]
            
            if card.get("content"):
                lines.append(f"\n**完整内容:**\n{card.get('content')}")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取卡片详情失败: {e}")
            yield event.plain_result(f"❌ 获取卡片详情失败: {str(e)}")
    
    @codecks.command("search", alias={"搜索"})
    async def search(self, event: AstrMessageEvent, keyword: str):
        """搜索卡片"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            cards = await self.client.get_cards(search=keyword, limit=20)
            
            if not cards:
                yield event.plain_result(f"📭 没有找到包含 '{keyword}' 的卡片")
                return
            
            lines = [f"🔍 **搜索结果: {keyword}**\n"]
            for c in cards:
                lines.append(self._format_card(c))
                lines.append("")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 搜索卡片失败: {e}")
            yield event.plain_result(f"❌ 搜索失败: {str(e)}")
    
    @codecks.command("newcard", alias={"新建卡片", "创建卡片"})
    async def newcard(
        self, 
        event: AstrMessageEvent,
        title: str,
        deck_id: int = 0,
        effort: int = 0,
        priority: str = "c"
    ):
        """
        创建新卡片
        
        用法: /codecks newcard <标题> [牌组ID] [工作量] [优先级]
        示例: /codecks newcard "修复登录Bug" 123 5 b
        """
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        if not self.config.user_id:
            yield event.plain_result("❌ 请先设置用户 ID: /codecks config userid <id>")
            return
        
        try:
            result = await self.client.create_card(
                title=title,
                deck_id=deck_id if deck_id > 0 else None,
                effort=effort,
                priority=priority,
                user_id=self.config.user_id
            )
            
            card_id = result.get("id") or result.get("cardId")
            yield event.plain_result(f"✅ 卡片创建成功！ID: {card_id}")
        except Exception as e:
            logger.error(f"[Codecks] 创建卡片失败: {e}")
            yield event.plain_result(f"❌ 创建卡片失败: {str(e)}")
    
    @codecks.command("complete", alias={"完成"})
    async def complete(self, event: AstrMessageEvent, card_id: int):
        """完成卡片"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        if not self.config.user_id:
            yield event.plain_result("❌ 请先设置用户 ID: /codecks config userid <id>")
            return
        
        try:
            await self.client.complete_card(card_id, self.config.user_id)
            yield event.plain_result(f"✅ 卡片 {card_id} 已完成！")
        except Exception as e:
            logger.error(f"[Codecks] 完成卡片失败: {e}")
            yield event.plain_result(f"❌ 完成卡片失败: {str(e)}")
    
    @codecks.command("reopen", alias={"重开", "重新打开"})
    async def reopen(self, event: AstrMessageEvent, card_id: int):
        """重新打开卡片"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        if not self.config.user_id:
            yield event.plain_result("❌ 请先设置用户 ID: /codecks config userid <id>")
            return
        
        try:
            await self.client.reopen_card(card_id, self.config.user_id)
            yield event.plain_result(f"✅ 卡片 {card_id} 已重新打开！")
        except Exception as e:
            logger.error(f"[Codecks] 重新打开卡片失败: {e}")
            yield event.plain_result(f"❌ 重新打开卡片失败: {str(e)}")
    
    # ==================== 里程碑命令 ====================
    
    @codecks.command("milestones", alias={"里程碑"})
    async def milestones(self, event: AstrMessageEvent, project_id: int = 0):
        """获取里程碑列表"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            pid = project_id if project_id > 0 else None
            milestones = await self.client.get_milestones(project_id=pid)
            
            if not milestones:
                yield event.plain_result("📭 没有找到任何里程碑")
                return
            
            lines = ["🎯 **里程碑列表**\n"]
            for m in milestones:
                lines.append(self._format_milestone(m))
                lines.append("")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取里程碑失败: {e}")
            yield event.plain_result(f"❌ 获取里程碑失败: {str(e)}")
    
    # ==================== 手牌命令 ====================
    
    @codecks.command("hand", alias={"手牌", "我的任务"})
    async def hand(self, event: AstrMessageEvent):
        """获取我的手牌（个人任务）"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            cards = await self.client.get_hand_cards()
            
            if not cards:
                yield event.plain_result("📭 你的手牌是空的，没有待办任务")
                return
            
            lines = ["🃏 **我的手牌**\n"]
            for c in cards:
                lines.append(self._format_card(c))
                lines.append("")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取手牌失败: {e}")
            yield event.plain_result(f"❌ 获取手牌失败: {str(e)}")
    
    # ==================== 统计命令 ====================
    
    @codecks.command("stats", alias={"统计"})
    async def stats(self, event: AstrMessageEvent, project_id: int = 0):
        """获取卡片统计信息"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            pid = project_id if project_id > 0 else None
            stats = await self.client.get_card_stats(project_id=pid)
            
            progress = 0
            if stats["total"] > 0:
                progress = (stats["done"] / stats["total"]) * 100
            
            lines = [
                "📊 **卡片统计**\n",
                f"总数: {stats['total']}",
                f"已完成: {stats['done']} ✅",
                f"进行中: {stats['inProgress']} 🔄",
                f"待办: {stats['todo']} 📋",
                f"",
                f"总工作量: {stats['totalEffort']}",
                f"已完成工作量: {stats['completedEffort']}",
                f"",
                f"完成进度: {progress:.1f}%"
            ]
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取统计失败: {e}")
            yield event.plain_result(f"❌ 获取统计失败: {str(e)}")
    
    # ==================== 用户命令 ====================
    
    @codecks.command("users", alias={"用户", "成员"})
    async def users(self, event: AstrMessageEvent):
        """获取组织成员列表"""
        success, error = await self._ensure_client()
        if not success:
            yield event.plain_result(f"❌ {error}")
            return
        
        try:
            users = await self.client.get_users()
            
            if not users:
                yield event.plain_result("📭 没有找到任何成员")
                return
            
            lines = ["👥 **组织成员**\n"]
            for u in users:
                lines.append(f"• **{u.get('name')}** (ID: {u.get('id')})")
            
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"[Codecks] 获取用户失败: {e}")
            yield event.plain_result(f"❌ 获取用户失败: {str(e)}")
    
    # ==================== 帮助命令 ====================
    
    @codecks.command("help", alias={"帮助"})
    async def help_cmd(self, event: AstrMessageEvent):
        """显示帮助信息"""
        lines = [
            "📖 **Codecks 连接器帮助**\n",
            "**配置命令:**",
            "/codecks config - 查看当前配置",
            "/codecks config token <token> - 设置 API Token",
            "/codecks config subdomain <subdomain> - 设置组织子域名",
            "/codecks config userid <id> - 设置用户 ID",
            "",
            "**查询命令:**",
            "/codecks projects - 获取项目列表",
            "/codecks decks [项目ID] - 获取牌组列表",
            "/codecks cards [牌组ID] - 获取卡片列表",
            "/codecks card <卡片ID> - 获取卡片详情",
            "/codecks search <关键词> - 搜索卡片",
            "/codecks milestones [项目ID] - 获取里程碑列表",
            "/codecks hand - 获取我的手牌",
            "/codecks users - 获取成员列表",
            "/codecks stats [项目ID] - 获取统计信息",
            "",
            "**操作命令:**",
            "/codecks newcard <标题> [牌组ID] [工作量] [优先级] - 创建卡片",
            "/codecks complete <卡片ID> - 完成卡片",
            "/codecks reopen <卡片ID> - 重新打开卡片",
            "",
            "**别名:**",
            "ck = codecks",
            "例如: /ck cards 等同于 /codecks cards"
        ]
        yield event.plain_result("\n".join(lines))
    
    # ==================== 生命周期 ====================
    
    async def terminate(self):
        """插件卸载时清理资源"""
        if self.client:
            await self.client.close()
            logger.info("[Codecks] 客户端已关闭")
