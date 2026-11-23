"""通道接反核查领域逻辑的端到端测试，仅依赖标准库。

运行：PYTHONPATH=/workspace/backend python3 -m unittest tests.test_swap -v
"""

import unittest

from src.domain.demo import demo_calibration_rows, demo_tone_periods
from src.domain.swap import investigate, validate_calibration_rows, validate_tone_periods

PARAMS = {"offset_min_seconds": -120, "offset_max_seconds": 120,
          "offset_step_seconds": 10, "threshold_dba": 85}

EXPECTED_WIRING = {"CH-1": "P1 站台东端", "CH-2": "P3 站台西端", "CH-3": "P2 站台中部", "CH-4": "P4 设备区通道"}


def rows_for(wiring, tones, skew=0, base="2026-11-22 14:00:00"):
    """按真实接线和时钟偏移生成理想化读数：试音期间被接通道 96 dB，其余 55 dB。"""
    from datetime import datetime, timedelta
    start = datetime.fromisoformat(base)
    rows = []
    for slot in range(120):
        seconds = 10 * slot
        stamp = (start + timedelta(seconds=seconds)).isoformat(sep=" ")
        for channel, point in wiring.items():
            lo, hi = tones[point]
            sounding = lo + skew <= seconds <= hi + skew
            rows.append({"station": "测试站", "channel": channel, "timestamp": stamp,
                         "level_dba": 96.0 if sounding else 55.0})
    return rows


def tone_periods(tones, base="2026-11-22 14:00:00"):
    from datetime import datetime, timedelta
    start = datetime.fromisoformat(base)
    return [{"point": point,
             "start": (start + timedelta(seconds=lo)).isoformat(sep=" "),
             "end": (start + timedelta(seconds=hi)).isoformat(sep=" ")}
            for point, (lo, hi) in sorted(tones.items())]


class DemoScenarioTest(unittest.TestCase):
    def test_demo_recovers_swapped_wiring_at_true_offset(self):
        result = investigate(demo_calibration_rows(), demo_tone_periods(), PARAMS)
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["feasible_offsets"], [30])
        self.assertEqual(result["assignments_total"], 1)
        confirmed = {pair["channel"]: pair["point"] for pair in result["confirmed"]}
        self.assertEqual(confirmed, EXPECTED_WIRING)
        self.assertIsNone(result["conflicts"])

    def test_demo_is_deterministic(self):
        first = investigate(demo_calibration_rows(), demo_tone_periods(), PARAMS)
        second = investigate(demo_calibration_rows(), demo_tone_periods(), PARAMS)
        self.assertEqual(first, second)


