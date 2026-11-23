import csv
import io
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.config.settings import ARTIFACTS
from src.constants.enums import Role, SwapState
from src.controllers.auth import allow, current
from src.domain.demo import demo_calibration_rows
from src.domain.spec import SPEC
from src.domain.swap import CALIBRATION_FIELDS
from src.models.identity import User
from src.models.swap import CalibrationBatch, SwapDetermination, SwapPublication, TonePeriod
from src.schemas.requests import DeterminationRequest, TonePeriodRequest, Upload
from src.services import swap
from src.services.audit import record
from src.utils import views

router = APIRouter(prefix='/swap')


@router.get('/template')
def template(actor: User = Depends(current)):
    fields = [field['key'] for field in CALIBRATION_FIELDS]
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(demo_calibration_rows())
    filename = quote(SPEC['swap']['sample_name'])
    return Response('﻿' + buffer.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"})


@router.get('/batches')
def batches(db: Session = Depends(connection), actor: User = Depends(current)):
    return [views.swap_batch(item) for item in
            db.scalars(select(CalibrationBatch).order_by(CalibrationBatch.id.desc()).limit(100))]


@router.get('/batches/{batch_id}')
def batch_details(batch_id: int, offset: int = Query(0, ge=0), limit: int = Query(16, ge=1, le=100),
                  db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(CalibrationBatch, batch_id)
    if not item:
        raise HTTPException(404, '找不到该标定批次')
    return {**views.swap_batch(item), 'rows': item.rows[offset:offset + limit]}


@router.post('/batches', status_code=201)
def upload(body: Upload, db: Session = Depends(connection),
           actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    rows = swap.parse_calibration(body.csv_text)
    item, created, voided = swap.save_batch(db, body.name, body.filename, rows, actor.username)
    db.commit()
    return {**views.swap_batch(item), 'created': created, 'voided': voided}


@router.get('/tone-periods')
def tone_periods(station: str = Query(''), db: Session = Depends(connection), actor: User = Depends(current)):
    query = select(TonePeriod).order_by(TonePeriod.station, TonePeriod.point, TonePeriod.start, TonePeriod.end)
    if station:
        query = query.where(TonePeriod.station == station)
    return [views.tone_period(item) for item in db.scalars(query.limit(500))]


@router.post('/tone-periods', status_code=201)
def add_tone_period(body: TonePeriodRequest, db: Session = Depends(connection),
                    actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    item, created, voided = swap.add_period(db, body.station, body.point, body.start, body.end, actor.username)
    db.commit()
    return {**views.tone_period(item), 'created': created, 'voided': voided}


@router.post('/tone-periods/{period_id}/delete')
def delete_tone_period(period_id: int, db: Session = Depends(connection),
                       actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    item, voided = swap.remove_period(db, period_id, actor.username)
    if not item:
        raise HTTPException(404, '找不到该试音时段')
    db.commit()
    return {'deleted': period_id, 'voided': voided}


@router.get('/determinations')
def determinations(station: str = Query(''), db: Session = Depends(connection), actor: User = Depends(current)):
    query = select(SwapDetermination).order_by(SwapDetermination.id.desc())
    if station:
        query = query.where(SwapDetermination.station == station)
    return [views.determination(item) for item in db.scalars(query.limit(100))]


@router.get('/determinations/{determination_id}')
def determination_details(determination_id: int, db: Session = Depends(connection),
                          actor: User = Depends(current)):
    item = db.get(SwapDetermination, determination_id)
    if not item:
        raise HTTPException(404, '找不到该判定记录')
    publication = db.scalar(select(SwapPublication)
                            .where(SwapPublication.determination_id == determination_id))
    return {**views.determination(item, detail=True),
            'publication': views.publication(publication) if publication else None}


@router.post('/determinations', status_code=201)
def determine(body: DeterminationRequest, db: Session = Depends(connection),
              actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    params = swap.normalize_params(body.params)
    item = swap.run_determination(db, body.station, params, actor.username)
    db.commit()
    return views.determination(item, detail=True)


@router.post('/determinations/{determination_id}/publish')
def publish(determination_id: int, db: Session = Depends(connection),
            actor: User = Depends(allow(Role.ADMIN))):
    item = db.get(SwapDetermination, determination_id, with_for_update=True)
    if not item:
        raise HTTPException(404, '找不到该判定记录')
    if item.state == SwapState.VOID:
        raise HTTPException(409, '该判定已因数据更新作废，请重新判定')
    if item.state == SwapState.COMPUTED:
        item.state = SwapState.PUBLISHING
        record(db, actor.username, 'swap.publishing', item.id, station=item.station, version=item.version)
        db.commit()
    else:
        db.commit()
    item, publication = swap.complete_publish(determination_id, actor.username)
    if publication is None:
        raise HTTPException(409, '该判定状态已变化，请刷新后重试')
    return views.publication(publication)


@router.get('/determinations/{determination_id}/export')
def export(determination_id: int, db: Session = Depends(connection), actor: User = Depends(current)):
    item = db.get(SwapDetermination, determination_id)
    if not item:
        raise HTTPException(404, '找不到该判定记录')
    publication = db.scalar(select(SwapPublication)
                            .where(SwapPublication.determination_id == determination_id))
    if not publication or not publication.export_file:
        raise HTTPException(409, '此判定尚未发布，无可下载结果')
    path = ARTIFACTS / publication.export_file
    if not path.is_file():
        raise HTTPException(410, '导出文件已不可用，请重新发布')
    return FileResponse(path, media_type='text/csv', filename=f'swap-handover-{item.id}.csv')


@router.get('/handover')
def handover(db: Session = Depends(connection), actor: User = Depends(current)):
    return swap.handover(db)
