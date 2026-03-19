"""
Codecks 连接器 — AstrBot 插件
通过聊天命令连接、查询和管理 Codecks 项目管理平台
"""

from typing import Optional
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig, logger

from .codecks_client import CodecksClient, CodecksError
from . import formatters


class CodecksConnectorPlugin(Star):
    """Codecks 连接器插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.config = config
        self.client: Optional[CodecksClient] = None
        self._auto_user_id: Optional[str] = None

    def _get_token(self) -> str:
        return self.config.get("token", "")

    def _get_subdomain(self) -> str:
        return self.config.get("subdomain", "")

    def _is_configured(self) -> bool:
        return bool(self._get_token() and self._get_subdomain())

    async def _ensure_client(self) -> tuple:
        """确保客户端已初始化，返回 (成功, 错误消息)"""
        if not self._is_configured():
            return False, "❌ Codecks 未配置，请在 WebUI 插件管理页面配置 Token 和子域名"
        if self.client is None:
            self.client = CodecksClient(
                token=self._get_token(),
                subdomain=self._get_subdomain(),
                rate_limit_delay=self.config.get("rate_limit_delay", 0.15)
            )
        return True, ""

    async def _get_user_id(self) -> tuple:
        """获取用户 ID，返回 (user_id, 错误消息)"""
        if self._auto_user_id:
            return self._auto_user_id, ""
        if self.client:
            try:
                uid = await self.client.get_current_user_id()
                if uid:
                    self._auto_user_id = uid
                    return uid, ""
            except Exception as e:
                logger.warning(f"[Codecks] 自动获取用户 ID 失败: {e}")
        return None, "❌ 无法获取用户 ID，请检查 Token 是否有效"

    async def _pre_check(self, need_user: bool = False):
        """统一前置检查，返回 (成功, 错误消息, user_id)"""
        ok, err = await self._ensure_client()
        if not ok:
            return False, err, None
        if need_user:
            uid, err = await self._get_user_id()
            if not uid:
                return False, err, None
            return True, "", uid
        return True, "", None

    async def terminate(self):
        if self.client:
            await self.client.close()
            logger.info("[Codecks] 客户端已关闭")

    # ==================== 命令组 ====================

    @filter.command_group("codecks", alias={"ck"})
    def codecks(self):
        """Codecks 项目管理命令组"""
        pass

    # ==================== 帮助 & 系统 ====================

    @codecks.command("help", alias={"帮助"})
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        yield event.plain_result(formatters.format_help())

    @codecks.command("config")
    async def cmd_config(self, event: AstrMessageEvent):
        """查看配置信息"""
        yield event.plain_result(formatters.format_config_info(
            token=self._get_token(),
            subdomain=self._get_subdomain(),
            is_configured=self._is_configured()
        ))

    @codecks.command("debug")
    async def cmd_debug(self, event: AstrMessageEvent):
        """测试 API 连接"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            account = await self.client.get_account_info()
            name = account.get("name", "未知")
            yield event.plain_result(
                f"✅ 连接成功！\n"
                f"  组织: {name}\n"
                f"  子域名: {self._get_subdomain()}"
            )
        except CodecksError as e:
            yield event.plain_result(f"❌ 连接失败: {e}")

    # ==================== 项目 ====================

    @codecks.command("projects", alias={"项目"})
    async def cmd_projects(self, event: AstrMessageEvent):
        """列出所有项目"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            projects = await self.client.get_projects()
            yield event.plain_result(formatters.format_project_list(projects))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取项目失败: {e}")

    # ==================== 卡组 ====================

    @codecks.command("decks", alias={"牌组"})
    async def cmd_decks(self, event: AstrMessageEvent, project_id: str = ""):
        """列出卡组，可选按项目筛选"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            pid = project_id if project_id else None
            decks = await self.client.get_decks(pid)
            yield event.plain_result(formatters.format_deck_list(decks))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取卡组失败: {e}")

    # ==================== 卡片查询 ====================

    @codecks.command("cards", alias={"卡片"})
    async def cmd_cards(self, event: AstrMessageEvent, deck_id: str = "", limit: int = 10):
        """列出卡片，可选按卡组筛选"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            did = deck_id if deck_id else None
            cards = await self.client.get_cards(deck_id=did, limit=limit)
            yield event.plain_result(formatters.format_card_list(cards))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取卡片失败: {e}")

    @codecks.command("card")
    async def cmd_card(self, event: AstrMessageEvent, card_id: str):
        """查看卡片详情"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            card = await self.client.get_card(card_id)
            yield event.plain_result(formatters.format_card_detail(card))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取卡片失败: {e}")

    @codecks.command("search", alias={"搜索"})
    async def cmd_search(self, event: AstrMessageEvent, keyword: str):
        """搜索卡片"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            cards = await self.client.get_cards(search=keyword, limit=20)
            yield event.plain_result(
                formatters.format_card_list(cards, title=f"搜索「{keyword}」结果")
            )
        except CodecksError as e:
            yield event.plain_result(f"❌ 搜索失败: {e}")

    # ==================== 卡片操作 ====================

    @codecks.command("newcard", alias={"新建卡片", "创建卡片"})
    async def cmd_newcard(
        self, event: AstrMessageEvent,
        title: str, deck_id: str = "",
        effort: int = 0, priority: str = "c"
    ):
        """创建新卡片。用法: /ck newcard <标题> [卡组ID] [工作量] [优先级]"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            did = deck_id if deck_id else None
            result = await self.client.create_card(
                title=title, deck_id=did, effort=effort,
                priority=priority, user_id=user_id
            )
            card_id = result.get("id", "未知")
            yield event.plain_result(f"✅ 卡片已创建！\n  标题: {title}\n  ID: {card_id}")
        except CodecksError as e:
            yield event.plain_result(f"❌ 创建卡片失败: {e}")

    @codecks.command("complete", alias={"完成"})
    async def cmd_complete(self, event: AstrMessageEvent, card_id: str):
        """完成卡片"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.complete_card(card_id, user_id)
            yield event.plain_result(f"✅ 卡片 {card_id} 已标记为完成")
        except CodecksError as e:
            yield event.plain_result(f"❌ 完成卡片失败: {e}")

    @codecks.command("reopen", alias={"重开", "重新打开"})
    async def cmd_reopen(self, event: AstrMessageEvent, card_id: str):
        """重新打开卡片"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.reopen_card(card_id, user_id)
            yield event.plain_result(f"✅ 卡片 {card_id} 已重新打开")
        except CodecksError as e:
            yield event.plain_result(f"❌ 重开卡片失败: {e}")

    @codecks.command("update", alias={"更新"})
    async def cmd_update(
        self, event: AstrMessageEvent,
        card_id: str, field: str, value: str
    ):
        """更新卡片字段。支持: title/content/effort/priority/duedate"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return

        field_map = {
            "title": "content",  # Codecks 的 title 实际存在 content 里
            "content": "content",
            "effort": "effort",
            "priority": "priority",
            "duedate": "dueDate",
            "due": "dueDate",
        }
        api_field = field_map.get(field.lower())
        if not api_field:
            yield event.plain_result(
                f"❌ 不支持的字段: {field}\n"
                f"💡 支持: title, content, effort, priority, duedate"
            )
            return

        # 类型转换
        if api_field == "effort":
            try:
                value = int(value)
            except ValueError:
                yield event.plain_result("❌ 工作量必须是整数")
                return

        try:
            await self.client.update_card(card_id, user_id, **{api_field: value})
            yield event.plain_result(f"✅ 卡片 {card_id} 的 {field} 已更新为: {value}")
        except CodecksError as e:
            yield event.plain_result(f"❌ 更新失败: {e}")

    @codecks.command("assign", alias={"分配"})
    async def cmd_assign(self, event: AstrMessageEvent, card_id: str, assignee_id: str):
        """分配卡片给用户"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.update_card(card_id, user_id, assigneeId=assignee_id)
            yield event.plain_result(f"✅ 卡片 {card_id} 已分配给用户 {assignee_id}")
        except CodecksError as e:
            yield event.plain_result(f"❌ 分配失败: {e}")

    @codecks.command("unassign", alias={"取消分配"})
    async def cmd_unassign(self, event: AstrMessageEvent, card_id: str):
        """取消卡片分配"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.update_card(card_id, user_id, assigneeId=None)
            yield event.plain_result(f"✅ 卡片 {card_id} 已取消分配")
        except CodecksError as e:
            yield event.plain_result(f"❌ 取消分配失败: {e}")

    @codecks.command("setmilestone", alias={"设置里程碑"})
    async def cmd_setmilestone(self, event: AstrMessageEvent, card_id: str, milestone_id: str):
        """设置卡片的里程碑"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.update_card(card_id, user_id, milestoneId=milestone_id)
            yield event.plain_result(f"✅ 卡片 {card_id} 已设置里程碑 {milestone_id}")
        except CodecksError as e:
            yield event.plain_result(f"❌ 设置里程碑失败: {e}")

    @codecks.command("clearmilestone", alias={"清除里程碑"})
    async def cmd_clearmilestone(self, event: AstrMessageEvent, card_id: str):
        """清除卡片的里程碑"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.update_card(card_id, user_id, milestoneId=None)
            yield event.plain_result(f"✅ 卡片 {card_id} 已清除里程碑")
        except CodecksError as e:
            yield event.plain_result(f"❌ 清除里程碑失败: {e}")

    @codecks.command("comment", alias={"评论"})
    async def cmd_comment(self, event: AstrMessageEvent, card_id: str, content: str):
        """为卡片添加评论"""
        ok, err, user_id = await self._pre_check(need_user=True)
        if not ok:
            yield event.plain_result(err)
            return
        try:
            await self.client.add_comment(card_id, user_id, content)
            yield event.plain_result(f"✅ 已为卡片 {card_id} 添加评论")
        except CodecksError as e:
            yield event.plain_result(f"❌ 添加评论失败: {e}")

    # ==================== 里程碑 ====================

    @codecks.command("milestones", alias={"里程碑"})
    async def cmd_milestones(self, event: AstrMessageEvent):
        """列出里程碑"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            milestones = await self.client.get_milestones()
            yield event.plain_result(formatters.format_milestone_list(milestones))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取里程碑失败: {e}")

    # ==================== 用户 ====================

    @codecks.command("users", alias={"用户", "成员"})
    async def cmd_users(self, event: AstrMessageEvent):
        """列出组织成员"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            users = await self.client.get_users()
            yield event.plain_result(formatters.format_user_list(users))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取用户失败: {e}")

    @codecks.command("me")
    async def cmd_me(self, event: AstrMessageEvent):
        """查看当前用户信息"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            user = await self.client.get_current_user()
            yield event.plain_result(formatters.format_current_user(user))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取用户信息失败: {e}")

    @codecks.command("hand", alias={"手牌", "我的任务"})
    async def cmd_hand(self, event: AstrMessageEvent):
        """查看我的待办/手牌"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            cards = await self.client.get_hand_cards()
            yield event.plain_result(
                formatters.format_card_list(cards, title="我的待办")
            )
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取手牌失败: {e}")

    # ==================== 标签 ====================

    @codecks.command("tags", alias={"标签"})
    async def cmd_tags(self, event: AstrMessageEvent, project_id: str = ""):
        """列出标签"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            pid = project_id if project_id else None
            tags = await self.client.get_tags(pid)
            yield event.plain_result(formatters.format_tag_list(tags))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取标签失败: {e}")

    # ==================== 冲刺 ====================

    @codecks.command("sprints", alias={"冲刺"})
    async def cmd_sprints(self, event: AstrMessageEvent, project_id: str = ""):
        """列出冲刺"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            pid = project_id if project_id else None
            sprints = await self.client.get_sprints(pid)
            yield event.plain_result(formatters.format_sprint_list(sprints))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取冲刺失败: {e}")

    # ==================== 统计 ====================

    @codecks.command("stats", alias={"统计"})
    async def cmd_stats(self, event: AstrMessageEvent, project_id: str = ""):
        """查看卡片统计"""
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return
        try:
            pid = project_id if project_id else None
            stats = await self.client.get_card_stats(pid)
            yield event.plain_result(formatters.format_stats(stats))
        except CodecksError as e:
            yield event.plain_result(f"❌ 获取统计失败: {e}")
