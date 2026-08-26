#!/usr/bin/env python3
"""八字排盘引擎 — 基于 lunar-python

完整四柱八字排盘：天干地支、五行、十神、纳音、地势(长生十二神)、
胎元、命宫、身宫、大运流年。输出结构化JSON。
"""

import argparse
import json
import sys
from datetime import datetime

from lunar_python import Solar

# 五行属性表
WUXING_MAP = {
    "甲": "木",
    "乙": "木",
    "丙": "火",
    "丁": "火",
    "戊": "土",
    "己": "土",
    "庚": "金",
    "辛": "金",
    "壬": "水",
    "癸": "水",
    "子": "水",
    "丑": "土",
    "寅": "木",
    "卯": "木",
    "辰": "土",
    "巳": "火",
    "午": "火",
    "未": "土",
    "申": "金",
    "酉": "金",
    "戌": "土",
    "亥": "水",
}

# 阴阳属性表
YINYANG_MAP = {
    "甲": "阳",
    "乙": "阴",
    "丙": "阳",
    "丁": "阴",
    "戊": "阳",
    "己": "阴",
    "庚": "阳",
    "辛": "阴",
    "壬": "阳",
    "癸": "阴",
    "子": "阳",
    "丑": "阴",
    "寅": "阳",
    "卯": "阴",
    "辰": "阳",
    "巳": "阴",
    "午": "阳",
    "未": "阴",
    "申": "阳",
    "酉": "阴",
    "戌": "阳",
    "亥": "阴",
}

# 五行生克关系
WUXING_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
WUXING_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


def _count_wuxing(ba) -> dict:
    """统计八字中各五行数量（天干+地支）"""
    counts = {"金": 0, "木": 0, "水": 0, "火": 0, "土": 0}
    elements = [
        ba.getYearGan(),
        ba.getYearZhi(),
        ba.getMonthGan(),
        ba.getMonthZhi(),
        ba.getDayGan(),
        ba.getDayZhi(),
        ba.getTimeGan(),
        ba.getTimeZhi(),
    ]
    for e in elements:
        wx = WUXING_MAP.get(e, "")
        if wx:
            counts[wx] += 1
    return counts


def _analyze_day_master(ba) -> dict:
    """分析日主强弱"""
    day_gan = ba.getDayGan()
    day_wx = WUXING_MAP.get(day_gan, "")
    counts = _count_wuxing(ba)

    # 生我者（正印、偏印）+ 同我者（比肩、劫财）= 得令数
    support = counts.get(day_wx, 0)  # 同我
    # 生我的五行
    for wx, target in WUXING_SHENG.items():
        if target == day_wx:
            support += counts.get(wx, 0)
            break

    total = sum(counts.values())
    strength_ratio = support / total if total > 0 else 0

    if strength_ratio >= 0.5:
        strength = "身强"
        advice = "宜泄宜克：食伤生财、官杀制身"
    else:
        strength = "身弱"
        advice = "宜生宜扶：印星生身、比劫帮身"

    return {
        "day_gan": day_gan,
        "day_wuxing": day_wx,
        "day_yinyang": YINYANG_MAP.get(day_gan, ""),
        "wuxing_counts": counts,
        "support_count": support,
        "total_count": total,
        "strength_ratio": round(strength_ratio, 2),
        "strength": strength,
        "method": "八字明字五行计数启发式（未计月令权重、藏干与通根）",
        "advice": advice,
    }


