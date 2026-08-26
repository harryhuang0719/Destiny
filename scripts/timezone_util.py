#!/usr/bin/env python3
"""真太阳时（True Solar Time）工具。

标准时区不等于太阳实际位置。八字的时柱基于太阳在天空中的真实位置，
而非时钟显示的时间。误差可达 ±30 分钟，足以改变时辰（2小时一个时辰）。

用法:
    from timezone_util import true_solar_time, get_longitude
    solar_dt = true_solar_time(datetime(1990, 6, 15, 14), longitude=121.5, tz_offset_hours=8)
"""

import calendar
import importlib.metadata
import importlib.resources
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# 主要城市经度 (东经为正，西经为负)
CITY_LONGITUDES = {
    # 中国
    "北京": 116.4,
    "上海": 121.5,
    "广州": 113.3,
    "深圳": 114.1,
    "成都": 104.1,
    "重庆": 106.5,
    "武汉": 114.3,
    "西安": 108.9,
    "杭州": 120.2,
    "南京": 118.8,
    "天津": 117.2,
    "长沙": 113.0,
    "哈尔滨": 126.6,
    "大连": 121.6,
    "青岛": 120.4,
    "郑州": 113.7,
    "沈阳": 123.4,
    "昆明": 102.7,
    "福州": 119.3,
    "厦门": 118.1,
    "合肥": 117.3,
    "济南": 117.0,
    "石家庄": 114.5,
    "太原": 112.6,
    "乌鲁木齐": 87.6,
    "拉萨": 91.1,
    "呼和浩特": 111.7,
    "香港": 114.2,
    "澳门": 113.5,
    "台北": 121.5,
    "高雄": 120.3,
    # 美国
    "New York": -74.0,
    "Los Angeles": -118.2,
    "Chicago": -87.6,
    "San Francisco": -122.4,
    "Boston": -71.1,
    "Seattle": -122.3,
    "Houston": -95.4,
    "Miami": -80.2,
    "Atlanta": -84.4,
    # 其他
    "London": -0.1,
    "Tokyo": 139.7,
    "Seoul": 127.0,
    "Singapore": 103.8,
    # 默认
    "default": 120.0,  # UTC+8 标准子午线
}

# 用于按出生日期解析当地真实 UTC 偏移（包括历史夏令时）。
# 中国大陆统一使用法定北京时间，因此乌鲁木齐等城市仍映射到
# Asia/Shanghai；经度差由真太阳时公式单独校正。
CITY_TIMEZONES = {
    **{
        city: "Asia/Shanghai"
        for city in (
            "北京",
            "上海",
            "广州",
            "深圳",
            "成都",
            "重庆",
            "武汉",
            "西安",
            "杭州",
            "南京",
            "天津",
            "长沙",
            "哈尔滨",
            "大连",
            "青岛",
            "郑州",
            "沈阳",
            "昆明",
            "福州",
            "厦门",
            "合肥",
            "济南",
            "石家庄",
            "太原",
            "乌鲁木齐",
            "拉萨",
            "呼和浩特",
        )
    },
    "香港": "Asia/Hong_Kong",
    "澳门": "Asia/Macau",
    "台北": "Asia/Taipei",
    "高雄": "Asia/Taipei",
    "New York": "America/New_York",
    "Los Angeles": "America/Los_Angeles",
    "Chicago": "America/Chicago",
    "San Francisco": "America/Los_Angeles",
    "Boston": "America/New_York",
    "Seattle": "America/Los_Angeles",
    "Houston": "America/Chicago",
    "Miami": "America/New_York",
    "Atlanta": "America/New_York",
    "London": "Europe/London",
    "Tokyo": "Asia/Tokyo",
    "Seoul": "Asia/Seoul",
    "Singapore": "Asia/Singapore",
    "default": "Asia/Shanghai",
}

# 时区标准子午线
TZ_MERIDIANS = {
    -8: -120.0,
    -7: -105.0,
    -6: -90.0,
    -5: -75.0,
    -4: -60.0,
    0: 0.0,
    1: 15.0,
    2: 30.0,
    8: 120.0,
    9: 135.0,
    10: 150.0,
}


