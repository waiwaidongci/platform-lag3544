import json
from sqlalchemy import func, select
from src.config.database import Session
from src.constants.enums import Role
from src.domain.demo import demo_calibration_rows, demo_rows, demo_tone_periods
from src.domain.spec import SPEC
from src.models.identity import User
from src.models.source import Dataset
from src.models.swap import CalibrationBatch, TonePeriod
from src.services.datasets import save
from src.services.swap import save_batch
from src.utils.security import hash_password


def seed():
    with Session.begin() as db:
        for role in Role:
            if not db.get(User, role.value):
                db.add(User(username=role.value, role=role, password_hash=hash_password(f'{role.value}-demo-2611')))
        item, created = save(db, SPEC['default_dataset'], SPEC['sample_name'], demo_rows(), 'seed')
        batch, batch_created, _ = save_batch(db, SPEC['swap']['default_batch'], SPEC['swap']['sample_name'],
                                             demo_calibration_rows(), 'seed')
        tones = 0
        for tone in demo_tone_periods():
            exists = db.scalar(select(TonePeriod).where(TonePeriod.station == batch.station,
                                                        TonePeriod.point == tone['point'],
                                                        TonePeriod.start == tone['start'],
                                                        TonePeriod.end == tone['end']))
            if not exists:
                db.add(TonePeriod(station=batch.station, author='seed', **tone))
                tones += 1
        return {'users': db.scalar(select(func.count()).select_from(User)),
                'datasets': db.scalar(select(func.count()).select_from(Dataset)),
                'seed_dataset_id': item.id, 'row_count': item.row_count, 'checksum': item.checksum,
                'created_dataset': created,
                'calibration_batches': db.scalar(select(func.count()).select_from(CalibrationBatch)),
                'seed_batch_id': batch.id, 'batch_created': batch_created, 'tone_periods_added': tones}


if __name__ == '__main__':
    print(json.dumps(seed(), ensure_ascii=False))
