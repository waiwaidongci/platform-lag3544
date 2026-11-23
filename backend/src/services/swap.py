import csv
import hashlib
import io
import json
import logging
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.constants.enums import SwapState
from src.domain import swap
from src.models.swap import CalibrationBatch, SwapDetermination, SwapPublication, TonePeriod
from src.services.audit import record
from src.services.datasets import checksum
from src.services.validation import cell
from src.utils.exports import write_named_report
from src.utils.time import iso, now

log = logging.getLogger(__name__)


def parse_calibration(text):
    """解析标定 CSV，字段口径与滞后批次一致，但按通道长表读取。"""
    reader = csv.DictReader(io.StringIO(text.removeprefix('﻿'), newline=''), strict=True)
    fields = swap.CALIBRATION_FIELDS
    keys = {field['key'] for field in fields}
    required = {field['key'] for field in fields if field.get('required', True)}
    rows = []
    try:
        headers = reader.fieldnames or []
        if not required <= set(headers) or not set(headers) <= keys or len(headers) != len(set(headers)):
            raise ValueError('CSV 表头与字段说明不符，请下载模板检查列名')
        for raw in reader:
            if len(rows) >= 20000:
                raise ValueError('一个标定批次最多导入 20000 行')
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise ValueError('工作表的列数与表头不一致')
                rows.append({field['key']: cell(field, raw.get(field['key'])) for field in fields})
            except ValueError as error:
                raise ValueError(f'CSV 第 {reader.line_num} 行 · {error}') from None
    except csv.Error:
        raise ValueError(f'CSV 第 {reader.line_num} 行附近格式不正确') from None
    return swap.validate_calibration_rows(rows)


def normalize_params(params):
    if not isinstance(params, dict):
        raise ValueError('接反核查参数格式无效。')
    fields = swap.SWAP_PARAMS
    if set(params) - {field['key'] for field in fields}:
        raise ValueError('存在未知核查参数，请重新打开工作面板')
    values = {field['key']: cell(field, params.get(field['key'], field['default'])) for field in fields}
    low, high, step = (values[key] for key in ('offset_min_seconds', 'offset_max_seconds', 'offset_step_seconds'))
    if low > high:
        raise ValueError('「校时偏移下限」不能大于上限。')
    if len(range(low, high + 1, step)) > swap.MAX_CANDIDATES:
        raise ValueError(f'候选偏移超过 {swap.MAX_CANDIDATES} 档，请增大步长或收窄范围。')
    return values


def void_unpublished(db, station, actor, reason):
    """数据更新后，未发布的旧判定作废；已发布的判定保留。"""
    states = (SwapState.COMPUTED, SwapState.PUBLISHING)
    items = db.scalars(select(SwapDetermination).where(SwapDetermination.station == station,
                                                       SwapDetermination.state.in_(states))
                       .with_for_update()).all()
    for item in items:
        item.state = SwapState.VOID
    if items:
        record(db, actor, 'swap.voided', station, count=len(items), reason=reason)
    return len(items)


def save_batch(db, name, filename, rows, actor):
    station = rows[0]['station']
    signature = checksum(rows)
    lookup = select(CalibrationBatch).where(CalibrationBatch.name == name,
                                            CalibrationBatch.checksum == signature)
    existing = db.scalar(lookup)
    if existing:
        return existing, False, 0
    channels = sorted({row['channel'] for row in rows})
    item = CalibrationBatch(station=station, name=name, filename=filename, checksum=signature,
                            rows=rows, row_count=len(rows), channels=channels, author=actor)
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(lookup.with_for_update())
        if existing:
            return existing, False, 0
        raise
    voided = void_unpublished(db, station, actor, '新标定批次入库')
    record(db, actor, 'swap.batch_imported', item.id, station=station, rows=item.row_count, voided=voided)
    return item, True, voided


def add_period(db, station, point, start, end, actor):
    """补录一段试音时段；不同测点的并发补录各自成行，都能留住。"""
    tone = swap.validate_tone_periods([{'point': point, 'start': start, 'end': end}])[0]
    lookup = select(TonePeriod).where(TonePeriod.station == station, TonePeriod.point == tone['point'],
                                      TonePeriod.start == tone['start'].isoformat(sep=' '),
                                      TonePeriod.end == tone['end'].isoformat(sep=' '))
    existing = db.scalar(lookup)
    if existing:
        return existing, False, 0
    item = TonePeriod(station=station, point=tone['point'],
                      start=tone['start'].isoformat(sep=' '), end=tone['end'].isoformat(sep=' '), author=actor)
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(lookup.with_for_update())
        if existing:
            return existing, False, 0
        raise
    voided = void_unpublished(db, station, actor, '补录试音时段')
    record(db, actor, 'swap.tone_added', item.id, station=station, point=item.point, voided=voided)
    return item, True, voided


