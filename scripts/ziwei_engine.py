#!/usr/bin/env python3
"""紫微斗数排盘引擎 — 通过 Node.js 调用 iztro

调用 iztro npm 包生成完整紫微斗数星盘，输出结构化JSON。
支持公历/农历输入、男女、十二宫位、主星辅星、四化、大限流年。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# iztro 安装目录
IZTRO_DIR = Path(__file__).parent.parent  # destiny skill root (has node_modules)
BRIDGE_PATH = Path(__file__).with_name("ziwei_bridge.cjs")


def _hour_to_index(hour: int) -> int:
    """将24小时制转为紫微时辰序号（0=子时早, 1=丑时, ..., 12=子时晚）"""
    if not 0 <= hour <= 23:
        raise ValueError("hour 必须在 0-23 之间")
    if hour == 23:
        return 12  # iztro 区分晚子时，不能与 00:00 的早子时混为 index 0
    mapping = [
        (0, 1, 0),  # 早子时 00:00-01:00
        (1, 3, 1),  # 丑时 01:00-03:00
        (3, 5, 2),  # 寅时 03:00-05:00
        (5, 7, 3),  # 卯时 05:00-07:00
        (7, 9, 4),  # 辰时 07:00-09:00
        (9, 11, 5),  # 巳时 09:00-11:00
        (11, 13, 6),  # 午时 11:00-13:00
        (13, 15, 7),  # 未时 13:00-15:00
        (15, 17, 8),  # 申时 15:00-17:00
        (17, 19, 9),  # 酉时 17:00-19:00
        (19, 21, 10),  # 戌时 19:00-21:00
        (21, 23, 11),  # 亥时 21:00-23:00
    ]
    for start, end, idx in mapping:
        if start <= hour < end:
            return idx
    raise ValueError(f"无法映射小时: {hour}")


SHICHEN_NAMES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子"]


def _safe_node_env() -> dict[str, str]:
    """Pass Node only the process fields it needs, never unrelated API keys."""
    allowed = (
        "PATH",
        "LANG",
        "LC_ALL",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TMPDIR",
        "TEMP",
        "TMP",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["NODE_PATH"] = str(IZTRO_DIR / "node_modules")
    return env


def generate_ziwei(
    year: int,
    month: int,
    day: int,
    hour: int,
    gender: str = "男",
    minute: int = 0,
    second: int = 0,
) -> dict:
    """
    生成紫微斗数星盘

    Args:
        year: 公历年
        month: 公历月
        day: 公历日
        hour: 时辰（0-23 小时制）
        gender: "男" 或 "女"

    Returns:
        结构化JSON dict
    """
    if gender not in ("男", "女"):
        raise ValueError("gender 必须是“男”或“女”")
    if not 1900 <= year <= 2100:
        raise ValueError("year 必须在 1900-2100 之间")
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise ValueError(f"无效的公历出生时间: {exc}") from exc

    solar_date = f"{year}-{month:02d}-{day:02d}"
    hour_index = _hour_to_index(hour)
    payload = json.dumps(
        {"solarDate": solar_date, "hourIndex": hour_index, "gender": gender},
        ensure_ascii=False,
    )

    try:
        child_env = _safe_node_env()
        node_path = shutil.which("node", path=child_env.get("PATH"))
        if not node_path:
            raise FileNotFoundError("node")
        proc = subprocess.run(
            [node_path, str(BRIDGE_PATH)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=10,
            cwd=str(IZTRO_DIR),
            env=child_env,
        )

        if proc.returncode != 0:
            detail = proc.stderr.strip()[-1200:]
            return {"error": f"iztro failed: {detail}", "palaces": []}

        data = json.loads(proc.stdout.strip())

    except subprocess.TimeoutExpired:
        return {"error": "iztro timeout (>10s)", "palaces": []}
    except json.JSONDecodeError as e:
        return {"error": f"iztro JSON parse error: {e}", "palaces": []}
    except FileNotFoundError:
        return {"error": "Node.js not found. Install Node.js to use ziwei engine.", "palaces": []}
    except OSError as exc:
        return {"error": f"Unable to start Node.js: {exc}", "palaces": []}

    # 增强：找出命宫和身宫
    soul_palace = None
    body_palace = None
    for p in data.get("palaces", []):
        if (
            p.get("earthlyBranch") == data.get("earthlyBranchOfSoulPalace")
            and p.get("name") == "命宫"
        ):
            soul_palace = p
        if p.get("earthlyBranch") == data.get("earthlyBranchOfBodyPalace"):
            body_palace = p

    result = {
        "input": {
            "solar_date": solar_date,
            "hour": hour,
            "minute": minute,
            "second": second,
            "shichen": SHICHEN_NAMES[hour_index] + "时",
            "gender": gender,
        },
        "soul_star": data.get("soul", ""),
        "body_star": data.get("body", ""),
        "five_elements_class": data.get("fiveElementsClass", ""),
        "soul_palace": soul_palace,
        "body_palace": body_palace,
        "palaces": data.get("palaces", []),
    }

    return result


def format_ziwei_text(data: dict) -> str:
    """格式化紫微星盘为可读文本"""
    if "error" in data:
        return f"紫微排盘错误: {data['error']}"

    lines = []
    inp = data["input"]
    lines.append(f"【紫微斗数星盘】{inp['solar_date']} {inp['shichen']} {inp['gender']}")
    lines.append(
        f"命主星: {data['soul_star']}  身主星: {data['body_star']}  局: {data.get('five_elements_class', '')}"
    )
    lines.append("")

    for p in data["palaces"]:
        major = ", ".join(
            f"{s['name']}({s['brightness']})" + (f"[{s['mutagen']}]" if s.get("mutagen") else "")
            for s in p.get("majorStars", [])
        )
        minor = ", ".join(s["name"] for s in p.get("minorStars", []))

        palace_line = f"【{p['name']}】{p.get('heavenlyStem', '')}{p.get('earthlyBranch', '')}"
        if major:
            palace_line += f"  主星: {major}"
        if minor:
            palace_line += f"  辅星: {minor}"

        decadal = p.get("decadal")
        if decadal and decadal.get("range"):
            palace_line += f"  大限: {decadal['range'][0]}-{decadal['range'][1]}岁"

        lines.append(palace_line)

    return "\n".join(lines)


if __name__ == "__main__":
    for _stream_name in ("stdin", "stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description="紫微斗数排盘引擎")
    parser.add_argument("year", type=int)
    parser.add_argument("month", type=int)
    parser.add_argument("day", type=int)
    parser.add_argument("hour", type=int)
    parser.add_argument("gender", nargs="?", default="男", choices=("男", "女"))
    parser.add_argument("--minute", type=int, default=0)
    parser.add_argument("--second", type=int, default=0)
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()
    try:
        result = generate_ziwei(
            args.year,
            args.month,
            args.day,
            args.hour,
            args.gender,
            args.minute,
            args.second,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if "error" in result:
        parser.exit(3, f"紫微排盘错误: {result['error']}\n")
    print(
        format_ziwei_text(result) if args.text else json.dumps(result, ensure_ascii=False, indent=2)
    )
