from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Optional

import dateparser


@dataclass
class ParseTaskResult:
    title: str
    due_date: Optional[date] = None
    due_time: Optional[time] = None
    priority: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    project: Optional[str] = None
    recurrence_rule: Optional[str] = None


_DAY_OFFSETS: dict[str, timedelta] = {
    "今天": timedelta(days=0),
    "明天": timedelta(days=1),
    "后天": timedelta(days=2),
    "大后天": timedelta(days=3),
}

_WEEKDAY_NAMES: dict[str, int] = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

_DAY_PATTERN = re.compile(
    r"(今天|明天|后天|大后天|下周[一二三四五六日天])"
)

_CN_NUMERALS: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "十一": 11, "十二": 12,
    "二十": 20, "二十一": 21, "二十二": 22,
    "二十三": 23, "二十四": 24,
    "二十五": 25, "二十六": 26, "二十七": 27,
    "二十八": 28, "二十九": 29, "三十": 30,
    "三十一": 31, "三十二": 32, "三十三": 33,
    "三十四": 34, "三十五": 35, "三十六": 36,
    "三十七": 37, "三十八": 38, "三十九": 39,
    "四十": 40, "四十五": 45, "五十": 50, "五十五": 55,
    "零": 0,
}

_CN_NUMERAL_HOUR_PATTERN = re.compile(
    r"(十[一二]?|[一两二三四五六七八九]|十一|十二)(?=[点时])"
)

_CN_NUMERAL_MINUTE_PATTERN = re.compile(
    r"(三?十[一二三四五六七八九]?|二十[一二三四五六七八九]?|[一两二三四五六七八九]|零)(?=分)"
)


def _convert_cn_numerals_for_time(text: str) -> str:
    def _replace_hour(m: re.Match) -> str:
        val = _CN_NUMERALS.get(m.group(0))
        return str(val) if val is not None else m.group(0)

    def _replace_minute(m: re.Match) -> str:
        val = _CN_NUMERALS.get(m.group(0))
        return str(val) if val is not None else m.group(0)

    result = _CN_NUMERAL_HOUR_PATTERN.sub(_replace_hour, text)
    result = _CN_NUMERAL_MINUTE_PATTERN.sub(_replace_minute, result)
    return result


_TIME_PREFIX_PATTERN = re.compile(r"(上午|早上|早晨|凌晨|下午|晚上|傍晚|夜里|夜晚)$")

_TIME_PATTERN = re.compile(
    r"(?:"
    r"(上午|早上|早晨|凌晨)?(\d{1,2})[点时:：](\d{1,2})?(分|半)?"
    r"|"
    r"(下午|晚上|傍晚|夜里|夜晚)?(\d{1,2})[点时:：](\d{1,2})?(分|半)?"
    r"|"
    r"(\d{1,2}):(\d{2})"
    r"|"
    r"(\d{1,2})\s*(am|pm|AM|PM)"
    r")"
)

_PRIORITY_PATTERN = re.compile(r"!{1,3}(?=\s|$)")

_TAG_PATTERN = re.compile(r"#(\S+)")

_PROJECT_PATTERN = re.compile(r"@(\S+)")

_ABSOLUTE_DATE_PATTERN = re.compile(
    r"(?:"
    r"(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})[日号]?"
    r"|"
    r"(\d{1,2})[月/\-.](\d{1,2})[日号]?"
    r")"
)

_RECURRENCE_WEEKDAY_MAP: dict[str, int] = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

_RECURRENCE_DAILY_PATTERN = re.compile(r"(每天|每日|daily)")
_RECURRENCE_WEEKLY_PATTERN = re.compile(r"(每星期[一二三四五六日天]|每周[一二三四五六日天])")
_RECURRENCE_MONTHLY_PATTERN = re.compile(r"每月(\d{1,2})[号日]")


def _resolve_weekday(name: str) -> date:
    target = _WEEKDAY_NAMES[name[2]]
    today = date.today()
    current = today.weekday()
    days_ahead = target - current
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _parse_time_hour_minute(prefix: str | None, hour_str: str, minute_str: str | None, half_str: str | None) -> time | None:
    try:
        hour = int(hour_str)
        minute = 0
        if half_str == "半":
            minute = 30
        elif minute_str:
            minute = int(minute_str)
        if prefix in ("下午", "晚上", "傍晚", "夜里", "夜晚"):
            if hour < 12:
                hour += 12
        elif prefix in ("上午", "早上", "早晨", "凌晨"):
            if hour == 12:
                hour = 0
        return time(hour, minute)
    except (ValueError, TypeError):
        return None


