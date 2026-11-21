import json
from app.errors import DataError
from app.store import connection


def lookup(db, notice_id):
    row = db.execute('SELECT * FROM notices WHERE id=?', (notice_id,)).fetchone()
    if row is None:
        raise DataError('NOTICE_UNKNOWN', '没有此公示批次', 404)
    return row


def fetch(notice_id):
    with connection() as db:
        row = lookup(db, notice_id)
        sources = [dict(item) for item in db.execute(
            'SELECT source_id,name,ordinal,payload FROM notice_sources WHERE notice_id=? ORDER BY ordinal',
            (notice_id,))]
        return row, sources


def persist(notice_id, sources, book, result, created):
    """幂等写入：同指纹重跑不新增批次、不重复来源记录。"""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id FROM notices WHERE id=?', (notice_id,)).fetchone()
        if existing is None:
            db.execute('INSERT INTO notices VALUES (?,?,?,0,?,NULL)',
                       (notice_id, book, json.dumps(result, ensure_ascii=False), created))
            for ordinal, (source_id, name, payload) in enumerate(sources):
                db.execute('INSERT INTO notice_sources VALUES (?,?,?,?,?)',
                           (notice_id, source_id, name, payload, ordinal))
        return lookup(db, notice_id)


def history():
    with connection() as db:
        rows = db.execute(
            'SELECT id,created,sealed,sealed_at FROM notices ORDER BY created DESC,id DESC LIMIT 50').fetchall()
        return [dict(row) for row in rows]


def seal(notice_id, sealed_at):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = lookup(db, notice_id)
        if row['sealed']:
            raise DataError('NOTICE_SEALED', '公示批次已封存，不能重复封存', 409)
        db.execute('UPDATE notices SET sealed=1, sealed_at=? WHERE id=?', (sealed_at, notice_id))
        return dict(lookup(db, notice_id))
