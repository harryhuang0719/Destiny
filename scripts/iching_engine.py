#!/usr/bin/env python3
"""周易六爻轻量引擎 — 纯Python自建

支持：大衍之数起卦、时间起卦、手动输入卦象。
输出：本卦、变卦、变爻、卦辞、爻辞、纳甲信息。
无C扩展依赖，纯Python实现。
"""

import argparse
import json
import random
import re
import sys
from datetime import datetime

# ============================================================
# 基础数据
# ============================================================

# 八卦（先天序）
BAGUA = {
    "乾": {"symbol": "☰", "nature": "天", "wuxing": "金", "lines": (1, 1, 1)},
    "兑": {"symbol": "☱", "nature": "泽", "wuxing": "金", "lines": (1, 1, 0)},
    "离": {"symbol": "☲", "nature": "火", "wuxing": "火", "lines": (1, 0, 1)},
    "震": {"symbol": "☳", "nature": "雷", "wuxing": "木", "lines": (1, 0, 0)},
    "巽": {"symbol": "☴", "nature": "风", "wuxing": "木", "lines": (0, 1, 1)},
    "坎": {"symbol": "☵", "nature": "水", "wuxing": "水", "lines": (0, 1, 0)},
    "艮": {"symbol": "☶", "nature": "山", "wuxing": "土", "lines": (0, 0, 1)},
    "坤": {"symbol": "☷", "nature": "地", "wuxing": "土", "lines": (0, 0, 0)},
}

# 后天八卦数
BAGUA_NUM = {"坎": 1, "坤": 2, "震": 3, "巽": 4, "乾": 6, "兑": 7, "艮": 8, "离": 9}

# 三爻 → 卦名 映射  (bottom, mid, top)
LINES_TO_GUA = {}
for name, info in BAGUA.items():
    LINES_TO_GUA[info["lines"]] = name

# 六十四卦 (上卦, 下卦) → (卦名, 卦序)
HEXAGRAMS = {
    ("乾", "乾"): ("乾为天", 1),
    ("坤", "坤"): ("坤为地", 2),
    ("坎", "震"): ("水雷屯", 3),
    ("艮", "坎"): ("山水蒙", 4),
    ("坎", "乾"): ("水天需", 5),
    ("乾", "坎"): ("天水讼", 6),
    ("坤", "坎"): ("地水师", 7),
    ("坎", "坤"): ("水地比", 8),
    ("巽", "乾"): ("风天小畜", 9),
    ("乾", "兑"): ("天泽履", 10),
    ("坤", "乾"): ("地天泰", 11),
    ("乾", "坤"): ("天地否", 12),
    ("乾", "离"): ("天火同人", 13),
    ("离", "乾"): ("火天大有", 14),
    ("坤", "艮"): ("地山谦", 15),
    ("震", "坤"): ("雷地豫", 16),
    ("兑", "震"): ("泽雷随", 17),
    ("艮", "巽"): ("山风蛊", 18),
    ("坤", "兑"): ("地泽临", 19),
    ("巽", "坤"): ("风地观", 20),
    ("离", "震"): ("火雷噬嗑", 21),
    ("艮", "离"): ("山火贲", 22),
    ("艮", "坤"): ("山地剥", 23),
    ("坤", "震"): ("地雷复", 24),
    ("乾", "震"): ("天雷无妄", 25),
    ("艮", "乾"): ("山天大畜", 26),
    ("艮", "震"): ("山雷颐", 27),
    ("兑", "巽"): ("泽风大过", 28),
    ("坎", "坎"): ("坎为水", 29),
    ("离", "离"): ("离为火", 30),
    ("兑", "艮"): ("泽山咸", 31),
    ("震", "巽"): ("雷风恒", 32),
    ("乾", "艮"): ("天山遁", 33),
    ("震", "乾"): ("雷天大壮", 34),
    ("离", "坤"): ("火地晋", 35),
    ("坤", "离"): ("地火明夷", 36),
    ("巽", "离"): ("风火家人", 37),
    ("离", "兑"): ("火泽睽", 38),
    ("坎", "艮"): ("水山蹇", 39),
    ("震", "坎"): ("雷水解", 40),
    ("艮", "兑"): ("山泽损", 41),
    ("巽", "震"): ("风雷益", 42),
    ("兑", "乾"): ("泽天夬", 43),
    ("乾", "巽"): ("天风姤", 44),
    ("兑", "坤"): ("泽地萃", 45),
    ("坤", "巽"): ("地风升", 46),
    ("兑", "坎"): ("泽水困", 47),
    ("坎", "巽"): ("水风井", 48),
    ("兑", "离"): ("泽火革", 49),
    ("离", "巽"): ("火风鼎", 50),
    ("震", "震"): ("震为雷", 51),
    ("艮", "艮"): ("艮为山", 52),
    ("巽", "艮"): ("风山渐", 53),
    ("震", "兑"): ("雷泽归妹", 54),
    ("震", "离"): ("雷火丰", 55),
    ("离", "艮"): ("火山旅", 56),
    ("巽", "巽"): ("巽为风", 57),
    ("兑", "兑"): ("兑为泽", 58),
    ("巽", "坎"): ("风水涣", 59),
    ("坎", "兑"): ("水泽节", 60),
    ("巽", "兑"): ("风泽中孚", 61),
    ("震", "艮"): ("雷山小过", 62),
    ("坎", "离"): ("水火既济", 63),
    ("离", "坎"): ("火水未济", 64),
}