def extract_datetime(text: str) -> tuple[Optional[date], Optional[time], str]:
    parsed_date: date | None = None
    parsed_time: time | None = None
    remaining = text

    day_match = _DAY_PATTERN.search(remaining)
    if day_match:
        keyword = day_match.group(1)
        if keyword in _DAY_OFFSETS:
            parsed_date = date.today() + _DAY_OFFSETS[keyword]
        elif keyword.startswith("下周"):
            parsed_date = _resolve_weekday(keyword)
        remaining = remaining[:day_match.start()] + remaining[day_match.end():]

    if parsed_date is None:
        abs_match = _ABSOLUTE_DATE_PATTERN.search(remaining)
        if abs_match:
            try:
                if abs_match.group(1):
                    y, m, d = int(abs_match.group(1)), int(abs_match.group(2)), int(abs_match.group(3))
                else:
                    y = date.today().year
                    m, d = int(abs_match.group(4)), int(abs_match.group(5))
                parsed_date = date(y, m, d)
                remaining = remaining[:abs_match.start()] + remaining[abs_match.end():]
            except (ValueError, TypeError):
                pass

    remaining = _convert_cn_numerals_for_time(remaining)
    time_match = _TIME_PATTERN.search(remaining)
    if time_match:
        t: time | None = None
        if time_match.group(2):
            t = _parse_time_hour_minute(
                time_match.group(1), time_match.group(2), time_match.group(3), time_match.group(4)
            )
        elif time_match.group(6):
            t = _parse_time_hour_minute(
                time_match.group(5), time_match.group(6), time_match.group(7), time_match.group(8)
            )
        elif time_match.group(9) and time_match.group(10):
            try:
                h = int(time_match.group(9))
                m_val = int(time_match.group(10))
                t = time(h, m_val)
            except (ValueError, TypeError):
                pass
        elif time_match.group(11) and time_match.group(12):
            try:
                h = int(time_match.group(11))
                suffix = time_match.group(12).lower()
                if suffix == "pm" and h < 12:
                    h += 12
                elif suffix == "am" and h == 12:
                    h = 0
                t = time(h, 0)
            except (ValueError, TypeError):
                pass

        if t is not None:
            parsed_time = t
            before = remaining[:time_match.start()]
            after = remaining[time_match.end():]
            prefix_match = _TIME_PREFIX_PATTERN.search(before)
            if prefix_match:
                before = before[:prefix_match.start()]
            remaining = before + after

    if parsed_date is None and parsed_time is not None:
        parsed_date = date.today()

    if parsed_date is None and parsed_time is None:
        dp_settings = {
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PARSERS": ["absolute-time", "relative-time"],
        }
        dp_result = dateparser.parse(text, settings=dp_settings, languages=["zh", "en"])
        if dp_result is not None:
            parsed_date = dp_result.date()
            parsed_time = dp_result.time()
            if parsed_time is not None and parsed_time == time(0, 0):
                parsed_time = None
            remaining = text

    remaining = re.sub(r"\s+", " ", remaining).strip()
    return parsed_date, parsed_time, remaining


def extract_priority(text: str) -> tuple[Optional[str], str]:
    match = _PRIORITY_PATTERN.search(text)
    if not match:
        return None, text
    marker = match.group(0)
    count = len(marker)
    mapping = {3: "urgent_important", 2: "not_urgent_important", 1: "urgent_not_important"}
    priority = mapping.get(count, "not_urgent_not_important")
    remaining = text[:match.start()] + text[match.end():]
    remaining = re.sub(r"\s+", " ", remaining).strip()
    return priority, remaining


def extract_tags(text: str) -> tuple[list[str], str]:
    matches = _TAG_PATTERN.findall(text)
    if not matches:
        return [], text
    remaining = _TAG_PATTERN.sub("", text)
    remaining = re.sub(r"\s+", " ", remaining).strip()
    return matches, remaining


def extract_project(text: str) -> tuple[Optional[str], str]:
    match = _PROJECT_PATTERN.search(text)
    if not match:
        return None, text
    project = match.group(1)
    remaining = text[:match.start()] + text[match.end():]
    remaining = re.sub(r"\s+", " ", remaining).strip()
    return project, remaining


def extract_recurrence(text: str) -> tuple[Optional[str], str]:
    remaining = text

    monthly_match = _RECURRENCE_MONTHLY_PATTERN.search(remaining)
    if monthly_match:
        day = int(monthly_match.group(1))
        if 1 <= day <= 31:
            remaining = remaining[:monthly_match.start()] + remaining[monthly_match.end():]
            remaining = re.sub(r"\s+", " ", remaining).strip()
            return f"monthly:{day}", remaining

    weekly_match = _RECURRENCE_WEEKLY_PATTERN.search(remaining)
    if weekly_match:
        phrase = weekly_match.group(1)
        weekday_char = phrase[-1]
        weekday = _RECURRENCE_WEEKDAY_MAP.get(weekday_char)
        if weekday is not None:
            remaining = remaining[:weekly_match.start()] + remaining[weekly_match.end():]
            remaining = re.sub(r"\s+", " ", remaining).strip()
            return f"weekly:{weekday}", remaining

    daily_match = _RECURRENCE_DAILY_PATTERN.search(remaining)
    if daily_match:
        remaining = remaining[:daily_match.start()] + remaining[daily_match.end():]
        remaining = re.sub(r"\s+", " ", remaining).strip()
        return "daily", remaining

    return None, text


def parse_natural_task(text: str) -> ParseTaskResult:
    cleaned = text.strip()
    if not cleaned:
        return ParseTaskResult(title=cleaned)

    tags, cleaned = extract_tags(cleaned)
    project, cleaned = extract_project(cleaned)
    priority, cleaned = extract_priority(cleaned)
    recurrence_rule, cleaned = extract_recurrence(cleaned)
    due_date, due_time, cleaned = extract_datetime(cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        cleaned = text.strip()
        tags = []
        project = None
        priority = None
        recurrence_rule = None
        due_date = None
        due_time = None

    return ParseTaskResult(
        title=cleaned,
        due_date=due_date,
        due_time=due_time,
        priority=priority,
        tags=tags,
        project=project,
        recurrence_rule=recurrence_rule,
    )
