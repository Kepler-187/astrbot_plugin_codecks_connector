"""
Codecks 连接器 — AstrBot 插件
通过聊天命令连接、查询和管理 Codecks 项目管理平台
"""

import os
from typing import Optional
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig, logger

from .codecks_client import CodecksClient, CodecksError
from .nlu_handler import NLUHandler
from .scheduler import Scheduler
from . import formatters


class CodecksConnectorPlugin(Star):
    """Codecks 连接器插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.config = config
        self.client: Optional[CodecksClient] = None
        self._auto_user_id: Optional[str] = None
        self._nlu_handler: Optional[NLUHandler] = None
        self._nlu_skill: str = ""
        self._default_decks: str = self.config.get("default_decks", "")
        self._load_nlu_skill()
        # 初始化定时任务调度器（延迟启动，避免 event loop 未就绪）
        self._scheduler: Optional[Scheduler] = None
        self._scheduler_started = False
        if self.config.get("enable_scheduler", True):
            data_dir = os.path.dirname(__file__)
            self._scheduler = Scheduler(
                data_dir=data_dir,
                execute_callback=self._execute_scheduled_query
            )

    def _load_nlu_skill(self):
        """加载 NLU Skill 文档"""
        # 优先使用配置中的自定义 Skill
        override = self.config.get("nlu_skill_override", "")
        if override:
            self._nlu_skill = override
            return
        # 加载默认 Skill 文件
        skill_path = os.path.join(os.path.dirname(__file__), "codecks_nlu_skill.md")
        if os.path.exists(skill_path):
            with open(skill_path, "r", encoding="utf-8") as f:
                self._nlu_skill = f.read()
            logger.info("[Codecks] 已加载 NLU Skill 文档")
        else:
            logger.warning("[Codecks] NLU Skill 文档不存在")

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

    def _ensure_scheduler_started(self):
        """确保调度器后台任务已启动（懒启动）"""
        if self._scheduler and not self._scheduler_started:
            self._scheduler.start()
            self._scheduler_started = True

    async def terminate(self):
        if self._scheduler:
            await self._scheduler.stop()
            logger.info("[Codecks] 定时任务调度器已停止")
        if self.client:
            await self.client.close()
            logger.info("[Codecks] 客户端已关闭")

    # ==================== 命令组 ====================

    @filter.command_group("codecks", alias={"ck"})
    def codecks(self):
        """Codecks 项目管理命令组"""
        pass

    # ==================== 帮助 & 系统 ====================

    @codecks.command("ai", alias={"智能", "问"})
    async def cmd_ai(self, event: AstrMessageEvent, text: str = ""):
        """自然语言命令入口。用法: /ck ai <自然语言指令>"""
        if not self.config.get("enable_nlu", True):
            yield event.plain_result("❌ 自然语言命令未启用")
            return

        if not text.strip():
            yield event.plain_result(
                "🎴 Codecks 自然语言助手\n\n"
                "用法: /ck ai <你的指令>\n\n"
                "示例:\n"
                "  /ck ai 看看最近的BUG\n"
                "  /ck ai 创建一个高优先级BUG 战斗闪退\n"
                "  /ck ai 搜一下存档相关的问题\n"
                "  /ck ai 我手上还有什么任务\n"
                "  /ck ai 统计一下进度"
            )
            return

        # 前置检查
        ok, err, _ = await self._pre_check()
        if not ok:
            yield event.plain_result(err)
            return

        # 确保 NLU Handler 已初始化（传入 provider 用于智能搜索筛选）
        provider = self.context.get_using_provider()
        if self._nlu_handler is None:
            self._nlu_handler = NLUHandler(
                self.client,
                llm_provider=provider,
                default_deck_names=self._default_decks
            )
        else:
            self._nlu_handler.llm_provider = provider

        if not self._nlu_skill:
            yield event.plain_result("❌ NLU Skill 文档未加载，无法解析自然语言")
            return

        # 调用 LLM 解析意图
        if not provider:
            yield event.plain_result("❌ 未配置 LLM Provider，无法使用自然语言命令")
            return

        try:
            resp = await provider.text_chat(
                prompt=text.strip(),
                system_prompt=self._nlu_skill
            )
            if not resp or not resp.completion_text:
                yield event.plain_result("❌ LLM 未返回有效响应")
                return

            # 解析意图
            intent = self._nlu_handler.parse_intent(resp.completion_text)
            if not intent:
                logger.warning(f"[Codecks NLU] 无法解析 LLM 输出: {resp.completion_text[:200]}")
                yield event.plain_result(
                    f"🤔 无法理解你的意图，请试试更具体的表达\n\n"
                    f"💡 示例: 「看看最近的BUG」「创建一个高优先级BUG xxx」"
                )
                return

            logger.info(f"[Codecks NLU] 解析意图: {intent.get('action')} - {intent.get('summary', '')}")

            # 获取用户 ID（用于写操作）
            user_id = None
            uid, _ = await self._get_user_id()
            if uid:
                user_id = uid

            # 执行意图
            result = await self._nlu_handler.execute(intent, user_id)
            yield event.plain_result(result)

        except Exception as e:
            logger.error(f"[Codecks NLU] 处理异常: {e}", exc_info=True)
            yield event.plain_result(f"❌ 处理指令时出错: {e}")

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

    # ==================== 定时任务 ====================

    async def _execute_scheduled_query(self, ai_prompt: str):
        """定时任务回调：执行 AI 查询并发送结果到配置中的目标群"""
        self._ensure_scheduler_started()
        targets = self.config.get("schedule_targets", [])
        if not targets:
            logger.warning("[Codecks Scheduler] 未配置推送目标群 (schedule_targets)，跳过执行")
            return

        # 确保客户端就绪
        ok, err, _ = await self._pre_check()
        if not ok:
            logger.error(f"[Codecks Scheduler] 前置检查失败: {err}")
            return

        # 确保 NLU Handler 就绪
        provider = self.context.get_using_provider()
        if not provider:
            logger.error("[Codecks Scheduler] 未配置 LLM Provider，无法执行定时查询")
            return

        if self._nlu_handler is None:
            self._nlu_handler = NLUHandler(
                self.client,
                llm_provider=provider,
                default_deck_names=self._default_decks
            )
        else:
            self._nlu_handler.llm_provider = provider

        if not self._nlu_skill:
            logger.error("[Codecks Scheduler] NLU Skill 文档未加载")
            return

        try:
            # 调用 LLM 解析意图
            resp = await provider.text_chat(
                prompt=ai_prompt,
                system_prompt=self._nlu_skill
            )
            if not resp or not resp.completion_text:
                logger.error("[Codecks Scheduler] LLM 未返回有效响应")
                return

            intent = self._nlu_handler.parse_intent(resp.completion_text)
            if not intent:
                logger.error(f"[Codecks Scheduler] 无法解析意图: {resp.completion_text[:200]}")
                return

            # 获取用户 ID
            user_id = None
            uid, _ = await self._get_user_id()
            if uid:
                user_id = uid

            # 执行意图获取结果
            result = await self._nlu_handler.execute(intent, user_id)

            # 添加定时任务标识
            from datetime import datetime
            time_str = datetime.now().strftime("%H:%M")
            message = f"⏰ 定时报告 ({time_str})\n🔍 {ai_prompt}\n\n{result}"

            # 发送到所有目标群
            for target in targets:
                target = target.strip()
                if not target:
                    continue

                # 纯数字群号：自动查找可用平台 ID
                if ":" not in target:
                    if target.isdigit():
                        # 尝试从已注册的平台中获取第一个平台 ID
                        auto_platform = None
                        try:
                            platforms = self.context.get_registered_platforms()
                            if platforms:
                                auto_platform = platforms[0].meta.name if hasattr(platforms[0], 'meta') else None
                        except Exception:
                            pass
                        if not auto_platform:
                            logger.warning(f"[Codecks Scheduler] 纯数字群号 {target}，但无法确定平台名。请使用 平台名:群号 格式")
                            continue
                        target = f"{auto_platform}:{target}"
                    else:
                        logger.warning(f"[Codecks Scheduler] 无效的目标群格式: {target}")
                        continue

                parts = target.split(":", 1)
                platform_id = parts[0]
                group_id = parts[1]
                umo = f"{platform_id}:GroupMessage:{group_id}"

                try:
                    await self.context.send_message(umo, MessageChain().message(message))
                    logger.info(f"[Codecks Scheduler] 已发送到 {umo}")
                except Exception as e:
                    logger.error(f"[Codecks Scheduler] 发送到 {umo} 失败: {e}")

        except Exception as e:
            logger.error(f"[Codecks Scheduler] 执行查询异常: {e}", exc_info=True)

    @codecks.command("schedule", alias={"定时"})
    async def cmd_schedule(self, event: AstrMessageEvent, text: str = ""):
        """定时任务管理。用法: /ck schedule <add|list|remove|test> [参数]"""
        self._ensure_scheduler_started()
        if not self._scheduler:
            yield event.plain_result("❌ 定时任务功能未启用，请在配置中开启 enable_scheduler")
            return

        # 从原始消息中提取 schedule 之后的完整文本（绕过 AstrBot 参数拆分）
        import re
        raw_msg = event.message_str.strip()
        m = re.search(r'(?:schedule|定时)\s*(.*)', raw_msg, re.IGNORECASE)
        full_text = m.group(1).strip() if m else text.strip()

        # 提取 action（第一个词）
        parts = full_text.split(None, 1)
        action = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if action in ("list", "ls", "列表", ""):
            yield event.plain_result(self._scheduler.list_tasks())
            return

        if action in ("add", "添加", "新增"):
            if not rest:
                yield event.plain_result(
                    "📋 添加定时任务\n\n"
                    "用法: /ck schedule add <时间> <查询>\n\n"
                    "示例:\n"
                    "  /ck schedule add 每天16:30 今天完成了哪些BUG\n"
                    "  /ck schedule add 每天9点 看看最近的进度\n"
                    "  /ck schedule add 每周一10:00 本周统计"
                )
                return

            time_expr, ai_prompt = self._parse_schedule_args(rest)
            if not time_expr or not ai_prompt:
                yield event.plain_result(
                    f"❌ 无法解析参数，请使用格式:\n"
                    f"  /ck schedule add <时间> <查询>\n\n"
                    f"例如: /ck schedule add 每天16:30 今天完成了哪些BUG"
                )
                return

            ok, msg = self._scheduler.add_task(time_expr, ai_prompt)
            targets = self.config.get("schedule_targets", [])
            if ok and not targets:
                msg += "\n\n⚠️ 注意：尚未配置推送目标群！请在 WebUI 配置 schedule_targets。"
            yield event.plain_result(msg)
            return

        if action in ("remove", "rm", "del", "delete", "删除"):
            task_id = rest.strip()
            if not task_id:
                yield event.plain_result("❌ 请指定任务编号，例如: /ck schedule remove 1")
                return
            ok, msg = self._scheduler.remove_task(task_id)
            yield event.plain_result(msg)
            return

        if action in ("test", "测试", "run", "执行"):
            task_id = rest.strip()
            if not task_id:
                yield event.plain_result("❌ 请指定任务编号，例如: /ck schedule test 1")
                return
            yield event.plain_result(f"⏳ 正在执行任务 #{task_id}...")
            ok, msg = await self._scheduler.execute_now(task_id)
            yield event.plain_result(msg)
            return

        yield event.plain_result(
            "📋 定时任务管理\n\n"
            "用法:\n"
            "  /ck schedule add <时间> <查询>  — 添加定时任务\n"
            "  /ck schedule list             — 查看所有任务\n"
            "  /ck schedule remove <编号>     — 删除任务\n"
            "  /ck schedule test <编号>       — 立即测试执行\n\n"
            "时间格式示例: 每天16:30、每天8点、每周一10:00、每30分钟"
        )

    @staticmethod
    def _parse_schedule_args(raw: str) -> tuple:
        """
        解析 schedule add 的参数，分割时间表达式和 AI 查询。
        例如: '每天16:30 今天完成了哪些BUG' → ('每天16:30', '今天完成了哪些BUG')
        """
        import re
        # 尝试匹配常见的中文时间模式
        patterns = [
            r'^(每天\s*\d{1,2}[:\uff1a点]\d{0,2}分?)\s+(.+)$',
            r'^(每天\s*\d{1,2}点)\s+(.+)$',
            r'^(每周[\u4e00-\u9fff]\s*\d{1,2}[:\uff1a点]\d{1,2}分?)\s+(.+)$',
            r'^(每小时)\s+(.+)$',
            r'^(每\d+小时)\s+(.+)$',
            r'^(每\d+分钟)\s+(.+)$',
            # cron 表达式 (5段)
            r'^([\d\*\/\-\,]+(?:\s+[\d\*\/\-\,]+){4})\s+(.+)$',
        ]
        for pattern in patterns:
            m = re.match(pattern, raw)
            if m:
                return m.group(1).strip(), m.group(2).strip()
        return None, None