# 六十四卦卦辞（精简版）
GUA_CI = {
    "乾为天": "元亨利贞。潜龙勿用，见龙在田，终日乾乾，或跃在渊，飞龙在天，亢龙有悔。",
    "坤为地": "元亨，利牝马之贞。君子有攸往，先迷后得主。利西南得朋，东北丧朋。安贞吉。",
    "水雷屯": "元亨利贞，勿用有攸往，利建侯。初始虽难，坚持有利。",
    "山水蒙": "亨，匪我求童蒙，童蒙求我。初筮告，再三渎，渎则不告。利贞。",
    "水天需": "有孚，光亨贞吉，利涉大川。等待时机，诚信前行。",
    "天水讼": "有孚窒惕，中吉终凶，利见大人，不利涉大川。争讼宜和解。",
    "地水师": "贞，丈人吉，无咎。师出有名，正道行军。",
    "水地比": "吉，原筮元永贞，无咎。不宁方来，后夫凶。亲比和睦。",
    "风天小畜": "亨，密云不雨，自我西郊。积蓄力量，等待时机。",
    "天泽履": "履虎尾，不咥人，亨。谨慎行事，化险为夷。",
    "地天泰": "小往大来，吉亨。天地交泰，万物通达。",
    "天地否": "否之匪人，不利君子贞，大往小来。闭塞不通，守正待变。",
    "天火同人": "同人于野，亨，利涉大川，利君子贞。志同道合，共事大业。",
    "火天大有": "元亨。光明正大，丰盛有余。",
    "地山谦": "亨，君子有终。谦逊自处，功成不居。",
    "雷地豫": "利建侯行师。顺应天道，安乐祥和。",
    "泽雷随": "元亨利贞，无咎。随时应变，顺势而为。",
    "山风蛊": "元亨，利涉大川。先甲三日，后甲三日。整治革新。",
    "地泽临": "元亨利贞，至于八月有凶。亲临视察，恩泽下施。",
    "风地观": "盥而不荐，有孚颙若。观察审视，以正示人。",
    "火雷噬嗑": "亨，利用狱。明察秋毫，执法公正。",
    "山火贲": "亨，小利有攸往。文饰装饰，适度为美。",
    "山地剥": "不利有攸往。剥落衰退，顺守为吉。",
    "地雷复": "亨，出入无疾，朋来无咎。七日来复，天行也。阳气复生。",
    "天雷无妄": "元亨利贞，其匪正有眚，不利有攸往。无妄行事，顺应天道。",
    "山天大畜": "利贞，不家食吉，利涉大川。大有蓄积，施展抱负。",
    "山雷颐": "贞吉，观颐，自求口实。养生养德，慎言节食。",
    "泽风大过": "栋桡，利有攸往，亨。非常时期，果断行动。",
    "坎为水": "习坎，有孚，维心亨，行有尚。重重险难，诚信化险。",
    "离为火": "利贞，亨，畜牝牛吉。光明附丽，柔顺正道。",
    "泽山咸": "亨利贞，取女吉。感应交融，阴阳和合。",
    "雷风恒": "亨，无咎利贞，利有攸往。恒久不变，持之以恒。",
    "天山遁": "亨，小利贞。适时退隐，明哲保身。",
    "雷天大壮": "利贞。壮盛有力，守正为要。",
    "火地晋": "康侯用锡马蕃庶，昼日三接。光明上升，前程似锦。",
    "地火明夷": "利艰贞。光明受损，韬光养晦。",
    "风火家人": "利女贞。齐家之道，正位内外。",
    "火泽睽": "小事吉。异中求同，殊途同归。",
    "水山蹇": "利西南，不利东北，利见大人，贞吉。步履艰难，择路而行。",
    "雷水解": "利西南，无所往，其来复吉。解除险难，春回大地。",
    "山泽损": "有孚，元吉无咎，可贞，利有攸往。减损有度，损下益上。",
    "风雷益": "利有攸往，利涉大川。增益发展，积极进取。",
    "泽天夬": "扬于王庭，孚号有厉，告自邑，不利即戎，利有攸往。果断决断。",
    "天风姤": "女壮，勿用取女。不期而遇，观察对待。",
    "泽地萃": "亨，王假有庙，利见大人，亨利贞。聚合团结。",
    "地风升": "元亨，用见大人，勿恤，南征吉。上升发展，积极向上。",
    "泽水困": "亨，贞大人吉，无咎，有言不信。困境中守正。",
    "水风井": "改邑不改井，无丧无得，往来井井。井养不穷，泽被万物。",
    "泽火革": "己日乃孚，元亨利贞，悔亡。变革更新，顺天应人。",
    "火风鼎": "元吉，亨。鼎新革故，烹饪文明。",
    "震为雷": "亨，震来虩虩，笑言哑哑。震惊百里，不丧匕鬯。",
    "艮为山": "艮其背，不获其身，行其庭，不见其人，无咎。止于所当止。",
    "风山渐": "女归吉，利贞。循序渐进，水到渠成。",
    "雷泽归妹": "征凶，无攸利。婚嫁之道，明察慎行。",
    "雷火丰": "亨，王假之，勿忧宜日中。盛大丰足，居安思危。",
    "火山旅": "小亨，旅贞吉。旅途在外，谦和审慎。",
    "巽为风": "小亨，利有攸往，利见大人。顺从柔和，深入渐进。",
    "兑为泽": "亨利贞。和悦交流，以正为本。",
    "风水涣": "亨，王假有庙，利涉大川，利贞。涣散重聚，团结一心。",
    "水泽节": "亨，苦节不可贞。节制有度，过犹不及。",
    "风泽中孚": "豚鱼吉，利涉大川，利贞。诚信感物，中正和平。",
    "雷山小过": "亨利贞，可小事，不可大事。飞鸟遗之音，不宜上宜下，大吉。",
    "水火既济": "亨小利贞，初吉终乱。功成之后，警惕衰退。",
    "火水未济": "亨，小狐汔济，濡其尾，无攸利。未完成之态，持续努力。",
}

