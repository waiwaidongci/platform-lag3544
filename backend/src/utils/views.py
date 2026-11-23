from src.utils.time import iso


def dataset(item):
    return {'id': item.id, 'name': item.name, 'filename': item.filename, 'row_count': item.row_count,
            'checksum': item.checksum, 'author': item.author, 'created_at': iso(item.created_at)}


def run(item, detail=False):
    item_view = {'id': item.id, 'dataset_id': item.dataset_id, 'name': item.name, 'status': item.status,
                 'author': item.author, 'review': item.review, 'decision': item.decision,
                 'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
                 'scheduled_at': iso(item.scheduled_at), 'schedule_id': item.schedule_id,
                 'has_export': bool(item.export_file), 'error': item.error}
    if detail:
        item_view.update(params=item.params, result=item.result, review_note=item.review_note)
    return item_view


def schedule(item):
    from src.domain.spec import SPEC
    return {'id': item.id, 'name': item.name, 'dataset_id': item.dataset_id, 'recipient': item.recipient,
            'next_at': iso(item.next_at), 'repeat_daily': item.repeat_daily, 'enabled': item.enabled,
            'next_report_day': item.params.get(SPEC['schedule_date_param']) if item.enabled else None}


def delivery(item):
    return {'id': item.id, 'run_id': item.run_id, 'recipient': item.recipient,
            'state': item.state, 'detail': item.detail, 'created_at': iso(item.created_at)}


def swap_batch(item):
    return {'id': item.id, 'station': item.station, 'name': item.name, 'filename': item.filename,
            'row_count': item.row_count, 'channels': item.channels, 'checksum': item.checksum,
            'author': item.author, 'created_at': iso(item.created_at)}


def tone_period(item):
    return {'id': item.id, 'station': item.station, 'point': item.point, 'start': item.start,
            'end': item.end, 'author': item.author, 'created_at': iso(item.created_at)}


def determination(item, detail=False):
    item_view = {'id': item.id, 'station': item.station, 'version': item.version, 'state': item.state,
                 'batch_id': item.batch_id, 'author': item.author, 'created_at': iso(item.created_at),
                 'published_at': iso(item.published_at)}
    if detail:
        item_view.update(params=item.params, result=item.result, tone_fingerprint=item.tone_fingerprint)
    return item_view


def publication(item):
    return {'id': item.id, 'determination_id': item.determination_id, 'station': item.station,
            'detail': item.detail, 'author': item.author, 'created_at': iso(item.created_at),
            'has_export': bool(item.export_file)}
