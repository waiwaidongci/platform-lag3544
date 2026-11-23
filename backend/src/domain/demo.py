"""澄湾站调频巡检样本，含已知三格滞后和三类采集缺口。"""

from datetime import datetime, timedelta
from random import Random


def demo_rows() -> list[dict]:
    rng = Random(52)
    start = datetime(2026, 11, 21, 9, 30)
    sweep = (31, 44, 36, 49, 39, 28, 46, 34, 42)
    frequency = [sweep[slot // 10] + rng.uniform(-1.2, 1.2) for slot in range(90)]
    rows = []
    for slot, fan_hz in enumerate(frequency):
        sound = 46 + 0.57 * frequency[max(0, slot - 3)] + rng.uniform(-0.7, 0.7)
        if 67 <= slot <= 69:
            continue
        rows.append({
            "platform": "澄湾站下行站台",
            "fan_id": "TVF-02",
            "timestamp": (start + timedelta(seconds=10 * slot)).isoformat(sep=" "),
            "sound_dba": None if 54 <= slot <= 57 else round(sound, 2),
            "fan_hz": None if 32 <= slot <= 34 else round(fan_hz, 2),
        })
    return rows


# 检修后 CH-2 与 CH-3 接反；声级计时钟比站内时钟快 30 秒，真实校时偏移为 +30 秒。
_SWAP_WIRING = {"CH-1": "P1", "CH-2": "P3", "CH-3": "P2", "CH-4": "P4"}
_SWAP_STATION = "澄湾站下行站台"
_SWAP_POINTS = {"P1": "P1 站台东端", "P2": "P2 站台中部", "P3": "P3 站台西端", "P4": "P4 设备区通道"}
_SWAP_TONES = {"P1": (120, 210), "P2": (360, 450), "P3": (600, 690), "P4": (840, 930)}
_SWAP_CLOCK_SKEW = 30
_SWAP_BLANKS = {("CH-3", 410), ("CH-3", 420), ("CH-2", 640)}
_SWAP_GAPS = {("CH-1", 720), ("CH-1", 730), ("CH-1", 740)}


def demo_tone_periods() -> list[dict]:
    base = datetime(2026, 11, 22, 14, 0, 0)
    return [{
        "point": _SWAP_POINTS[point],
        "start": (base + timedelta(seconds=start)).isoformat(sep=" "),
        "end": (base + timedelta(seconds=end)).isoformat(sep=" "),
    } for point, (start, end) in sorted(_SWAP_TONES.items())]


def demo_calibration_rows() -> list[dict]:
    rng = Random(72)
    base = datetime(2026, 11, 22, 14, 0, 0)
    rows = []
    for slot in range(120):
        instant = base + timedelta(seconds=10 * slot)
        for channel, point in sorted(_SWAP_WIRING.items()):
            seconds = 10 * slot
            if (channel, seconds) in _SWAP_GAPS:
                continue
            start, end = _SWAP_TONES[point]
            sounding = start + _SWAP_CLOCK_SKEW <= seconds <= end + _SWAP_CLOCK_SKEW
            level = 95.5 + rng.uniform(-1.5, 1.5) if sounding else 55 + rng.uniform(-3, 3)
            rows.append({
                "station": _SWAP_STATION,
                "channel": channel,
                "timestamp": instant.isoformat(sep=" "),
                "level_dba": None if (channel, seconds) in _SWAP_BLANKS else round(level, 2),
            })
    return rows