def generate_bazi(
    year: int,
    month: int,
    day: int,
    hour: int,
    gender: int = 1,
    minute: int = 0,
    second: int = 0,
    sect: int = 2,
) -> dict:
    """
    生成完整八字命盘

    Args:
        year: 公历年
        month: 公历月
        day: 公历日
        hour: 时辰（0-23）
        gender: 1=男, 0=女
        minute: 分钟（0-59）
        second: 秒（0-59）
        sect: lunar-python 换日流派，1=晚子时换日，2=午夜换日（默认）

    Returns:
        结构化JSON dict
    """
    if gender not in (0, 1):
        raise ValueError("gender 必须是 1（男）或 0（女）")
    if sect not in (1, 2):
        raise ValueError("sect 必须是 1 或 2")
    if not 1900 <= year <= 2100:
        raise ValueError("year 必须在 1900-2100 之间")
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise ValueError(f"无效的公历出生时间: {exc}") from exc

    s = Solar.fromYmdHms(year, month, day, hour, minute, second)
    l = s.getLunar()
    ba = l.getEightChar()
    ba.setSect(sect)

    # 四柱
    pillars = {
        "year": {
            "ganzhi": ba.getYear(),
            "gan": ba.getYearGan(),
            "zhi": ba.getYearZhi(),
            "wuxing": ba.getYearWuXing(),
            "nayin": ba.getYearNaYin(),
            "shishen_gan": ba.getYearShiShenGan(),
            "shishen_zhi": ba.getYearShiShenZhi(),
            "dishi": ba.getYearDiShi(),
            "gan_yinyang": YINYANG_MAP.get(ba.getYearGan(), ""),
            "zhi_yinyang": YINYANG_MAP.get(ba.getYearZhi(), ""),
        },
        "month": {
            "ganzhi": ba.getMonth(),
            "gan": ba.getMonthGan(),
            "zhi": ba.getMonthZhi(),
            "wuxing": ba.getMonthWuXing(),
            "nayin": ba.getMonthNaYin(),
            "shishen_gan": ba.getMonthShiShenGan(),
            "shishen_zhi": ba.getMonthShiShenZhi(),
            "dishi": ba.getMonthDiShi(),
            "gan_yinyang": YINYANG_MAP.get(ba.getMonthGan(), ""),
            "zhi_yinyang": YINYANG_MAP.get(ba.getMonthZhi(), ""),
        },
        "day": {
            "ganzhi": ba.getDay(),
            "gan": ba.getDayGan(),
            "zhi": ba.getDayZhi(),
            "wuxing": ba.getDayWuXing(),
            "nayin": ba.getDayNaYin(),
            "shishen_zhi": ba.getDayShiShenZhi(),
            "dishi": ba.getDayDiShi(),
            "gan_yinyang": YINYANG_MAP.get(ba.getDayGan(), ""),
            "zhi_yinyang": YINYANG_MAP.get(ba.getDayZhi(), ""),
        },
        "time": {
            "ganzhi": ba.getTime(),
            "gan": ba.getTimeGan(),
            "zhi": ba.getTimeZhi(),
            "wuxing": ba.getTimeWuXing(),
            "nayin": ba.getTimeNaYin(),
            "shishen_gan": ba.getTimeShiShenGan(),
            "shishen_zhi": ba.getTimeShiShenZhi(),
            "dishi": ba.getTimeDiShi(),
            "gan_yinyang": YINYANG_MAP.get(ba.getTimeGan(), ""),
            "zhi_yinyang": YINYANG_MAP.get(ba.getTimeZhi(), ""),
        },
    }

    # 胎元、命宫、身宫
    special = {
        "tai_yuan": ba.getTaiYuan(),
        "tai_yuan_nayin": ba.getTaiYuanNaYin(),
        "ming_gong": ba.getMingGong(),
        "ming_gong_nayin": ba.getMingGongNaYin(),
        "shen_gong": ba.getShenGong(),
        "shen_gong_nayin": ba.getShenGongNaYin(),
    }

    # 日主分析
    day_master = _analyze_day_master(ba)

    # 大运
    yun = ba.getYun(gender)
    da_yun_list = []
    for i, dy in enumerate(yun.getDaYun()):
        gz = dy.getGanZhi()
        if not gz:
            continue
        gan = gz[0] if len(gz) >= 2 else ""
        da_yun_list.append(
            {
                "index": i,
                "ganzhi": gz,
                "start_year": dy.getStartYear(),
                "end_year": dy.getEndYear(),
                "start_age": dy.getStartAge(),
                "end_age": dy.getEndAge(),
                "gan_wuxing": WUXING_MAP.get(gan, ""),
            }
        )

    # 基本信息
    result = {
        "input": {
            "solar_date": f"{year}-{month:02d}-{day:02d}",
            "hour": hour,
            "minute": minute,
            "second": second,
            "sect": sect,
            "gender": "男" if gender == 1 else "女",
        },
        "lunar": {
            "date": str(l),
            "shengxiao": l.getYearShengXiao(),
            "constellation": s.getXingZuo(),
        },
        "pillars": pillars,
        "special": special,
        "day_master": day_master,
        "da_yun": {
            "start_age": da_yun_list[0]["start_age"] if da_yun_list else None,
            "start_solar": str(yun.getStartSolar()),
            "start_offset": {
                "years": yun.getStartYear(),
                "months": yun.getStartMonth(),
                "days": yun.getStartDay(),
                "hours": yun.getStartHour(),
            },
            "list": da_yun_list,
        },
    }

    return result


