"""
Codecks NLU Handler
自然语言意图解析和命令路由

将 LLM 解析出的 JSON 意图路由到对应的 CodecksClient 方法
"""

import json
import re
from typing import Awaitable, Callable, Optional

from . import formatters
from .codecks_client import CodecksClient, CodecksError


class NLUHandler:
    """自然语言意图处理器"""

    def __init__(
        self,
        client: CodecksClient,
        llm_provider=None,
        default_deck_names: str = "",
        card_created_callback: Optional[Callable[[dict, str], Awaitable[None]]] = None
    ):
        self.client = client
        self.llm_provider = llm_provider
        self.card_created_callback = card_created_callback
        # 解析逗号分隔的 deck 名称列表
        self._default_deck_names = [
            n.strip() for n in default_deck_names.split(",") if n.strip()
        ] if default_deck_names else []
        self._default_deck_ids: Optional[list] = None
        self._deck_resolved = False

    async def _resolve_deck_ids(self) -> list:
        """按名称查找所有配置的 deck ID（只查一次并缓存）"""
        if self._deck_resolved:
            return self._default_deck_ids or []
        self._deck_resolved = True
        if not self._default_deck_names:
            return []
        try:
            decks = await self.client.get_decks()
            ids = []
            for deck in decks:
                name = deck.get("title") or deck.get("name") or ""
                if name in self._default_deck_names:
                    did = deck.get("id")
                    if did:
                        ids.append(did)
            self._default_deck_ids = ids if ids else None
            return ids
        except Exception:
            return []

    async def _get_cards_from_decks(self, limit: int = 500, include_archived: bool = False, **kwargs) -> list:
        """从配置的 deck 中获取卡片，支持多 deck 合并，默认排除归档卡"""
        deck_ids = await self._resolve_deck_ids()
        if not deck_ids:
            # 未配置 deck，查所有
            cards = await self.client.get_cards(limit=limit, **kwargs)
            if not include_archived:
                cards = [c for c in cards if not str(c.get("derivedStatus", "")).startswith("archived")]
            return cards

        # 多 deck 合并（用 accountSeq 去重）
        seen_seqs = set()
        all_cards = []
        for did in deck_ids:
            try:
                cards = await self.client.get_cards(deck_id=did, limit=limit, **kwargs)
            except Exception:
                cards = []
            for c in cards:
                # 跳过归档卡片（除非 include_archived）
                if not include_archived and str(c.get("derivedStatus", "")).startswith("archived"):
                    continue
                seq = c.get("accountSeq")
                if seq is not None:
                    if seq not in seen_seqs:
                        seen_seqs.add(seq)
                        all_cards.append(c)
                else:
                    all_cards.append(c)
        return all_cards

    @staticmethod
    def _sanitize_json(text: str) -> str:
        """清洗 JSON 文本中的特殊字符"""
        # 先将字符串值中的中文引号替换为转义引号，避免破坏 JSON 结构
        # 只替换不在 JSON 键位置的中文引号
        text = text.replace('\u201c', '\\"').replace('\u201d', '\\"')
        text = text.replace('\u2018', "'").replace('\u2019', "'")
        text = text.replace('\uff1a', ':')
        # 替换中文逗号和分号
        text = text.replace('\uff0c', ',')
        return text

    @staticmethod
    def _try_fix_truncated_json(text: str) -> Optional[str]:
        """尝试修复被截断的 JSON"""
        text = text.strip()
        if not text.startswith('{'):
            return None

        # 计算括号平衡
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        # 如果已平衡，直接返回
        if open_braces == 0 and open_brackets == 0:
            return text

        # 尝试在截断处补上引号和括号
        # 先去掉最后一个不完整的键值对
        last_comma = text.rfind(',')
        last_colon = text.rfind(':')
        if last_comma > last_colon  and open_braces > 0:
            text = text[:last_comma]

        # 补全括号
        text += ']' * open_brackets + '}' * open_braces

        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            return None

    def parse_intent(self, llm_response: str) -> Optional[dict]:
        """从 LLM 输出中提取 JSON 意图"""
        if not llm_response:
            return None

        # 方法 1: 从 ```json ``` 代码块提取
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', llm_response, re.DOTALL)
        if json_match:
            raw = self._sanitize_json(json_match.group(1).strip())
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # 尝试修复截断
                fixed = self._try_fix_truncated_json(raw)
                if fixed:
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass

        # 方法 2: 直接提取 {...}
        brace_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
        if brace_match:
            raw = self._sanitize_json(brace_match.group(0))
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

        # 方法 3: 从截断的输出中提取（无闭合 }）
        brace_start = re.search(r'\{.*', llm_response, re.DOTALL)
        if brace_start:
            raw = self._sanitize_json(brace_start.group(0))
            fixed = self._try_fix_truncated_json(raw)
            if fixed:
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass

        return None

    # ==================== 智能搜索 ====================

    async def _smart_search(self, params: dict) -> str:
        """
        LLM 全量筛选搜索：
        1. 获取全量卡片标题列表
        2. 用 LLM 从标题中筛选出与用户描述相关的卡片
        3. 无 LLM 时降级为多关键词 API 搜索
        """
        include_archived = params.get("include_archived", False)
        keywords = params.get("keywords", [])
        original_query = params.get("original_query", "")

        # 兼容旧格式（单个 keyword）
        if not keywords:
            kw = params.get("keyword", "")
            if kw:
                keywords = [kw]

        search_desc = original_query or "、".join(keywords) if keywords else "未知"

        # === 方案 A：LLM 全量筛选（优先） ===
        if self.llm_provider and original_query:
            result = await self._llm_full_search(original_query, include_archived=include_archived)
            if result is not None:
                if not result:
                    return f"📭 搜索「{search_desc}」：没有找到相关卡片"
                return formatters.format_card_list(
                    result,
                    title=f"搜索「{search_desc}」结果"
                )

        # === 方案 B：降级为多关键词 API 搜索 ===
        if not keywords:
            return "❌ 缺少搜索关键词"

        all_cards = await self._multi_keyword_search(keywords)

        # 自动重试（更短关键词）
        if not all_cards:
            shorter_keywords = list(set(kw[:2] for kw in keywords if len(kw) > 2))
            if shorter_keywords:
                all_cards = await self._multi_keyword_search(shorter_keywords)
                if all_cards:
                    keywords = shorter_keywords

        if not all_cards:
            return f"📭 搜索「{'、'.join(keywords)}」：没有找到相关卡片"

        return formatters.format_card_list(
            all_cards,
            title=f"搜索「{'、'.join(keywords)}」结果"
        )

    async def _llm_full_search(self, query: str, include_archived: bool = False) -> Optional[list]:
        """
        获取全量卡片标题，用 LLM 筛选出相关卡片。
        返回 None 表示 LLM 调用失败（应降级到关键词搜索）。
        返回空列表 [] 表示 LLM 确认没有相关卡片。
        """
        if not self.llm_provider:
            return None

        try:
            # 获取大量卡片
            all_cards = await self._get_cards_from_decks(limit=500, include_archived=include_archived)
            if not all_cards:
                return []

            # 构建标题列表
            card_summaries = []
            for i, card in enumerate(all_cards):
                title = card.get("title") or card.get("content", "")[:50] or "无标题"
                status = card.get("status", "")
                card_summaries.append(f"{i}: [{status}] {title}")

            prompt = (
                f"你是霓虹深渊2项目的BUG管理助手。\n"
                f"用户想查找: 「{query}」\n\n"
                f"以下是所有卡片列表（序号: [状态] 标题）:\n"
                + "\n".join(card_summaries) +
                f"\n\n请从中找出与用户查找内容相关的卡片。"
                f"考虑语义相关性，不要只匹配字面文字。"
                f"例如「词缀丢失」和「词条重置」描述的可能是同一个问题。\n"
                f"按相关性从高到低排列，只输出序号，用逗号分隔。\n"
                f"如果都不相关就输出 none。"
            )

            resp = await self.llm_provider.text_chat(prompt=prompt)
            if not resp or not resp.completion_text:
                return None

            text = resp.completion_text.strip()
            if text.lower() == "none":
                return []

            indices = []
            for part in re.split(r'[,，\s]+', text):
                part = part.strip()
                if part.isdigit():
                    idx = int(part)
                    if 0 <= idx < len(all_cards):
                        indices.append(idx)

            if indices:
                return [all_cards[i] for i in indices]

            return None  # LLM 输出无法解析，降级
        except Exception:
            return None  # 出错时降级

    async def _multi_keyword_search(self, keywords: list) -> list:
        """用多个关键词搜索并合并去重（降级方案）"""
        seen_ids = set()
        all_cards = []

        for kw in keywords:
            try:
                cards = await self.client.get_cards(search=kw, limit=30)
                for card in cards:
                    card_id = card.get("id", "")
                    if card_id and card_id not in seen_ids:
                        seen_ids.add(card_id)
                        all_cards.append(card)
            except Exception:
                continue

        return all_cards

    # ==================== 执行入口 ====================

    async def execute(self, intent: dict, user_id: str = None) -> str:
        """执行意图"""
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
            card_id = params.get("card_id", "")
            if not card_id:
                return "❌ 缺少卡片 ID"

            # 如果是序号（数字或 #开头），先按 accountSeq 查找
            seq = card_id.lstrip("#").strip()
            if seq.isdigit():
                cards = await self._get_cards_from_decks(limit=500)
                target = None
                for c in cards:
                    if str(c.get("accountSeq")) == seq:
                        target = c
                        break
                if target:
                    return formatters.format_card_detail(target)
                return f"📭 未找到序号 #{seq} 的卡片"

            card = await self.client.get_card(card_id)
            return formatters.format_card_detail(card)

        elif action == "search_cards":
            return await self._smart_search(params)

        elif action == "filter_cards":
            status = params.get("status")
            priority = params.get("priority")
            assignee_id = params.get("assignee_id")
            days = params.get("days")
            date_from = params.get("date_from")
            date_to = params.get("date_to")
            include_archived = params.get("include_archived", False)

            # 全部在代码层过滤，避免 API 500 错误
            cards = await self._get_cards_from_decks(limit=500, include_archived=include_archived)

            # 按条件筛选
            if status:
                cards = [c for c in cards if c.get("status") == status]
            if priority:
                cards = [c for c in cards if c.get("priority") == priority]
            if assignee_id:
                cards = [c for c in cards if c.get("assigneeId") == assignee_id]

            from datetime import datetime, timedelta, timezone

            # 按绝对日期范围筛选（date_from / date_to，ISO 格式）
            if date_from or date_to:
                try:
                    dt_from = datetime.fromisoformat(date_from.replace("Z", "+00:00")) if date_from else None
                    dt_to = datetime.fromisoformat(date_to.replace("Z", "+00:00")) if date_to else None
                    # 如果日期没带时区信息，视为 UTC
                    if dt_from and dt_from.tzinfo is None:
                        dt_from = dt_from.replace(tzinfo=timezone.utc)
                    if dt_to and dt_to.tzinfo is None:
                        dt_to = dt_to.replace(tzinfo=timezone.utc)
                    filtered = []
                    for c in cards:
                        date_str = c.get("lastUpdatedAt") or c.get("createdAt") or ""
                        if date_str:
                            try:
                                card_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                                if dt_from and card_date < dt_from:
                                    continue
                                if dt_to and card_date > dt_to:
                                    continue
                                filtered.append(c)
                            except (ValueError, TypeError):
                                pass
                    cards = filtered
                except (ValueError, TypeError):
                    pass
            # 按相对时间范围筛选（严格最近 N×24小时，与 Codecks 一致）
            elif days:
                try:
                    days_int = int(days)
                    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=days_int * 24)
                    filtered = []
                    for c in cards:
                        date_str = c.get("lastUpdatedAt") or c.get("createdAt") or ""
                        if date_str:
                            try:
                                card_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                                if card_date >= cutoff_utc:
                                    filtered.append(c)
                            except (ValueError, TypeError):
                                pass
                    cards = filtered
                except (ValueError, TypeError):
                    pass

            # 按 limit 截断
            limit = params.get("limit", 20)
            if isinstance(limit, int) and len(cards) > limit:
                cards = cards[:limit]

            # 构建标题描述
            desc_parts = []
            priority_names = {"a": "最高", "b": "高", "c": "普通", "d": "低"}
            status_names = {"not_started": "未完成", "created": "未完成", "started": "进行中", "done": "已完成"}
            if date_from and date_to:
                desc_parts.append(f"{date_from}~{date_to}")
            elif date_from:
                desc_parts.append(f"{date_from}起")
            elif date_to:
                desc_parts.append(f"截至{date_to}")
            elif days:
                desc_parts.append(f"最近{days}天")
            if priority:
                desc_parts.append(f"{priority_names.get(priority, priority)}优先级")
            if status:
                desc_parts.append(status_names.get(status, status))
            if include_archived:
                desc_parts.append("含归档")
            title = "、".join(desc_parts) + "卡片" if desc_parts else "筛选结果"
            return formatters.format_card_list(cards, title=title)

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
            if self.card_created_callback:
                await self.card_created_callback(result, title)
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
                "title": "content", "content": "content",
                "effort": "effort", "priority": "priority",
                "duedate": "dueDate", "due": "dueDate",
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
