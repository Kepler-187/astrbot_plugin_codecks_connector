"""
Codecks 数据格式化器
将 API 返回的字典/列表转换为用户友好的聊天文本
"""


# ==================== 状态/优先级映射 ====================

STATUS_MAP = {
    "created": "📋 待办",
    "started": "🔨 进行中",
    "done": "✅ 已完成",
}

PRIORITY_MAP = {
    "a": "🔴 最高",
    "b": "🟠 高",
    "c": "🟡 中",
    "d": "🟢 低",
    0: "🟡 中",
    1: "🔴 最高",
    2: "🟠 高",
    3: "🟡 中",
    4: "🟢 低",
}


def _status(s) -> str:
    if isinstance(s, str):
        return STATUS_MAP.get(s, s)
    return str(s)


def _priority(p) -> str:
    return PRIORITY_MAP.get(p, str(p) if p else "🟡 中")


def _truncate(text: str, length: int = 80) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text[:length] + "…" if len(text) > length else text


def _format_date(date_val) -> str:
    if not date_val:
        return ""
    if isinstance(date_val, str):
        return date_val[:10]
    return str(date_val)


def _get_display_name(item: dict) -> str:
    """从 item 中获取显示名称"""
    return item.get("title") or item.get("name") or item.get("content", "")


def _get_id(item: dict) -> str:
    """获取 ID 用于显示"""
    return str(item.get("id", "?"))


# ==================== 卡片格式化 ====================

def format_card_detail(card: dict) -> str:
    """格式化单个卡片详情"""
    if not card:
        return "❌ 未找到卡片"

    lines = [f"🃏 卡片详情"]
    lines.append(f"━━━━━━━━━━━━━━━━")

    title = _get_display_name(card)
    if title:
        lines.append(f"📌 标题: {title}")

    card_id = _get_id(card)
    lines.append(f"🆔 ID: {card_id}")

    seq = card.get("accountSeq")
    if seq:
        lines.append(f"#️⃣ 序号: #{seq}")

    friendly_id = card.get("uniqueFriendlyId")
    if friendly_id:
        lines.append(f"🔗 友好ID: {friendly_id}")

    lines.append(f"📊 状态: {_status(card.get('status'))}")
    lines.append(f"⚡ 优先级: {_priority(card.get('priority'))}")

    effort = card.get("effort")
    if effort:
        lines.append(f"💪 工作量: {effort}")

    due_date = card.get("dueDate")
    if due_date:
        lines.append(f"📅 截止日期: {_format_date(due_date)}")

    created_at = card.get("createdAt")
    if created_at:
        lines.append(f"🕐 创建时间: {_format_date(created_at)}")

    updated_at = card.get("lastUpdatedAt")
    if updated_at:
        lines.append(f"🔄 更新时间: {_format_date(updated_at)}")

    tags = card.get("masterTags") or card.get("tags")
    if tags and isinstance(tags, list) and len(tags) > 0:
        lines.append(f"🏷️ 标签: {', '.join(str(t) for t in tags)}")

    content = card.get("content", "")
    if content:
        # 标题通常是 content 的第一行
        content_lines = content.strip().split("\n")
        body = "\n".join(content_lines[1:]).strip() if len(content_lines) > 1 else ""
        if body:
            lines.append(f"📝 内容: {_truncate(body, 200)}")

    checkbox = card.get("checkboxStats")
    if checkbox and isinstance(checkbox, dict):
        total = checkbox.get("total", 0)
        checked = checkbox.get("checked", 0)
        if total > 0:
            lines.append(f"☑️ 清单: {checked}/{total}")

    return "\n".join(lines)


