"""
Codecks NLU Handler
自然语言意图解析和命令路由

将 LLM 解析出的 JSON 意图路由到对应的 CodecksClient 方法
"""

import json
import re
from typing import Optional

from . import formatters
from .codecks_client import CodecksClient, CodecksError


class NLUHandler:
    """自然语言意图处理器"""

    def __init__(self, client: CodecksClient):
        self.client = client

    def parse_intent(self, llm_response: str) -> Optional[dict]:
        """
        从 LLM 输出中提取 JSON 意图

        支持：
        - 纯 JSON
        - ```json ... ``` 代码块
        - 文本中夹杂的 JSON 块
        """
        if not llm_response:
            return None

        # 尝试提取 ```json ... ``` 代码块
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', llm_response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试提取 {...} 块
        brace_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    async def execute(self, intent: dict, user_id: str = None) -> str:
        """
        执行意图

        Args:
            intent: LLM 解析出的意图字典 {"action": ..., "params": ..., "summary": ...}
            user_id: 当前用户 ID

        Returns:
            格式化后的结果文本
        """
        action = intent.get("action", "unclear")
        params = intent.get("params", {})
        summary = intent.get("summary", "")

        try:
            result = await self._dispatch(action, params, user_id)
            if summary:
                return f"💡 {summary}\n\n{result}"
            return result
        except CodecksError as e:
            return f"❌ 执行失败: {e}"
        except Exception as e:
            return f"❌ 内部错误: {e}"

    async def _dispatch(self, action: str, params: dict, user_id: str = None) -> str:
        """根据 action 路由到对应方法"""

        # ==================== 查询类 ====================

        if action == "list_projects":
            projects = await self.client.get_projects()
            return formatters.format_project_list(projects)

        elif action == "list_decks":
            pid = params.get("project_id")
            decks = await self.client.get_decks(pid)
            return formatters.format_deck_list(decks)

        elif action == "list_cards":
            cards = await self.client.get_cards(
                deck_id=params.get("deck_id"),
                limit=params.get("limit", 10)
            )
            return formatters.format_card_list(cards)

        elif action == "get_card":
            card_id = params.get("card_id")
            if not card_id:
                return "❌ 缺少卡片 ID"
            card = await self.client.get_card(card_id)
            return formatters.format_card_detail(card)

        elif action == "search_cards":
            keyword = params.get("keyword")
            if not keyword:
                return "❌ 缺少搜索关键词"
            cards = await self.client.get_cards(search=keyword, limit=20)
            return formatters.format_card_list(cards, title=f"搜索「{keyword}」结果")

        elif action == "list_milestones":
            milestones = await self.client.get_milestones()
            return formatters.format_milestone_list(milestones)

        elif action == "list_tags":
            pid = params.get("project_id")
            tags = await self.client.get_tags(pid)
            return formatters.format_tag_list(tags)

        elif action == "list_sprints":
            pid = params.get("project_id")
            sprints = await self.client.get_sprints(pid)
            return formatters.format_sprint_list(sprints)

        elif action == "list_users":
            users = await self.client.get_users()
            return formatters.format_user_list(users)

        elif action == "get_me":
            user = await self.client.get_current_user()
            return formatters.format_current_user(user)

        elif action == "get_hand":
            cards = await self.client.get_hand_cards()
            return formatters.format_card_list(cards, title="我的待办")

        elif action == "get_stats":
            pid = params.get("project_id")
            stats = await self.client.get_card_stats(pid)
            return formatters.format_stats(stats)

        # ==================== 操作类 ====================

        elif action == "create_card":
            title = params.get("title")
            if not title:
                return "❌ 缺少卡片标题"
            if not user_id:
                return "❌ 无法获取用户 ID，创建卡片需要用户身份"
            result = await self.client.create_card(
                title=title,
                deck_id=params.get("deck_id"),
                effort=params.get("effort", 0),
                priority=params.get("priority", "c"),
                user_id=user_id
            )
            card_id = result.get("id", "未知")
            priority_display = formatters._priority(params.get("priority", "c"))
            return (
                f"✅ 卡片已创建！\n"
                f"  📌 标题: {title}\n"
                f"  ⚡ 优先级: {priority_display}\n"
                f"  🆔 ID: {card_id}"
            )

        elif action == "complete_card":
            card_id = params.get("card_id")
            if not card_id:
                return "❌ 缺少卡片 ID"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.complete_card(card_id, user_id)
            return f"✅ 卡片 {card_id} 已标记为完成"

        elif action == "reopen_card":
            card_id = params.get("card_id")
            if not card_id:
                return "❌ 缺少卡片 ID"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.reopen_card(card_id, user_id)
            return f"✅ 卡片 {card_id} 已重新打开"

        elif action == "update_card":
            card_id = params.get("card_id")
            field = params.get("field")
            value = params.get("value")
            if not all([card_id, field, value]):
                return "❌ 缺少必要参数（card_id, field, value）"
            if not user_id:
                return "❌ 无法获取用户 ID"

            field_map = {
                "title": "content",
                "content": "content",
                "effort": "effort",
                "priority": "priority",
                "duedate": "dueDate",
                "due": "dueDate",
            }
            api_field = field_map.get(str(field).lower())
            if not api_field:
                return f"❌ 不支持的字段: {field}"

            if api_field == "effort":
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    return "❌ 工作量必须是整数"

            await self.client.update_card(card_id, user_id, **{api_field: value})
            return f"✅ 卡片 {card_id} 的 {field} 已更新为: {value}"

        elif action == "assign_card":
            card_id = params.get("card_id")
            assignee_id = params.get("assignee_id")
            if not card_id or not assignee_id:
                return "❌ 缺少卡片 ID 或用户 ID"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.update_card(card_id, user_id, assigneeId=assignee_id)
            return f"✅ 卡片 {card_id} 已分配给用户 {assignee_id}"

        elif action == "unassign_card":
            card_id = params.get("card_id")
            if not card_id:
                return "❌ 缺少卡片 ID"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.update_card(card_id, user_id, assigneeId=None)
            return f"✅ 卡片 {card_id} 已取消分配"

        elif action == "add_comment":
            card_id = params.get("card_id")
            content = params.get("content")
            if not card_id or not content:
                return "❌ 缺少卡片 ID 或评论内容"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.add_comment(card_id, user_id, content)
            return f"✅ 已为卡片 {card_id} 添加评论"

        elif action == "set_milestone":
            card_id = params.get("card_id")
            milestone_id = params.get("milestone_id")
            if not card_id or not milestone_id:
                return "❌ 缺少卡片 ID 或里程碑 ID"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.update_card(card_id, user_id, milestoneId=milestone_id)
            return f"✅ 卡片 {card_id} 已设置里程碑 {milestone_id}"

        elif action == "clear_milestone":
            card_id = params.get("card_id")
            if not card_id:
                return "❌ 缺少卡片 ID"
            if not user_id:
                return "❌ 无法获取用户 ID"
            await self.client.update_card(card_id, user_id, milestoneId=None)
            return f"✅ 卡片 {card_id} 已清除里程碑"

        # ==================== 特殊 ====================

        elif action == "help":
            return formatters.format_help()

        elif action == "unclear":
            hint = params.get("hint", "")
            return (
                f"🤔 我不太确定你想做什么。\n"
                f"{('💡 ' + hint) if hint else ''}\n\n"
                f"你可以试试：\n"
                f"  • 「看看最近的BUG」\n"
                f"  • 「创建一个高优先级BUG xxx」\n"
                f"  • 「搜一下存档相关的问题」\n"
                f"  • 「我手上还有什么任务」\n"
                f"  • 「统计一下进度」"
            )

        else:
            return f"❌ 未知操作: {action}"
