"""检修后声级计通道接反核查：候选校时偏移、声级门槛与可行配法枚举。"""

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

MAX_CHANNELS = 8
MAX_CANDIDATES = 121
MAX_MATCHINGS = 500_000
LIST_LIMIT = 100

CALIBRATION_FIELDS = (
    {"key": "station", "label": "车站", "type": "string", "required": True},
    {"key": "channel", "label": "声级计通道", "type": "string", "required": True},
    {"key": "timestamp", "label": "本地采样时间（YYYY-MM-DD HH:MM:SS）", "type": "string", "required": True},
    {"key": "level_dba", "label": "通道声级（dB(A)）", "type": "number", "required": False, "min": 0, "max": 150},
)

SWAP_PARAMS = (
    {"key": "offset_min_seconds", "label": "校时偏移下限（秒）", "type": "int", "required": True,
     "min": -3600, "max": 3600, "default": -120,
     "help": "试音时段整体平移的下界，负值表示试音记录早于通道读数。"},
    {"key": "offset_max_seconds", "label": "校时偏移上限（秒）", "type": "int", "required": True,
     "min": -3600, "max": 3600, "default": 120,
     "help": "校时偏移的上界，与下限、步长共同组成候选偏移。"},
    {"key": "offset_step_seconds", "label": "偏移步长（秒）", "type": "int", "required": True,
     "min": 1, "max": 600, "default": 10,
     "help": "相邻候选偏移的间隔，候选总数不超过 121 档。"},
    {"key": "threshold_dba", "label": "声级门槛（dB(A)）", "type": "number", "required": True,
     "min": 30, "max": 140, "default": 85,
     "help": "试音时段内低于门槛的读数排除对应接线，缺测不排除。"},
)


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("请填写本地时间 YYYY-MM-DD HH:MM:SS") from None
    if result.isoformat(sep=" ") != value.replace("T", " ") or result.tzinfo is not None:
        raise ValueError("请填写本地时间 YYYY-MM-DD HH:MM:SS，精确到整秒")
    return result


def validate_calibration_rows(rows):
    """与 CSV 导入共用校验，返回可序列化且按时间排序的标定读数。"""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("请导入至少一条标定读数。")
    readings = []
    seen = set()
    station = None
    for index, row in enumerate(rows, 1):
        context = f"第 {index} 条标定读数"
        if not isinstance(row, dict):
            raise ValueError(f"{context}格式无效。")
        record = {}
        for field in CALIBRATION_FIELDS:
            key, label = field["key"], field["label"]
            value = row.get(key)
            if field["type"] == "string":
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 300:
                    raise ValueError(f"{context}的「{label}」须为 1 至 300 个字符。")
                value = value.strip()
            elif value is not None and (
                type(value) not in (int, float) or not field["min"] <= value <= field["max"]
            ):
                raise ValueError(f"{context}的「{label}」须为 {field['min']} 至 {field['max']} 的数值或留空。")
            record[key] = value
        try:
            instant = _timestamp(record["timestamp"])
        except ValueError as error:
            raise ValueError(f"{context}时间无效。{error}。") from None
        record["timestamp"] = instant.isoformat(sep=" ")
        key = (record["channel"], instant)
        if key in seen:
            raise ValueError(f"{context}的通道 {record['channel']} 在 {record['timestamp']} 重复，请保留每个时刻唯一的一行。")
        seen.add(key)
        if station is None:
            station = record["station"]
        if record["station"] != station:
            raise ValueError(f"{context}与首条记录的车站不同，请按车站拆分标定批次。")
        readings.append(record)
    channels = {record["channel"] for record in readings}
    if len(channels) > MAX_CHANNELS:
        raise ValueError(f"一个标定批次最多 {MAX_CHANNELS} 条通道，当前 {len(channels)} 条，请分批核对。")
    return sorted(readings, key=lambda record: (record["timestamp"], record["channel"]))


