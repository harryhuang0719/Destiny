#!/usr/bin/env python3
"""历法/干支引擎 — 基于 lunar-python

提供公历↔农历转换、干支、节气、生肖、宜忌等基础数据。
所有术数引擎的底层依赖。
"""

import argparse
import json
import sys
from datetime import datetime

from lunar_python import Lunar, Solar


def solar_to_lunar_info(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> dict:
    """公历日期 → 完整历法信息（JSON-serializable dict）"""
    if not 1900 <= year <= 2100:
        raise ValueError("year 必须在 1900-2100 之间")
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise ValueError(f"无效的公历时间: {exc}") from exc

    s = Solar.fromYmdHms(year, month, day, hour, minute, second)
    l = s.getLunar()

    # 节气
    jie_qi = l.getJieQi()
    # 当年节气表
    jie_qi_table = {}
    for name, solar in l.getJieQiTable().items():
        # lunar-python includes uppercase aliases for the year boundary.
        if solar.getYear() == year and any("\u4e00" <= c <= "\u9fff" for c in name):
            jie_qi_table[name] = solar.toYmdHms()

    # 宜忌
    yi_list = l.getDayYi()
    ji_list = l.getDayJi()

    # 星宿
    xiu = l.getXiu()
    xiu_song = l.getXiuSong()

    # 彭祖百忌
    peng_zu_gan = l.getPengZuGan()
    peng_zu_zhi = l.getPengZuZhi()

    # 值神 & 建除十二值星
    zhi_shen = l.getDayTianShen()
    zhi_shen_type = l.getDayTianShenType()
    zhi_shen_luck = l.getDayTianShenLuck()
    jian_chu = l.getZhiXing()

    weekday = s.getWeek()
    weekday_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    result = {
        "solar": {
            "year": year,
            "month": month,
            "day": day,
            "hour": hour,
            "minute": minute,
            "second": second,
            "weekday": weekday,
            "weekday_name": weekday_names[weekday],
            "constellation": s.getXingZuo(),
        },
        "lunar": {
            "year": l.getYear(),
            "month": l.getMonth(),
            "day": l.getDay(),
            "year_cn": l.getYearInChinese(),
            "month_cn": l.getMonthInChinese(),
            "day_cn": l.getDayInChinese(),
            "is_leap": l.getMonth() < 0,
            "full_string": str(l),
        },
        "ganzhi": {
            "year": l.getYearInGanZhiExact(),
            "lunar_year": l.getYearInGanZhi(),
            "month": l.getMonthInGanZhiExact(),
            "day": l.getDayInGanZhi(),
            "year_gan": l.getYearGanExact(),
            "year_zhi": l.getYearZhiExact(),
            "month_gan": l.getMonthGanExact(),
            "month_zhi": l.getMonthZhiExact(),
            "day_gan": l.getDayGan(),
            "day_zhi": l.getDayZhi(),
        },
        "shengxiao": l.getYearShengXiao(),
        "jie_qi": jie_qi if jie_qi else "无",
        "jie_qi_year": jie_qi_table,
        "yi": yi_list if isinstance(yi_list, list) else [],
        "ji": ji_list if isinstance(ji_list, list) else [],
        "xing_xiu": {"name": xiu, "song": xiu_song},
        "peng_zu": {"gan": peng_zu_gan, "zhi": peng_zu_zhi},
        "zhi_shen": {
            "name": zhi_shen,
            "type": zhi_shen_type,
            "luck": zhi_shen_luck,
        },
        "jian_chu": jian_chu,
    }

    return result


def get_jie_qi_around(year: int, month: int, day: int) -> list:
    """获取某日期前后的节气"""
    s = Solar.fromYmd(year, month, day)
    l = s.getLunar()
    result = []
    prev_jq = l.getPrevJieQi()
    next_jq = l.getNextJieQi()
    if prev_jq:
        result.append(
            {"name": prev_jq.getName(), "solar": prev_jq.getSolar().toYmdHms(), "type": "prev"}
        )
    if next_jq:
        result.append(
            {"name": next_jq.getName(), "solar": next_jq.getSolar().toYmdHms(), "type": "next"}
        )
    return result


def lunar_to_solar(year: int, month: int, day: int, is_leap: bool = False) -> dict:
    """农历 → 公历"""
    if not 1900 <= year <= 2100:
        raise ValueError("year 必须在 1900-2100 之间")
    try:
        l = Lunar.fromYmd(year, month if not is_leap else -month, day)
    except Exception as exc:
        raise ValueError(f"无效农历日期: {year}-{month}-{day}, leap={is_leap}") from exc
    s = l.getSolar()
    return {
        "solar_year": s.getYear(),
        "solar_month": s.getMonth(),
        "solar_day": s.getDay(),
        "solar_string": str(s),
    }


if __name__ == "__main__":
    for _stream_name in ("stdin", "stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="strict")
    if len(sys.argv) > 1 and sys.argv[1] == "lunar":
        parser = argparse.ArgumentParser(description="农历转公历")
        parser.add_argument("mode", choices=("lunar",))
        parser.add_argument("year", type=int)
        parser.add_argument("month", type=int)
        parser.add_argument("day", type=int)
        parser.add_argument("--leap", action="store_true")
        args = parser.parse_args()
        try:
            result = lunar_to_solar(args.year, args.month, args.day, args.leap)
        except Exception as exc:
            parser.error(str(exc))
    else:
        parser = argparse.ArgumentParser(description="公历转农历与黄历信息")
        parser.add_argument("year", type=int)
        parser.add_argument("month", type=int)
        parser.add_argument("day", type=int)
        parser.add_argument("hour", type=int, nargs="?", default=0)
        parser.add_argument("--minute", type=int, default=0)
        parser.add_argument("--second", type=int, default=0)
        args = parser.parse_args()
        try:
            result = solar_to_lunar_info(
                args.year, args.month, args.day, args.hour, args.minute, args.second
            )
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