def format_card_list(cards: list, title: str = "卡片列表") -> str:
    """格式化卡片列表"""
    if not cards:
        return f"📭 {title}: 没有找到卡片"

    lines = [f"🃏 {title} ({len(cards)} 张)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for card in cards:
        card_title = _get_display_name(card)
        status = _status(card.get("status"))
        card_id = _get_id(card)
        seq = card.get("accountSeq", "")
        seq_str = f"#{seq} " if seq else ""

        effort = card.get("effort")
        effort_str = f" 💪{effort}" if effort else ""

        due = card.get("dueDate")
        due_str = f" 📅{_format_date(due)}" if due else ""

        lines.append(
            f"  {seq_str}{_truncate(card_title, 40)} "
            f"[{status}]{effort_str}{due_str}\n"
            f"    ID: {card_id}"
        )

    return "\n".join(lines)


# ==================== 项目格式化 ====================

def format_project_list(projects: list) -> str:
    """格式化项目列表"""
    if not projects:
        return "📭 没有找到项目"

    lines = [f"📂 项目列表 ({len(projects)} 个)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for p in projects:
        name = p.get("name", "未命名")
        pid = _get_id(p)
        seq = p.get("accountSeq", "")
        seq_str = f"#{seq} " if seq else ""
        vis = "🌐" if p.get("isPublic") else "🔒"
        lines.append(f"  {seq_str}{vis} {name}  (ID: {pid})")

    return "\n".join(lines)


# ==================== 卡组格式化 ====================

def format_deck_list(decks: list) -> str:
    """格式化卡组列表"""
    if not decks:
        return "📭 没有找到卡组"

    lines = [f"📦 卡组列表 ({len(decks)} 个)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for d in decks:
        name = d.get("name") or d.get("title") or "未命名"
        did = _get_id(d)
        archived = " [已归档]" if d.get("archived") else ""
        color = d.get("color", "")
        color_str = f" 🎨{color}" if color else ""
        lines.append(f"  📦 {name}{archived}{color_str}  (ID: {did})")

    return "\n".join(lines)


# ==================== 里程碑格式化 ====================

def format_milestone_list(milestones: list) -> str:
    """格式化里程碑列表"""
    if not milestones:
        return "📭 没有找到里程碑"

    lines = [f"🏁 里程碑列表 ({len(milestones)} 个)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for m in milestones:
        name = m.get("name", "未命名")
        mid = _get_id(m)
        date = _format_date(m.get("date"))
        date_str = f" 📅{date}" if date else ""
        start = _format_date(m.get("startDate"))
        start_str = f" (起始: {start})" if start else ""
        global_str = " 🌏全局" if m.get("isGlobal") else ""
        lines.append(f"  🏁 {name}{date_str}{start_str}{global_str}  (ID: {mid})")

    return "\n".join(lines)


# ==================== 用户格式化 ====================

def format_user_list(users: list) -> str:
    """格式化用户列表"""
    if not users:
        return "📭 没有找到用户"

    lines = [f"👥 组织成员 ({len(users)} 人)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for u in users:
        name = u.get("name") or u.get("nickname") or "未知"
        uid = _get_id(u)
        full = ""
        first = u.get("firstName", "")
        last = u.get("lastName", "")
        if first or last:
            full = f" ({first} {last})".strip()
        lines.append(f"  👤 {name}{full}  (ID: {uid})")

    return "\n".join(lines)


def format_current_user(user: dict) -> str:
    """格式化当前用户信息"""
    if not user:
        return "❌ 无法获取用户信息"

    lines = ["👤 当前用户信息"]
    lines.append("━━━━━━━━━━━━━━━━")

    name = user.get("name") or user.get("nickname") or "未知"
    lines.append(f"  昵称: {name}")

    uid = _get_id(user)
    lines.append(f"  ID: {uid}")

    first = user.get("firstName", "")
    last = user.get("lastName", "")
    if first or last:
        lines.append(f"  姓名: {first} {last}")

    email = user.get("email")
    if email:
        lines.append(f"  邮箱: {email}")

    tz = user.get("timezone")
    if tz:
        lines.append(f"  时区: {tz}")

    return "\n".join(lines)


# ==================== 标签格式化 ====================

def format_tag_list(tags: list) -> str:
    """格式化标签列表"""
    if not tags:
        return "📭 没有找到标签"

    lines = [f"🏷️ 标签列表 ({len(tags)} 个)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for t in tags:
        name = t.get("name", "未命名")
        tid = _get_id(t)
        color = t.get("color", "")
        color_str = f" 🎨{color}" if color else ""
        lines.append(f"  🏷️ {name}{color_str}  (ID: {tid})")

    return "\n".join(lines)


# ==================== 冲刺格式化 ====================

def format_sprint_list(sprints: list) -> str:
    """格式化冲刺列表"""
    if not sprints:
        return "📭 没有找到冲刺"

    lines = [f"🏃 冲刺列表 ({len(sprints)} 个)"]
    lines.append("━━━━━━━━━━━━━━━━")

    for s in sprints:
        name = s.get("name", "未命名")
        sid = _get_id(s)
        created = _format_date(s.get("createdAt"))
        created_str = f" 🕐{created}" if created else ""
        lines.append(f"  🏃 {name}{created_str}  (ID: {sid})")

    return "\n".join(lines)


# ==================== 统计格式化 ====================

def format_stats(stats: dict) -> str:
    """格式化卡片统计"""
    if not stats:
        return "❌ 无法获取统计信息"

    total = stats.get("total", 0)
    done = stats.get("done", 0)
    started = stats.get("started", 0)
    created = stats.get("created", 0)
    total_effort = stats.get("totalEffort", 0)
    done_effort = stats.get("doneEffort", 0)
    started_effort = stats.get("startedEffort", 0)

    # 计算完成率
    pct = f"{done / total * 100:.1f}%" if total > 0 else "0%"

    lines = ["📊 卡片统计"]
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(f"  📋 总计: {total} 张")
    lines.append(f"  ✅ 已完成: {done} ({pct})")
    lines.append(f"  🔨 进行中: {started}")
    lines.append(f"  📋 待办: {created}")
    lines.append("")
    lines.append(f"  💪 总工作量: {total_effort}")
    lines.append(f"  ✅ 已完成工作量: {done_effort}")
    lines.append(f"  🔨 进行中工作量: {started_effort}")

    return "\n".join(lines)


# ==================== 帮助信息 ====================

def format_help() -> str:
    """格式化帮助信息"""
    return """🎴 Codecks 连接器 — 帮助
━━━━━━━━━━━━━━━━
📂 查询命令:
  /ck projects (项目)     — 列出所有项目
  /ck decks (牌组) [项目ID] — 列出卡组
  /ck cards (卡片) [卡组ID] [数量] — 列出卡片
  /ck card <ID>          — 查看卡片详情
  /ck search (搜索) <关键词> — 搜索卡片
  /ck milestones (里程碑)  — 列出里程碑
  /ck tags (标签) [项目ID] — 列出标签
  /ck sprints (冲刺) [项目ID] — 列出冲刺
  /ck users (用户)        — 列出组织成员
  /ck me                 — 当前用户信息
  /ck hand (手牌/我的任务)  — 我的待办
  /ck stats (统计) [项目ID] — 卡片统计

✏️ 操作命令:
  /ck newcard (新建卡片) <标题> [卡组ID] [工作量] [优先级]
  /ck complete (完成) <卡片ID>
  /ck reopen (重开) <卡片ID>
  /ck update (更新) <卡片ID> <字段> <值>
  /ck assign (分配) <卡片ID> <用户ID>
  /ck unassign (取消分配) <卡片ID>
  /ck comment (评论) <卡片ID> <内容>
  /ck setmilestone (设置里程碑) <卡片ID> <里程碑ID>
  /ck clearmilestone (清除里程碑) <卡片ID>

⚙️ 系统命令:
  /ck config  — 查看配置
  /ck debug   — 测试连接
  /ck help    — 显示帮助

💡 提示: 优先级 a=最高 b=高 c=中(默认) d=低
💡 更新字段: title/content/effort/priority/duedate"""


# ==================== 配置信息 ====================

def format_config_info(
    token: str, subdomain: str, is_configured: bool
) -> str:
    """格式化配置信息"""
    token_display = f"{token[:6]}...{token[-4:]}" if token and len(token) > 10 else ("已设置" if token else "❌ 未设置")

    lines = ["⚙️ Codecks 配置"]
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(f"  Token: {token_display}")
    lines.append(f"  子域名: {subdomain or '❌ 未设置'}")
    lines.append(f"  状态: {'✅ 已配置' if is_configured else '❌ 未完成配置'}")

    if not is_configured:
        lines.append("\n💡 请在 AstrBot WebUI → 插件管理中配置 Token 和子域名")

    return "\n".join(lines)