def validate_tone_periods(periods):
    """校验试音时段，返回按测点和开始时间排序的列表，完全相同的时段只留一段。"""
    if not isinstance(periods, (list, tuple)) or not periods:
        raise ValueError("请先录入各测点的试音时段。")
    tones = []
    seen = set()
    for index, item in enumerate(periods, 1):
        context = f"第 {index} 段试音时段"
        if not isinstance(item, dict):
            raise ValueError(f"{context}格式无效。")
        point = item.get("point")
        if not isinstance(point, str) or not point.strip() or len(point.strip()) > 120:
            raise ValueError(f"{context}的「测点」须为 1 至 120 个字符。")
        point = point.strip()
        try:
            start = _timestamp(item.get("start"))
            end = _timestamp(item.get("end"))
        except ValueError as error:
            raise ValueError(f"{context}时间无效。{error}。") from None
        if not start < end:
            raise ValueError(f"{context}的开始时间须早于结束时间。")
        if end - start > timedelta(hours=2):
            raise ValueError(f"{context}超过 2 小时，请拆分为多段试音。")
        key = (point, start, end)
        if key in seen:
            continue
        seen.add(key)
        tones.append({"point": point, "start": start, "end": end})
    return sorted(tones, key=lambda tone: (tone["point"], tone["start"], tone["end"]))


def _parameters(params):
    if not isinstance(params, dict):
        raise ValueError("接反核查参数格式无效。")
    values = {}
    for field in SWAP_PARAMS:
        key = field["key"]
        value = params.get(key, field["default"])
        if field["type"] == "int":
            if type(value) is not int or not field["min"] <= value <= field["max"]:
                raise ValueError(f"「{field['label']}」须为 {field['min']} 至 {field['max']} 的整数。")
        elif type(value) not in (int, float) or isinstance(value, bool) or not field["min"] <= value <= field["max"]:
            raise ValueError(f"「{field['label']}」须为 {field['min']} 至 {field['max']} 的数值。")
        values[key] = value
    low, high, step = (values[key] for key in ("offset_min_seconds", "offset_max_seconds", "offset_step_seconds"))
    if low > high:
        raise ValueError("「校时偏移下限」不能大于上限。")
    if len(range(low, high + 1, step)) > MAX_CANDIDATES:
        raise ValueError(f"候选偏移超过 {MAX_CANDIDATES} 档，请增大步长或收窄范围。")
    return values


def _pair_stats(readings, windows, channels, points, offset, threshold):
    """逐通道逐测点统计：窗口内低于门槛的最早读数、达到门槛的读数数和窗口读数总数。"""
    allowed, support, offending, covered = {}, {}, {}, {}
    for channel in channels:
        stamps = [stamp for stamp, _ in readings[channel]]
        for point in points:
            low = None
            hits = total = 0
            for start, end in windows[point]:
                first = bisect_left(stamps, start + offset)
                last = bisect_right(stamps, end + offset)
                for stamp, level in readings[channel][first:last]:
                    total += 1
                    if level < threshold:
                        if low is None:
                            low = (stamp, level)
                    else:
                        hits += 1
            allowed[channel, point] = low is None
            support[channel, point] = hits
            offending[channel, point] = low
            covered[channel, point] = total
    return allowed, support, offending, covered


def _matchings(channels, points, allowed):
    """回溯枚举通道到测点的一一对应，通道和测点均按名称顺序，结果确定。"""
    found = []

    def visit(index, used, current):
        if index == len(channels):
            found.append(tuple(current))
            return
        channel = channels[index]
        for point in points:
            if point not in used and allowed[channel, point]:
                current.append(point)
                visit(index + 1, used | {point}, current)
                current.pop()

    visit(0, set(), [])
    return found


def _max_matching(channels, points, allowed):
    """确定性增广路最大匹配，用于无可行配法时定位冲突通道。"""
    match = {}

    def augment(channel, seen):
        for point in points:
            if allowed[channel, point] and point not in seen:
                seen.add(point)
                if point not in match or augment(match[point], seen):
                    match[point] = channel
                    return True
        return False

    for channel in channels:
        augment(channel, set())
    return match


def _table(title, columns, rows):
    return {"title": title, "columns": [{"key": key, "label": label} for key, label in columns], "rows": rows}


