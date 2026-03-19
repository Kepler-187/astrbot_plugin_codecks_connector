"""
Codecks 定时任务调度器
支持定时执行 AI 查询并将结果推送到指定群聊
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger


def _match_cron_field(field: str, value: int, max_val: int) -> bool:
    """检查单个 cron 字段是否匹配给定值"""
    if field == '*':
        return True

    # */N 格式
    m = re.match(r'^\*/(\d+)$', field)
    if m:
        step = int(m.group(1))
        return step > 0 and value % step == 0

    # 纯数字
    if field.isdigit():
        return int(field) == value

    # 逗号分隔的多值
    if ',' in field:
        return value in [int(v) for v in field.split(',') if v.isdigit()]

    # 范围 N-M
    m = re.match(r'^(\d+)-(\d+)$', field)
    if m:
        return int(m.group(1)) <= value <= int(m.group(2))

    return False


def _cron_dow_match(field: str, dt: datetime) -> bool:
    """专门处理星期几匹配（Python weekday 转 cron dow）"""
    # Python: Mon=0, Tue=1 ... Sun=6
    # Cron:   Sun=0, Mon=1 ... Sat=6
    py_wd = dt.weekday()
    cron_wd = (py_wd + 1) % 7  # 转换
    return _match_cron_field(field, cron_wd, 6)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """检查给定时间是否匹配 cron 表达式（分 时 日 月 周）"""
    parts = cron_expr.split()
    if len(parts) != 5:
        return False

    mi, h, dom, mon, dow = parts
    return (
        _match_cron_field(mi, dt.minute, 59) and
        _match_cron_field(h, dt.hour, 23) and
        _match_cron_field(dom, dt.day, 31) and
        _match_cron_field(mon, dt.month, 12) and
        _cron_dow_match(dow, dt)
    )


def parse_chinese_time(text: str) -> Optional[str]:
    """
    将自然中文时间表达式解析为 cron 表达式。

    支持格式:
      每天HH:MM / 每天HH点MM分
      每周X HH:MM
      每小时 / 每N小时
      每N分钟
      cron 表达式（直接返回）
    """
    text = text.strip()

    # 已经是 cron 表达式（5 段空格分隔的数字/星号）
    if re.match(r'^[\d\*\/\-\,]+(\s+[\d\*\/\-\,]+){4}$', text):
        return text

    # 每天HH:MM 或 每天HH点MM分
    m = re.match(r'每天\s*(\d{1,2})[:\uff1a点](\d{1,2})分?$', text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{mi} {h} * * *"

    # 每天HH点（整点）
    m = re.match(r'每天\s*(\d{1,2})点$', text)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"0 {h} * * *"

    # 每周X HH:MM
    weekday_map = {
        '一': '1', '二': '2', '三': '3', '四': '4',
        '五': '5', '六': '6', '日': '0', '天': '0',
    }
    m = re.match(r'每周([\u4e00-\u9fff])\s*(\d{1,2})[:\uff1a点](\d{1,2})分?$', text)
    if m:
        wd = weekday_map.get(m.group(1))
        if wd:
            h, mi = int(m.group(2)), int(m.group(3))
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return f"{mi} {h} * * {wd}"

    # 每小时
    if text == '每小时':
        return "0 * * * *"

    # 每N小时
    m = re.match(r'每(\d+)小时$', text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 23:
            return f"0 */{n} * * *"

    # 每N分钟
    m = re.match(r'每(\d+)分钟$', text)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 59:
            return f"*/{n} * * * *"

    return None


def cron_to_chinese(cron_expr: str) -> str:
    """将 cron 表达式转为人类可读的中文描述"""
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr

    mi, h, dom, mon, dow = parts

    weekday_names = {'0': '日', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六'}

    # 每N分钟
    m = re.match(r'^\*/(\d+)$', mi)
    if m and h == '*' and dom == '*' and mon == '*' and dow == '*':
        return f"每{m.group(1)}分钟"

    # 每N小时
    m = re.match(r'^\*/(\d+)$', h)
    if m and mi == '0' and dom == '*' and mon == '*' and dow == '*':
        return f"每{m.group(1)}小时"

    # 每小时
    if mi == '0' and h == '*' and dom == '*' and mon == '*' and dow == '*':
        return "每小时"

    # 每天 HH:MM
    if mi.isdigit() and h.isdigit() and dom == '*' and mon == '*' and dow == '*':
        return f"每天{h.zfill(2)}:{mi.zfill(2)}"

    # 每周X HH:MM
    if mi.isdigit() and h.isdigit() and dom == '*' and mon == '*' and dow in weekday_names:
        return f"每周{weekday_names[dow]} {h.zfill(2)}:{mi.zfill(2)}"

    return cron_expr


class ScheduleTask:
    """单个定时任务"""

    def __init__(self, task_id: str, ai_prompt: str, cron_expr: str,
                 enabled: bool = True, created_at: str = None,
                 last_run: str = None):
        self.id = task_id
        self.ai_prompt = ai_prompt
        self.cron_expr = cron_expr
        self.enabled = enabled
        self.created_at = created_at or datetime.now().isoformat()
        self.last_run = last_run

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ai_prompt": self.ai_prompt,
            "cron_expr": self.cron_expr,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run": self.last_run,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ScheduleTask':
        return cls(
            task_id=data["id"],
            ai_prompt=data["ai_prompt"],
            cron_expr=data["cron_expr"],
            enabled=data.get("enabled", True),
            created_at=data.get("created_at"),
            last_run=data.get("last_run"),
        )

    def is_due(self, now: datetime) -> bool:
        """检查任务是否到期需要执行"""
        if not self.enabled:
            return False

        # 使用内置 cron 匹配
        if not cron_matches(self.cron_expr, now):
            return False

        # 避免重复执行（同一分钟内不重复）
        if self.last_run:
            try:
                last = datetime.fromisoformat(self.last_run)
                if (now - last).total_seconds() < 60:
                    return False
            except (ValueError, TypeError):
                pass

        return True


class Scheduler:
    """定时任务调度器"""

    def __init__(self, data_dir: str, execute_callback=None):
        self._data_dir = data_dir
        self._data_file = os.path.join(data_dir, "schedules.json")
        self._tasks: list[ScheduleTask] = []
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._execute_callback = execute_callback
        self._load()

    def _load(self):
        """从 JSON 文件加载任务"""
        if os.path.exists(self._data_file):
            try:
                with open(self._data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._tasks = [ScheduleTask.from_dict(d) for d in data]
                logger.info(f"[Codecks Scheduler] 已加载 {len(self._tasks)} 个定时任务")
            except Exception as e:
                logger.error(f"[Codecks Scheduler] 加载定时任务失败: {e}")
                self._tasks = []
        else:
            self._tasks = []

    def _save(self):
        """保存任务到 JSON 文件"""
        try:
            os.makedirs(self._data_dir, exist_ok=True)
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump([t.to_dict() for t in self._tasks], f,
                          ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Codecks Scheduler] 保存定时任务失败: {e}")

    def _next_id(self) -> str:
        """生成简短的自增 ID"""
        if not self._tasks:
            return "1"
        max_id = max(int(t.id) for t in self._tasks if t.id.isdigit()) if self._tasks else 0
        return str(max_id + 1)

    def add_task(self, time_expr: str, ai_prompt: str) -> tuple[bool, str]:
        """
        添加定时任务。
        返回 (成功, 消息)
        """
        cron_expr = parse_chinese_time(time_expr)
        if not cron_expr:
            return False, (
                f"❌ 无法识别时间格式「{time_expr}」\n\n"
                "💡 支持的格式:\n"
                "  • 每天16:30\n"
                "  • 每天8点\n"
                "  • 每天9点30分\n"
                "  • 每周一 10:00\n"
                "  • 每小时\n"
                "  • 每30分钟"
            )

        task = ScheduleTask(
            task_id=self._next_id(),
            ai_prompt=ai_prompt,
            cron_expr=cron_expr,
        )
        self._tasks.append(task)
        self._save()

        readable_time = cron_to_chinese(cron_expr)
        return True, (
            f"✅ 定时任务已创建！\n\n"
            f"  🆔 编号: {task.id}\n"
            f"  ⏰ 时间: {readable_time}\n"
            f"  🔍 查询: {ai_prompt}"
        )

    def remove_task(self, task_id: str) -> tuple[bool, str]:
        """删除定时任务"""
        for i, t in enumerate(self._tasks):
            if t.id == task_id:
                self._tasks.pop(i)
                self._save()
                return True, f"✅ 已删除定时任务 #{task_id}"
        return False, f"❌ 未找到编号为 {task_id} 的定时任务"

    def get_task(self, task_id: str) -> Optional[ScheduleTask]:
        """获取指定任务"""
        for t in self._tasks:
            if t.id == task_id:
                return t
        return None

    def list_tasks(self) -> str:
        """列出所有定时任务"""
        if not self._tasks:
            return (
                "📭 暂无定时任务\n\n"
                "💡 使用 /ck schedule add <时间> <查询> 添加\n"
                "   例如: /ck schedule add 每天16:30 今天完成了哪些BUG"
            )

        lines = ["📋 定时任务列表\n"]
        for t in self._tasks:
            status = "✅" if t.enabled else "⏸️"
            readable_time = cron_to_chinese(t.cron_expr)
            last_run = ""
            if t.last_run:
                try:
                    lr = datetime.fromisoformat(t.last_run)
                    last_run = f"  上次执行: {lr.strftime('%m-%d %H:%M')}"
                except (ValueError, TypeError):
                    pass
            lines.append(
                f"{status} #{t.id}  ⏰ {readable_time}\n"
                f"    🔍 {t.ai_prompt}{last_run}"
            )
        return "\n".join(lines)

    def start(self):
        """启动后台调度循环"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("[Codecks Scheduler] 调度器已启动")

    async def stop(self):
        """停止调度器"""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("[Codecks Scheduler] 调度器已停止")

    async def _loop(self):
        """后台调度主循环，每 30 秒检查一次"""
        while self._running:
            try:
                await asyncio.sleep(30)
                now = datetime.now()
                for task in self._tasks:
                    if task.is_due(now):
                        logger.info(f"[Codecks Scheduler] 执行定时任务 #{task.id}: {task.ai_prompt}")
                        task.last_run = now.isoformat()
                        self._save()
                        try:
                            await self._execute_task(task)
                        except Exception as e:
                            logger.error(f"[Codecks Scheduler] 任务 #{task.id} 执行失败: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Codecks Scheduler] 调度循环异常: {e}")
                await asyncio.sleep(10)

    async def _execute_task(self, task: ScheduleTask):
        """执行单个定时任务"""
        if self._execute_callback:
            await self._execute_callback(task.ai_prompt)

    async def execute_now(self, task_id: str) -> tuple[bool, str]:
        """立即执行指定任务（调试用）"""
        task = self.get_task(task_id)
        if not task:
            return False, f"❌ 未找到编号为 {task_id} 的定时任务"

        task.last_run = datetime.now().isoformat()
        self._save()

        if self._execute_callback:
            await self._execute_callback(task.ai_prompt)
            return True, f"✅ 任务 #{task_id} 已手动触发执行"

        return False, "❌ 执行回调未配置"