def equation_of_time(day_of_year: int) -> float:
    """时差方程 (Equation of Time)，返回分钟数。
    修正地球轨道偏心率和地轴倾斜导致的太阳时与平均太阳时的偏差。
    """
    b = 2 * math.pi * (day_of_year - 81) / 365
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def true_solar_time(
    dt: datetime,
    longitude: float = 120.0,
    tz_offset_hours: float = 8,
) -> datetime:
    """将标准时钟时间转换为真太阳时 (真太阳时)。

    Args:
        dt: 标准（时钟）时间
        longitude: 观测者经度（东经为正）
        tz_offset_hours: 时钟时间的 UTC 偏移（如 UTC+8 传 8）

    Returns:
        调整后的真太阳时 datetime
    """
    standard_meridian = TZ_MERIDIANS.get(tz_offset_hours, tz_offset_hours * 15.0)
    # 经度修正：每度 4 分钟
    lng_correction = (longitude - standard_meridian) * 4  # minutes
    # 时差方程修正
    eot = equation_of_time(dt.timetuple().tm_yday)
    total_correction = lng_correction + eot  # minutes
    return dt + timedelta(minutes=total_correction)


def get_longitude(city: str = "default") -> float:
    """查询城市经度。未知城市返回 UTC+8 标准子午线 (120E)。"""
    return CITY_LONGITUDES.get(city, CITY_LONGITUDES["default"])


def has_city(city: str) -> bool:
    """Return whether ``city`` is in the built-in coordinate table."""
    return city in CITY_LONGITUDES and city != "default"


def get_timezone_name(city: str = "default") -> str:
    """Return the IANA timezone associated with a supported city."""
    return CITY_TIMEZONES.get(city, CITY_TIMEZONES["default"])


def tzdata_version() -> str:
    """Return the pinned IANA database version used for city resolution."""
    try:
        return importlib.metadata.version("tzdata")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("缺少固定版本 tzdata；请重新运行 bootstrap") from exc


def _load_pinned_zone(zone_name: str) -> ZoneInfo:
    """Load TZif bytes from the pinned package rather than the host OS."""
    try:
        resource = importlib.resources.files("tzdata.zoneinfo").joinpath(*zone_name.split("/"))
        with resource.open("rb") as handle:
            return ZoneInfo.from_file(handle, key=zone_name)
    except (ModuleNotFoundError, FileNotFoundError, ValueError) as exc:
        raise ValueError(f"无法从固定 tzdata 加载时区 {zone_name}") from exc


def resolve_utc_offset(
    dt: datetime,
    city: str = "default",
    explicit_offset: float | None = None,
) -> float:
    """Resolve the civil UTC offset for ``dt``.

    An explicit ``--tz`` value wins. Otherwise a supported city's IANA zone is
    used so historical daylight-saving rules are respected. Missing timezone
    data fails closed; it never silently falls back to UTC+8.
    """
    if explicit_offset is not None:
        if not -12 <= explicit_offset <= 14:
            raise ValueError(f"UTC 时区偏移 {explicit_offset} 超出范围 (-12 到 +14)")
        return float(explicit_offset)

    zone_name = get_timezone_name(city)
    zone = _load_pinned_zone(zone_name)
    candidates = [dt.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    valid = []
    for candidate in candidates:
        round_trip = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if round_trip == dt:
            valid.append(candidate)
    if not valid:
        raise ValueError(f"{dt.isoformat()} 在 {zone_name} 是夏令时跳过的不存在时间")
    offsets = {candidate.utcoffset() for candidate in valid}
    if len(offsets) > 1:
        raise ValueError(f"{dt.isoformat()} 在 {zone_name} 是夏令时回拨的歧义时间；请显式提供 --tz")
    offset = valid[0].utcoffset()
    return offset.total_seconds() / 3600 if offset is not None else 8.0


def list_cities() -> list[str]:
    """列出所有支持的城市名。"""
    return [c for c in CITY_LONGITUDES if c != "default"]


def validate_datetime(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> str | None:
    """验证日期时间输入。返回错误信息或 None（合法）。"""
    if year < 1900 or year > 2100:
        return f"年份 {year} 超出范围 (1900-2100)"
    if month < 1 or month > 12:
        return f"月份 {month} 无效 (1-12)"
    max_day = calendar.monthrange(year, month)[1]
    if day < 1 or day > max_day:
        return f"日期 {day} 无效，{year}年{month}月最多 {max_day} 天"
    if hour < 0 or hour > 23:
        return f"时辰 {hour} 无效 (0-23)"
    if minute < 0 or minute > 59:
        return f"分钟 {minute} 无效 (0-59)"
    if second < 0 or second > 59:
        return f"秒 {second} 无效 (0-59)"
    return None