def remove_period(db, period_id, actor):
    item = db.get(TonePeriod, period_id, with_for_update=True)
    if not item:
        return None, 0
    station, point = item.station, item.point
    db.delete(item)
    voided = void_unpublished(db, station, actor, '删除试音时段')
    record(db, actor, 'swap.tone_removed', period_id, station=station, point=point, voided=voided)
    return item, voided


def _fingerprint(batch, periods):
    raw = json.dumps({'batch': batch.checksum,
                      'tones': [(item.point, item.start, item.end) for item in periods]},
                     ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def run_determination(db, station, params, actor):
    """按当前标定批次和试音时段计算一版判定并入库，状态为待发布。"""
    batch = db.scalar(select(CalibrationBatch).where(CalibrationBatch.station == station)
                      .order_by(CalibrationBatch.id.desc()).limit(1))
    if not batch:
        raise ValueError('该车站还没有标定批次，请先导入。')
    periods = db.scalars(select(TonePeriod).where(TonePeriod.station == station)
                         .order_by(TonePeriod.point, TonePeriod.start, TonePeriod.end)).all()
    if not periods:
        raise ValueError('该车站还没有试音时段，请先补录。')
    tones = [{'point': item.point, 'start': item.start, 'end': item.end} for item in periods]
    result = swap.investigate(batch.rows, tones, params)
    fingerprint = _fingerprint(batch, periods)
    for _ in range(3):
        version = db.scalar(select(func.max(SwapDetermination.version))
                            .where(SwapDetermination.station == station)) or 0
        item = SwapDetermination(station=station, version=version + 1, batch_id=batch.id,
                                 tone_fingerprint=fingerprint, params=params, result=result, author=actor)
        try:
            with db.begin_nested():
                db.add(item)
                db.flush()
            break
        except IntegrityError:
            continue
    else:
        raise ValueError('判定版本冲突，请重试')
    record(db, actor, 'swap.computed', item.id, station=station, version=item.version,
           feasible=item.result['assignments_total'])
    return item


def complete_publish(determination_id, actor):
    """把发布中的判定补齐发布；发布记录按判定唯一，重复执行不产生重复记录。"""
    with Session.begin() as db:
        item = db.get(SwapDetermination, determination_id, with_for_update=True)
        if not item:
            return None, None
        publication = db.scalar(select(SwapPublication)
                                .where(SwapPublication.determination_id == determination_id))
        if item.state == SwapState.PUBLISHED:
            return item, publication
        if item.state != SwapState.PUBLISHING:
            return item, None
        if publication is None:
            export = write_named_report(f'swap-handover-{item.id}', item.result)
            publication = SwapPublication(determination_id=item.id, station=item.station, export_file=export,
                                          detail=item.result['headline'][:500], author=actor)
            db.add(publication)
            db.flush()
        item.state = SwapState.PUBLISHED
        item.published_at = now()
        record(db, actor, 'swap.published', item.id, station=item.station, version=item.version)
        return item, publication


def recover_interrupted():
    """恢复发布中断的判定：沿用入库的同一版本补齐发布，不重新计算。"""
    with Session.begin() as db:
        ids = db.scalars(select(SwapDetermination.id)
                         .where(SwapDetermination.state == SwapState.PUBLISHING)).all()
    for determination_id in ids:
        try:
            complete_publish(determination_id, 'recovery')
        except Exception:
            log.exception('Recovery of determination %s failed', determination_id)
    return len(ids)


def handover(db):
    """各车站最新已发布判定的共有接线，供交班页面确认。"""
    published = db.scalars(select(SwapDetermination).where(SwapDetermination.state == SwapState.PUBLISHED)
                           .order_by(SwapDetermination.station, SwapDetermination.version.desc())).all()
    latest = {}
    for item in published:
        latest.setdefault(item.station, item)
    summaries = []
    for station, item in sorted(latest.items()):
        result = item.result
        summaries.append({
            'station': station,
            'determination_id': item.id,
            'version': item.version,
            'published_at': iso(item.published_at),
            'headline': result['headline'],
            'confirmed': result['confirmed'],
            'feasible_offsets': result['feasible_offsets'],
            'assignments_total': result['assignments_total'],
            'conflicts': result['conflicts'],
        })
    return summaries