class ExclusionRuleTest(unittest.TestCase):
    wiring = {"CH-1": "P1", "CH-2": "P2"}
    tones = {"P1": (120, 210), "P2": (360, 450)}

    def investigate(self, rows, periods=None, params=None):
        return investigate(rows, periods or tone_periods(self.tones), params or PARAMS)

    def test_missing_readings_do_not_exclude(self):
        rows = rows_for(self.wiring, self.tones)
        # CH-2 在 P1、CH-1 在 P2 的试音窗口内完全没有读数：缺测不排除，交叉配法依然可行。
        rows = [row for row in rows
                if not (row["channel"] == "CH-2" and "14:02:00" <= row["timestamp"][11:] <= "14:03:30")
                and not (row["channel"] == "CH-1" and "14:06:00" <= row["timestamp"][11:] <= "14:07:30")]
        result = self.investigate(rows)
        self.assertEqual(result["state"], "ok")
        self.assertGreaterEqual(result["assignments_total"], 2)
        wirings = [row["wiring"] for table in result["tables"] if table["title"].startswith("可行配法明细")
                   for row in table["rows"]]
        self.assertTrue(any("CH-2→P1" in wiring for wiring in wirings))

    def test_below_threshold_reading_excludes(self):
        result = self.investigate(rows_for(self.wiring, self.tones))
        self.assertEqual(result["assignments_total"], 1)
        confirmed = {pair["channel"]: pair["point"] for pair in result["confirmed"]}
        self.assertEqual(confirmed, {"CH-1": "P1", "CH-2": "P2"})

    def test_reading_at_threshold_does_not_exclude(self):
        rows = rows_for(self.wiring, self.tones)
        for row in rows:
            if row["level_dba"] == 55.0:
                row["level_dba"] = 85.0  # 等于门槛不算低于门槛
        result = self.investigate(rows)
        self.assertIn(0, result["feasible_offsets"])
        wirings = [row["wiring"] for table in result["tables"] if table["title"].startswith("可行配法明细")
                   for row in table["rows"]]
        self.assertTrue(any("CH-1→P2" in wiring for wiring in wirings))

    def test_shared_offset_across_station(self):
        # 全站共用一档校时偏移：只有偏移 0 可行，偏移 +30 下两路都被排除。
        result = self.investigate(rows_for(self.wiring, self.tones, skew=0))
        self.assertEqual(result["feasible_offsets"], [0])
        shifted = rows_for(self.wiring, self.tones, skew=30)
        result = self.investigate(shifted)
        self.assertEqual(result["feasible_offsets"], [30])

    def test_conflict_lists_channels(self):
        # CH-2 在 P2 试音窗口内读数低于门槛，且 CH-1 已占 P1：无可行配法。
        rows = rows_for(self.wiring, self.tones)
        for row in rows:
            if row["channel"] == "CH-2":
                row["level_dba"] = 55.0
        result = self.investigate(rows)
        self.assertEqual(result["state"], "warning")
        self.assertEqual(result["assignments_total"], 0)
        self.assertIn("CH-2", result["conflicts"]["channels"])
        self.assertEqual(result["confirmed"], [])

    def test_ambiguity_confirms_only_common_wiring(self):
        # CH-2、CH-3 全程缺测：两种配法都可行，只有 CH-1→P1 被共有确认。
        wiring = {"CH-1": "P1", "CH-2": "P2", "CH-3": "P3"}
        tones = {"P1": (120, 210), "P2": (360, 450), "P3": (600, 690)}
        rows = [{**row, "level_dba": None} if row["channel"] != "CH-1" else row
                for row in rows_for(wiring, tones)]
        result = investigate(rows, tone_periods(tones), PARAMS)
        self.assertEqual(result["assignments_total"], 2)
        self.assertEqual(result["confirmed"], [{"channel": "CH-1", "point": "P1"}])


class ValidationTest(unittest.TestCase):
    def test_channel_point_count_must_match(self):
        rows = rows_for({"CH-1": "P1", "CH-2": "P2"}, {"P1": (120, 210), "P2": (360, 450)})
        with self.assertRaisesRegex(ValueError, "一一对应"):
            investigate(rows, tone_periods({"P1": (120, 210)}), PARAMS)

    def test_duplicate_channel_timestamp_rejected(self):
        rows = [{"station": "测试站", "channel": "CH-1", "timestamp": "2026-11-22 14:00:00", "level_dba": 60.0},
                {"station": "测试站", "channel": "CH-1", "timestamp": "2026-11-22 14:00:00", "level_dba": 61.0}]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_calibration_rows(rows)

    def test_mixed_stations_rejected(self):
        rows = [{"station": "甲站", "channel": "CH-1", "timestamp": "2026-11-22 14:00:00", "level_dba": 60.0},
                {"station": "乙站", "channel": "CH-1", "timestamp": "2026-11-22 14:00:10", "level_dba": 60.0}]
        with self.assertRaisesRegex(ValueError, "车站不同"):
            validate_calibration_rows(rows)

    def test_tone_period_must_be_ordered(self):
        with self.assertRaisesRegex(ValueError, "早于结束时间"):
            validate_tone_periods([{"point": "P1", "start": "2026-11-22 14:03:00", "end": "2026-11-22 14:02:00"}])

    def test_offset_candidate_cap(self):
        params = {"offset_min_seconds": -3600, "offset_max_seconds": 3600,
                  "offset_step_seconds": 10, "threshold_dba": 85}
        with self.assertRaisesRegex(ValueError, "121"):
            investigate(rows_for({"CH-1": "P1", "CH-2": "P2"}, {"P1": (120, 210), "P2": (360, 450)}),
                        tone_periods({"P1": (120, 210), "P2": (360, 450)}), params)


if __name__ == "__main__":
    unittest.main()