def format_bazi_text(data: dict) -> str:
    """将八字数据格式化为可读文本"""
    lines = []
    inp = data["input"]
    lines.append(
        f"【八字排盘】{inp['solar_date']} "
        f"{inp['hour']:02d}:{inp.get('minute', 0):02d} {inp['gender']}"
    )
    lines.append(
        f"农历: {data['lunar']['date']}  生肖: {data['lunar']['shengxiao']}  星座: {data['lunar']['constellation']}"
    )
    lines.append("")

    p = data["pillars"]
    lines.append("    年柱      月柱      日柱      时柱")
    lines.append(
        f"    {p['year']['ganzhi']}      {p['month']['ganzhi']}      {p['day']['ganzhi']}      {p['time']['ganzhi']}"
    )
    lines.append(
        f"    {p['year']['wuxing']}    {p['month']['wuxing']}    {p['day']['wuxing']}    {p['time']['wuxing']}"
    )
    lines.append(
        f"    {p['year']['nayin']}  {p['month']['nayin']}  {p['day']['nayin']}  {p['time']['nayin']}"
    )
    lines.append("")

    dm = data["day_master"]
    lines.append(
        f"日主: {dm['day_gan']}({dm['day_wuxing']}{dm['day_yinyang']})  "
        f"轻量强弱提示: {dm['strength']} (扶助比:{dm['strength_ratio']})"
    )
    lines.append(
        f"五行: 金{dm['wuxing_counts']['金']} 木{dm['wuxing_counts']['木']} 水{dm['wuxing_counts']['水']} 火{dm['wuxing_counts']['火']} 土{dm['wuxing_counts']['土']}"
    )
    lines.append(f"提示: {dm['advice']}（仅为明字计数启发式，不替代完整旺衰辨析）")
    lines.append("")

    sp = data["special"]
    lines.append(
        f"胎元: {sp['tai_yuan']}({sp['tai_yuan_nayin']})  命宫: {sp['ming_gong']}({sp['ming_gong_nayin']})  身宫: {sp['shen_gong']}({sp['shen_gong_nayin']})"
    )
    lines.append("")

    lines.append("【大运】")
    for dy in data["da_yun"]["list"][:8]:
        lines.append(
            f"  {dy['ganzhi']} ({dy['start_year']}-{dy['end_year']}, {dy['start_age']}-{dy['end_age']}岁)"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    for _stream_name in ("stdin", "stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description="八字排盘引擎")
    parser.add_argument("year", type=int)
    parser.add_argument("month", type=int)
    parser.add_argument("day", type=int)
    parser.add_argument("hour", type=int)
    parser.add_argument("gender", type=int, nargs="?", default=1, choices=(0, 1))
    parser.add_argument("--minute", type=int, default=0)
    parser.add_argument("--second", type=int, default=0)
    parser.add_argument("--sect", type=int, choices=(1, 2), default=2)
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()
    try:
        result = generate_bazi(
            args.year,
            args.month,
            args.day,
            args.hour,
            args.gender,
            args.minute,
            args.second,
            args.sect,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(
        format_bazi_text(result) if args.text else json.dumps(result, ensure_ascii=False, indent=2)
    )