# 六亲 (以日干五行为基准)
LIUQIN_MAP = {
    # (日干五行, 爻位五行) → 六亲
    ("金", "金"): "兄弟",
    ("金", "木"): "妻财",
    ("金", "水"): "子孙",
    ("金", "火"): "官鬼",
    ("金", "土"): "父母",
    ("木", "木"): "兄弟",
    ("木", "土"): "妻财",
    ("木", "火"): "子孙",
    ("木", "金"): "官鬼",
    ("木", "水"): "父母",
    ("水", "水"): "兄弟",
    ("水", "火"): "妻财",
    ("水", "木"): "子孙",
    ("水", "土"): "官鬼",
    ("水", "金"): "父母",
    ("火", "火"): "兄弟",
    ("火", "金"): "妻财",
    ("火", "土"): "子孙",
    ("火", "水"): "官鬼",
    ("火", "木"): "父母",
    ("土", "土"): "兄弟",
    ("土", "水"): "妻财",
    ("土", "金"): "子孙",
    ("土", "木"): "官鬼",
    ("土", "火"): "父母",
}

# 六兽
LIU_SHOU = ["青龙", "朱雀", "勾陈", "螣蛇", "白虎", "玄武"]

# 地支五行
DIZHI_WUXING = {
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

DIZHI_LIST = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
TIANGAN_LIST = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
EARTHLY_BRANCH_NUM = {name: index + 1 for index, name in enumerate(DIZHI_LIST)}


# ============================================================
# 起卦方法
# ============================================================


def _dayan_one_change(yarrow_count: int, rng=None) -> int:
    """大衍之数一变"""
    rng = rng or random
    left = rng.randint(1, yarrow_count - 1)
    right = yarrow_count - left
    # 挂一
    right -= 1
    # 揲四归奇
    left_remainder = left % 4 or 4
    right_remainder = right % 4 or 4
    removed = 1 + left_remainder + right_remainder
    return yarrow_count - removed


def dayan_one_yao(rng=None) -> int:
    """大衍之数起一爻，按传统 1:5:7:3 概率返回 6/7/8/9。

    直接抽取等价离散分布，避免把“随机选一个分堆位置”误当成人工分蓍，
    后者会悄悄扭曲老阳概率。
    """
    rng = rng or random
    draw = rng.randrange(16)
    if draw == 0:
        return 6
    if draw <= 5:
        return 7
    if draw <= 12:
        return 8
    return 9


def qigua_dayan(rng=None) -> list:
    """大衍之数起卦 → 返回6爻列表 [初爻, ..., 上爻]"""
    return [dayan_one_yao(rng) for _ in range(6)]


def qigua_time(dt: datetime | None = None) -> list:
    """时间起卦（梅花易数）→ 返回6爻列表"""
    if dt is None:
        dt = datetime.now()
    if not 1900 <= dt.year <= 2100:
        raise ValueError("时间起卦年份必须在 1900-2100 之间")

    # 梅花易数时间起卦采用农历年月日与地支序数（子=1 ... 亥=12）。
    # 输入仍是公历时间，先用 lunar-python 转换，避免把公历月日直接代入。
    from lunar_python import Solar

    lunar = Solar.fromYmdHms(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second).getLunar()
    year_num = EARTHLY_BRANCH_NUM[lunar.getYearZhi()]
    month = abs(lunar.getMonth())
    day = lunar.getDay()
    hour_num = ((dt.hour + 1) // 2) % 12 + 1

    # 上卦 = (年+月+日) % 8
    upper_num = (year_num + month + day) % 8 or 8
    # 下卦 = (年+月+日+时) % 8
    lower_num = (year_num + month + day + hour_num) % 8 or 8
    # 变爻 = (年+月+日+时) % 6
    change_yao = (year_num + month + day + hour_num) % 6 or 6

    # 数字→八卦（先天八卦数：乾1兑2离3震4巽5坎6艮7坤8）
    xiantian_map = {1: "乾", 2: "兑", 3: "离", 4: "震", 5: "巽", 6: "坎", 7: "艮", 8: "坤"}
    upper_gua = xiantian_map[upper_num]
    lower_gua = xiantian_map[lower_num]

    # 组装6爻 (7=少阳, 8=少阴)
    lines = list(BAGUA[lower_gua]["lines"]) + list(BAGUA[upper_gua]["lines"])
    yao_list = [7 if l == 1 else 8 for l in lines]

    # 设置变爻 (变阳为老阳9, 变阴为老阴6)
    idx = change_yao - 1
    yao_list[idx] = 9 if yao_list[idx] in (7, 9) else 6

    return yao_list


def qigua_manual(input_str: str) -> list:
    """手动输入卦象（6位数字，每位6-9）"""
    normalized = input_str.strip()
    if not re.fullmatch(r"[6789]{6}", normalized):
        raise ValueError(f"需要恰好6位数字且每位为6-9: {input_str}")
    return [int(c) for c in normalized]


# ============================================================
# 解卦
# ============================================================


def _lines_to_trigram(lines: tuple) -> str:
    """三爻组合 → 卦名"""
    return LINES_TO_GUA.get(lines, "未知")


def _yao_to_line(yao: int) -> int:
    """爻数 → 阴阳 (1=阳, 0=阴)"""
    return 1 if yao in (7, 9) else 0


def _yao_is_changing(yao: int) -> bool:
    """是否变爻"""
    return yao in (6, 9)


def interpret(yao_list: list, question: str = "") -> dict:
    """
    解卦

    Args:
        yao_list: 6个数字 [初爻, 二爻, ..., 上爻]，每个为 6/7/8/9
        question: 占问事项

    Returns:
        结构化JSON
    """
    if len(yao_list) != 6 or any(type(y) is not int or y not in (6, 7, 8, 9) for y in yao_list):
        raise ValueError("yao_list 必须包含恰好6个整数，每个值为6、7、8或9")

    # 本卦
    ben_lines = tuple(_yao_to_line(y) for y in yao_list)
    lower_tri = _lines_to_trigram(ben_lines[:3])
    upper_tri = _lines_to_trigram(ben_lines[3:])

    ben_key = (upper_tri, lower_tri)
    ben_name, ben_num = HEXAGRAMS.get(ben_key, ("未知卦", 0))
    ben_ci = GUA_CI.get(ben_name, "")

    # 变爻
    changing_positions = [i + 1 for i, y in enumerate(yao_list) if _yao_is_changing(y)]

    # 变卦
    zhi_lines = tuple(
        (1 - _yao_to_line(y)) if _yao_is_changing(y) else _yao_to_line(y) for y in yao_list
    )
    zhi_lower = _lines_to_trigram(zhi_lines[:3])
    zhi_upper = _lines_to_trigram(zhi_lines[3:])
    zhi_key = (zhi_upper, zhi_lower)
    zhi_name, zhi_num = HEXAGRAMS.get(zhi_key, ("未知卦", 0))
    zhi_ci = GUA_CI.get(zhi_name, "")

    # 互卦 (2,3,4为下卦, 3,4,5为上卦)
    hu_lower = _lines_to_trigram(ben_lines[1:4])
    hu_upper = _lines_to_trigram(ben_lines[2:5])
    hu_key = (hu_upper, hu_lower)
    hu_name, hu_num = HEXAGRAMS.get(hu_key, ("未知卦", 0))

    # 爻位详情
    yao_names = ["初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
    yao_types = {6: "老阴 ⚋×", 7: "少阳 ⚊", 8: "少阴 ⚋", 9: "老阳 ⚊○"}
    yao_details = []
    for i, y in enumerate(yao_list):
        yao_details.append(
            {
                "position": yao_names[i],
                "value": y,
                "type": yao_types.get(y, ""),
                "yinyang": "阳" if y in (7, 9) else "阴",
                "is_changing": _yao_is_changing(y),
            }
        )

    # 断卦指导（根据变爻数量）
    change_count = len(changing_positions)
    if change_count == 0:
        guidance = "六爻不变，以本卦卦辞断。卦象稳定，事态清晰。"
    elif change_count == 1:
        guidance = f"一爻变，以本卦变爻爻辞断。关注第{changing_positions[0]}爻。"
    elif change_count == 2:
        guidance = "两爻变，以本卦两变爻爻辞断，以上爻为主。"
    elif change_count == 3:
        guidance = "三爻变，以本卦和变卦卦辞合参，本卦为体，变卦为用。"
    elif change_count == 4:
        guidance = "四爻变，以变卦中两不变爻爻辞断。"
    elif change_count == 5:
        guidance = "五爻变，以变卦中不变爻爻辞断。"
    else:
        guidance = "六爻全变，乾坤以用九用六断，余卦以变卦卦辞断。"

    result = {
        "question": question,
        "yao_list": yao_list,
        "ben_gua": {
            "name": ben_name,
            "number": ben_num,
            "upper": upper_tri,
            "lower": lower_tri,
            "upper_symbol": BAGUA[upper_tri]["symbol"],
            "lower_symbol": BAGUA[lower_tri]["symbol"],
            "gua_ci": ben_ci,
        },
        "zhi_gua": {
            "name": zhi_name,
            "number": zhi_num,
            "upper": zhi_upper,
            "lower": zhi_lower,
            "gua_ci": zhi_ci,
        },
        "hu_gua": {
            "name": hu_name,
            "number": hu_num,
        },
        "changing": {
            "positions": changing_positions,
            "count": change_count,
        },
        "yao_details": yao_details,
        "guidance": guidance,
    }

    return result


def format_iching_text(data: dict) -> str:
    """格式化六爻结果为可读文本"""
    lines = []
    if data.get("question"):
        lines.append(f"【占问】{data['question']}")
        lines.append("")

    ben = data["ben_gua"]
    zhi = data["zhi_gua"]
    lines.append(f"【本卦】{ben['name']} (第{ben['number']}卦)")
    lines.append(
        f"  上{ben['upper']}({ben['upper_symbol']}) 下{ben['lower']}({ben['lower_symbol']})"
    )
    lines.append(f"  卦辞: {ben['gua_ci']}")
    lines.append("")

    # 画卦
    yao_names = ["初", "二", "三", "四", "五", "上"]
    for i in range(5, -1, -1):
        yd = data["yao_details"][i]
        mark = " ×" if yd["value"] == 6 else " ○" if yd["value"] == 9 else ""
        bar = "━━━━━━━" if yd["yinyang"] == "阳" else "━━━ ━━━"
        lines.append(f"  {yao_names[i]}爻 {bar}{mark}")
    lines.append("")

    if data["changing"]["count"] > 0:
        lines.append(f"【变卦】{zhi['name']} (第{zhi['number']}卦)")
        lines.append(f"  变爻: {', '.join(f'第{p}爻' for p in data['changing']['positions'])}")
        lines.append(f"  卦辞: {zhi['gua_ci']}")
        lines.append("")

    lines.append(f"【互卦】{data['hu_gua']['name']}")
    lines.append("")
    lines.append(f"【断卦指导】{data['guidance']}")

    return "\n".join(lines)


if __name__ == "__main__":
    for _stream_name in ("stdin", "stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description="周易卦象引擎（不含完整文王纳甲）")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    dayan_parser = subparsers.add_parser("dayan")
    dayan_parser.add_argument("question", nargs="?", default="")
    dayan_parser.add_argument("--seed", type=int)
    time_parser = subparsers.add_parser("time")
    time_parser.add_argument("year", type=int)
    time_parser.add_argument("month", type=int)
    time_parser.add_argument("day", type=int)
    time_parser.add_argument("hour", type=int)
    time_parser.add_argument("question", nargs="?", default="")
    time_parser.add_argument("--minute", type=int, default=0)
    time_parser.add_argument("--second", type=int, default=0)
    manual_parser = subparsers.add_parser("manual")
    manual_parser.add_argument("lines")
    manual_parser.add_argument("question", nargs="?", default="")
    for mode_parser in (dayan_parser, time_parser, manual_parser):
        mode_parser.add_argument("--text", action="store_true")
        mode_parser.add_argument("--question-stdin", action="store_true")
    args = parser.parse_args()
    question = sys.stdin.read(20_001).rstrip("\r\n") if args.question_stdin else args.question
    if args.question_stdin and args.question:
        parser.error("问题不能同时来自位置参数与 --question-stdin")
    if len(question) > 20_000:
        parser.error("问题文本超过 20,000 字符限制")
    try:
        if args.mode == "dayan":
            rng = random.Random(args.seed) if args.seed is not None else None
            yao_list = qigua_dayan(rng)
        elif args.mode == "time":
            dt = datetime(args.year, args.month, args.day, args.hour, args.minute, args.second)
            yao_list = qigua_time(dt)
        else:
            yao_list = qigua_manual(args.lines)
        result = interpret(yao_list, question)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        format_iching_text(result)
        if args.text
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