def investigate(rows, periods, params):
    """枚举候选校时偏移下的可行配法，给出共有接线和冲突通道。"""
    readings = validate_calibration_rows(rows)
    tones = validate_tone_periods(periods)
    options = _parameters(params)
    threshold = options["threshold_dba"]
    channels = sorted({record["channel"] for record in readings})
    points = sorted({tone["point"] for tone in tones})
    if len(channels) != len(points):
        raise ValueError(
            f"通道（{len(channels)} 条）与测点（{len(points)} 个）须一一对应，请补齐试音时段或核对标定批次。")
    if not 2 <= len(channels) <= MAX_CHANNELS:
        raise ValueError(f"通道与测点须为 2 至 {MAX_CHANNELS} 个，当前 {len(channels)} 个。")
    by_channel = {
        channel: sorted(
            (datetime.fromisoformat(record["timestamp"]), record["level_dba"])
            for record in readings
            if record["channel"] == channel and record["level_dba"] is not None
        )
        for channel in channels
    }
    windows = {point: [(tone["start"], tone["end"]) for tone in tones if tone["point"] == point] for point in points}
    low, high, step = (options[key] for key in ("offset_min_seconds", "offset_max_seconds", "offset_step_seconds"))
    offsets = list(range(low, high + 1, step))

    stats = {}
    matching_cache = {}
    materialized = 0
    for offset in offsets:
        allowed, support, offending, covered = _pair_stats(by_channel, windows, channels, points,
                                                           timedelta(seconds=offset), threshold)
        key = tuple(tuple(allowed[channel, point] for point in points) for channel in channels)
        if key not in matching_cache:
            matching_cache[key] = _matchings(channels, points, allowed)
            materialized += len(matching_cache[key])
            if materialized > MAX_MATCHINGS:
                raise ValueError("可行配法数量过大，请收窄候选偏移范围或补充试音时段后重试。")
        stats[offset] = {
            "allowed": allowed, "support": support, "offending": offending, "covered": covered,
            "matchings": matching_cache[key],
            "excluded": sum(not allowed[channel, point] for channel in channels for point in points),
        }

    feasible_offsets = [offset for offset in offsets if stats[offset]["matchings"]]
    total = sum(len(stats[offset]["matchings"]) for offset in feasible_offsets)
    common = None
    listed = []
    for offset in feasible_offsets:
        for matching in stats[offset]["matchings"]:
            pairs = frozenset(zip(channels, matching))
            common = pairs if common is None else common & pairs
            if len(listed) < LIST_LIMIT:
                listed.append((offset, matching))
    common = common or set()

    def representative():
        return max(feasible_offsets, key=lambda offset: (len(stats[offset]["matchings"]), -abs(offset), -offset))

    def conflict_offset():
        def rank(offset):
            allowed = stats[offset]["allowed"]
            size = len(_max_matching(channels, points, allowed))
            return size, -stats[offset]["excluded"], -abs(offset), -offset
        return max(offsets, key=rank)

    focus = representative() if feasible_offsets else conflict_offset()
    focus_stats = stats[focus]
    confirmed = sorted(common)
    conflict_channels = []
    evidence = []
    if not feasible_offsets:
        allowed = focus_stats["allowed"]
        match = _max_matching(channels, points, allowed)
        matched_channels = set(match.values())
        conflict_channels = [channel for channel in channels
                             if channel not in matched_channels or not any(allowed[channel, point] for point in points)]
        for channel in channels:
            for point in points:
                low = focus_stats["offending"][channel, point]
                if low is not None and len(evidence) < 60:
                    stamp, level = low
                    evidence.append({"channel": channel, "point": point, "timestamp": stamp.isoformat(sep=" "),
                                     "level_dba": level, "threshold_dba": threshold})

    count = len(channels)
    if not feasible_offsets:
        state = "warning"
        headline = f"所有候选偏移下均无可行配法，冲突通道：{'、'.join(conflict_channels)}。"
        action = "按冲突通道核对现场接线与标定记录，修正或补录试音时段后重新判定。"
    elif len(confirmed) == count:
        state = "ok"
        headline = f"{count} 条通道接线全部确认，可行校时偏移 {len(feasible_offsets)} 档。"
        action = "全部接线在可行配法中一致，可发布到交班页面；发布前如更新数据，本判定将作废。"
    else:
        state = "ok"
        headline = f"共 {total} 种可行配法，{count} 对中 {len(confirmed)} 对接线可确认。"
        action = "对未确认的通道补录试音时段或收窄候选偏移后重新判定，交班页面只确认共有接线。"

    offset_rows = [{
        "offset_seconds": offset,
        "excluded_pairs": stats[offset]["excluded"],
        "feasible_assignments": len(stats[offset]["matchings"]),
        "verdict": "可行" if stats[offset]["matchings"] else "无可行配法",
    } for offset in offsets]
    confirmed_rows = [{
        "channel": channel,
        "point": point,
        "support_readings": focus_stats["support"][channel, point],
    } for channel, point in confirmed]
    assignment_rows = [{
        "assignment": index,
        "offset_seconds": offset,
        "wiring": "、".join(f"{channel}→{point}" for channel, point in zip(channels, matching)),
        "support_readings": sum(stats[offset]["support"][channel, point] for channel, point in zip(channels, matching)),
    } for index, (offset, matching) in enumerate(listed, 1)]
    matrix_rows = [{
        "channel": channel,
        "point": point,
        "window_readings": focus_stats["covered"][channel, point],
        "support_readings": focus_stats["support"][channel, point],
        "verdict": ("排除" if not focus_stats["allowed"][channel, point]
                    else "缺测不排除" if focus_stats["covered"][channel, point] == 0 else "可配"),
    } for channel in channels for point in points]

    tables = [
        _table("候选偏移逐档结果", (
            ("offset_seconds", "校时偏移（秒）"), ("excluded_pairs", "排除配对"),
            ("feasible_assignments", "可行配法"), ("verdict", "结论"),
        ), offset_rows),
        _table(f"代表偏移 {focus:+d} 秒的通道×测点核对", (
            ("channel", "通道"), ("point", "测点"), ("window_readings", "窗口读数"),
            ("support_readings", "达标读数"), ("verdict", "配对结论"),
        ), matrix_rows),
    ]
    if confirmed_rows:
        tables.insert(0, _table("确认接线（所有可行配法共有）", (
            ("channel", "通道"), ("point", "测点"), ("support_readings", "达标读数"),
        ), confirmed_rows))
    if assignment_rows:
        tables.append(_table(f"可行配法明细（共 {total} 种，列出前 {len(listed)} 种）", (
            ("assignment", "序号"), ("offset_seconds", "校时偏移（秒）"),
            ("wiring", "通道→测点"), ("support_readings", "达标读数合计"),
        ), assignment_rows))
    if conflict_channels:
        tables.append(_table(f"冲突通道（偏移 {focus:+d} 秒处最大匹配）", (
            ("channel", "通道"),
            ("reason", "说明"),
        ), [{"channel": channel,
             "reason": ("该通道在此偏移下无可配测点"
                        if not any(focus_stats["allowed"][channel, point] for point in points)
                        else "最大匹配后仍未配上测点")}
            for channel in conflict_channels]))
        tables.append(_table("排除证据（低于门槛的最早读数）", (
            ("channel", "通道"), ("point", "测点"), ("timestamp", "读数时刻"),
            ("level_dba", "读数（dB(A)）"), ("threshold_dba", "门槛（dB(A)）"),
        ), evidence))

    station = readings[0]["station"]
    return {
        "state": state,
        "headline": headline,
        "note": (
            f"{station}，标定读数 {len(readings)} 行，试音时段 {len(tones)} 段。"
            f"候选偏移 {low} 至 {high} 秒、步长 {step} 秒，门槛 {threshold} dB(A)。"
            "整站配法共用一档校时偏移，通道与测点一一对应；试音时段内读数低于门槛才排除，缺测不排除。"
        ),
        "metrics": [
            {"label": "可行配法（种）", "value": total,
             "detail": f"列出前 {len(listed)} 种" if total > len(listed) else "全部列出"},
            {"label": "可行候选偏移（档）", "value": len(feasible_offsets), "detail": f"共扫描 {len(offsets)} 档"},
            {"label": "确认接线（对）", "value": len(confirmed), "detail": f"通道与测点各 {count} 个，一一对应"},
            {"label": "声级门槛（dB(A)）", "value": threshold, "detail": "试音时段内低于门槛的读数才排除"},
            {"label": "标定读数（行）", "value": len(readings), "detail": f"{count} 条通道"},
            {"label": "试音时段（段）", "value": len(tones), "detail": f"{count} 个测点"},
        ],
        "feasible_offsets": feasible_offsets,
        "confirmed": [{"channel": channel, "point": point} for channel, point in confirmed],
        "assignments_total": total,
        "conflicts": ({"offset_seconds": focus, "channels": conflict_channels} if conflict_channels else None),
        "tables": tables,
        "charts": [
            {"title": "各候选偏移的可行配法数", "kind": "bar", "series": [
                {"label": f"{offset:+d} 秒", "value": len(stats[offset]["matchings"])} for offset in offsets
            ]},
        ],
        "sections": [
            {"title": "现场复核", "text": action},
            {"title": "交班口径", "text": (
                "交班页面只确认所有可行配法共有的接线；判定未发布前，导入新标定批次或补录试音时段都会使其作废；"
                "发布中断时按同一版本恢复，重复发布不会产生重复记录。"
            )},
        ],
    }
