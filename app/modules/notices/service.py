import json
from datetime import datetime, timezone
from app.errors import DataError
from .manifest import notice_manifest
from .merge import merge, describe, motion_summaries
from . import repository


def _enrich(merged, source_names):
    """附上来源名称与逐议案汇总，供页面看清每栋每次送审的采信与结论变化。"""
    for item in merged['sources']:
        item['name'] = source_names[item['source_id']]
    for bucket in ('accepted', 'quarantine', 'suppressed'):
        for row in merged[bucket]:
            row['source_name'] = source_names.get(row.get('source_id'), '')
    merged['motions'] = motion_summaries(merged, merged.pop('_contracts'), merged['_rejected'])
    merged.pop('_rejected', None)
    return merged


def build(sources, book):
    """合并多份送审文件为一次公示批次；同字节集合重跑幂等，不新增批次或重复记录。"""
    proof = notice_manifest(sources, book)
    source_names = {source_id: name for source_id, name, _ in sources}
    payloads = [(source_id, payload) for source_id, _, payload in sources]
    merged = merge(payloads, book)
    created = datetime.now(timezone.utc).isoformat()
    merged['manifest'] = {**proof, 'created': created,
                          'files': [{**item, 'name': source_names[item['source_id']]}
                                    for item in proof['files']]}
    merged['file_details'] = [describe(index, payload, source_names[source_id])
                              for index, (source_id, _, payload) in enumerate(sources, start=1)]
    merged = _enrich(merged, source_names)
    stored = repository.persist(proof['notice_id'], sources, book, merged, created)
    record = json.loads(stored['result'])
    record['sealed'] = bool(stored['sealed'])
    record['sealed_at'] = stored['sealed_at']
    return record


def get(notice_id):
    row, _ = repository.fetch(notice_id)
    record = json.loads(row['result'])
    record['sealed'] = bool(row['sealed'])
    record['sealed_at'] = row['sealed_at']
    return record


def list_notices():
    return repository.history()


def seal(notice_id):
    row, _ = repository.fetch(notice_id)
    if row['sealed']:
        raise DataError('NOTICE_SEALED', '公示批次已封存，不能重复封存', 409)
    sealed_at = datetime.now(timezone.utc).isoformat()
    updated = repository.seal(notice_id, sealed_at)
    return {'notice_id': notice_id, 'sealed': bool(updated['sealed']), 'sealed_at': updated['sealed_at']}


def source_inputs(notice_id):
    _, sources = repository.fetch(notice_id)
    from base64 import b64encode
    return {'sources': [{'source_id': item['source_id'], 'name': item['name'],
                         'data_base64': b64encode(item['payload']).decode()} for item in sources]}


def _metrics(accepted_row):
    metrics = {item['metric']: item['value'] for item in accepted_row['proof']}
    return {'revision': accepted_row['revision'], 'source_id': accepted_row.get('source_id'),
            'line': accepted_row['line'], 'outcome': metrics['双门槛'],
            'participation_area': metrics['参与面积'], 'participation_owners': metrics['参与人数'],
            'yes_area': metrics['赞成面积'], 'yes_owners': metrics['赞成人数'],
            'amount': accepted_row['amount']}


def assess_amendment(notice_id, incoming):
    """封存后出现更高修订：只列受影响议案与差异，不形成新公示结果，等待重新确认。"""
    row, stored_sources = repository.fetch(notice_id)
    if not row['sealed']:
        raise DataError('NOTICE_UNSEALED', '批次尚未封存，直接重跑即可合并补传')
    book = row['book']
    previous = json.loads(row['result'])
    # 原封存文件全部保留参与重跑，再加入新到送审；任一字节变化都可由此体现。
    base = [(item['source_id'], item['name'], item['payload']) for item in stored_sources]
    offset = len(base)
    incoming = [(f'dong-{offset + index:02d}', name, payload)
                for index, (_, name, payload) in enumerate(incoming, start=1)]
    candidate = [*base, *incoming]
    proof = notice_manifest(candidate, book)
    merged = merge([(source_id, payload) for source_id, _, payload in candidate], book)

    old_by_key = {item['key']: item for item in previous['accepted']}
    new_by_key = {item['key']: item for item in merged['accepted']}
    affected, blocked = [], []
    for key in sorted(old_by_key.keys() | new_by_key.keys()):
        old_row, new_row = old_by_key.get(key), new_by_key.get(key)
        old_rev = old_row['revision'] if old_row else None
        new_rev = new_row['revision'] if new_row else None
        higher = new_rev is not None and (old_rev is None or new_rev > old_rev)
        if not (higher or (old_row and not new_row)):
            continue
        if new_row is None:
            # 新修订无法采信（冲突/阻断/业务错误），议案失去可公示结论。
            key_quarantine = [item for item in merged['quarantine'] if item['key'] == key]
            candidate_revision = max((item.get('revision') or 0 for item in key_quarantine),
                                     default=old_rev)
            reasons = [{'source_id': item.get('source_id'), 'line': item['line'],
                        'revision': item.get('revision'),
                        'code': item['code'], 'detail': item['detail']}
                       for item in key_quarantine]
            blocked.append({'key': key, 'previous_revision': old_rev,
                            'candidate_revision': candidate_revision, 'reasons': reasons})
            continue
        before = _metrics(old_row) if old_row else None
        after = _metrics(new_row)
        field_changes = []
        if before:
            for field in ('outcome', 'participation_area', 'participation_owners',
                          'yes_area', 'yes_owners', 'amount'):
                if before[field] != after[field]:
                    field_changes.append({'field': field, 'before': before[field], 'after': after[field]})
        affected.append({'key': key, 'previous_revision': old_rev, 'candidate_revision': new_rev,
                         'conclusion_changed': bool(before and before['outcome'] != after['outcome']),
                         'before': before, 'after': after, 'field_changes': field_changes})

    new_quarantine = [item for item in merged['quarantine']
                      if item.get('source_id') not in {s['source_id'] for s in stored_sources}]
    return {'notice_id': notice_id, 'candidate_id': proof['notice_id'],
            'sealed_notice_id': notice_id, 'affected': affected, 'blocked': blocked,
            'new_quarantine': new_quarantine,
            'would_change': bool(affected or blocked),
            'note': '仅列出受影响议案与差异，确认前不形成新的公示批次'}
