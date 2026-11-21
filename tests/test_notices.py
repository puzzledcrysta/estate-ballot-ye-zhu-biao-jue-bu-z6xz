import csv
import io
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from app.modules.notices import service


HEADER = ['表决议案', '修订号', '提交时间', '议案类别', '产权单元', '表决票', '原始备注']
OWNERSHIP = '一单元:110:甲=100;二单元:100:甲=50+乙=50;三单元:30:丙=100'
VOTES = '甲:赞成;乙:反对;丙:弃权'
BOOK_HEADER = '表决议案,外部记录值(平方米)\n'


def build(rows):
    """rows: (key, revision, kind, votes) — 其余字段用固定样例填充。"""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(HEADER)
    for key, revision, kind, votes in rows:
        writer.writerow([key, revision, '2026-11-18T09:30:00+08:00', kind, OWNERSHIP, votes, ''])
    return stream.getvalue().encode()


def payload(sources, book=None):
    if book is None:
        book = BOOK_HEADER.encode()
    return {'sources': [{'name': name, 'data': text.decode()} for name, text in sources],
            'book': book.decode()}


def motion(report, key):
    return next(item for item in report['motions'] if item['key'] == key)


def make(client, sources, book=None):
    return client.post('/api/notices', json=payload(sources, book))


def test_merge_combines_buildings_into_one_notice(client):
    first = build([('00101', 1, '一般', VOTES)])
    second = build([('00202', 1, '一般', VOTES)])
    response = make(client, [('一号楼', first), ('二号楼', second)])
    assert response.status_code == 200
    report = response.json()
    assert {row['key'] for row in report['accepted']} == {'00101', '00202'}
    assert report['counts']['sources'] == 2 and report['balanced']
    assert [item['name'] for item in report['file_details']] == ['一号楼', '二号楼']


def test_later_old_table_cannot_override_passed_motion(client):
    # 一号楼先送修订 2（通过），二号楼后到的是原样旧表修订 1（未通过）；旧表不得翻回结论。
    newer = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    older = build([('00101', 1, '一般', '甲:反对;乙:反对;丙:弃权')])
    report = make(client, [('一号楼', newer), ('二号楼', older)]).json()
    adopted = motion(report, '00101')['adopted']
    assert (adopted['revision'], adopted['source_id'], adopted['outcome']) == (2, 'dong-01', '通过')
    suppressed = [row for row in report['suppressed'] if row['key'] == '00101']
    assert suppressed and suppressed[0]['code'] == 'SUPERSEDED'


def test_motion_shows_source_revision_participation_and_yes(client):
    first = build([('00101', 1, '一般', VOTES)])
    second = build([('00102', 1, '特别', '甲:赞成;乙:赞成;丙:弃权')])
    report = make(client, [('一号楼', first), ('二号楼', second)]).json()
    summary = motion(report, '00102')
    assert summary['adopted']['source_id'] == 'dong-02'
    assert (summary['adopted']['participation_owners'], summary['adopted']['yes_owners']) == ('3', '2')
    assert summary['adopted']['participation_area'] == '240'
    # 页面可直接读到每个议案采用哪栋楼的哪次送审。
    assert summary['submission_count'] == 1


def test_supplemental_upload_marks_conclusion_change(client):
    first = build([('00101', 1, '一般', '甲:反对;乙:反对;丙:弃权')])
    report = make(client, [('一号楼', first)]).json()
    assert motion(report, '00101')['adopted']['outcome'] == '未通过'
    # 补传修订 2，改为全赞成。
    supplement = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    updated = make(client, [('一号楼', first), ('二号楼补传', supplement)]).json()
    summary = motion(updated, '00101')
    assert summary['conclusion_changed'] is True
    assert summary['adopted']['revision'] == 2
    revisions = [item['revision'] for item in summary['history']]
    assert revisions == [1, 2]
    assert summary['history'][1]['changed'] is True and summary['history'][0]['changed'] is False


def test_identical_resend_is_idempotent_no_new_batch(client):
    first = build([('00101', 1, '一般', VOTES)])
    created = make(client, [('一号楼', first)]).json()['manifest']['notice_id']
    # 同一组文件原样重跑：指纹一致、不新增批次或重复来源记录。
    rerun = make(client, [('一号楼', first)]).json()
    again = make(client, [('一号楼', first)]).json()
    assert rerun['manifest']['notice_id'] == again['manifest']['notice_id'] == created
    notices = client.get('/api/notices').json()
    assert len(notices) == 1 and notices[0]['id'] == created
    # 另一组不同文件产生不同批次，但同组重放仍不重复。
    other = build([('00202', 1, '一般', VOTES)])
    make(client, [('一号楼', first), ('二号楼', other)])
    make(client, [('一号楼', first), ('二号楼', other)])
    assert len(client.get('/api/notices').json()) == 2


def test_byte_identical_set_order_independent_fingerprint(client):
    first = build([('00101', 1, '一般', VOTES)])
    second = build([('00202', 1, '一般', VOTES)])
    one = make(client, [('一号楼', first), ('二号楼', second)]).json()['manifest']['notice_id']
    other = make(client, [('二号楼', second), ('一号楼', first)]).json()['manifest']['notice_id']
    assert one == other


def test_concurrent_merges_keep_single_record(client):
    first = build([('00101', 1, '一般', VOTES)])
    sources = [('一号楼', first)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.build(
            [('dong-01', '一号楼', first)], BOOK_HEADER.encode()), range(4)))
    assert all(item['manifest']['notice_id'] == results[0]['manifest']['notice_id'] for item in results)
    assert len(client.get('/api/notices').json()) == 1


def test_sources_are_retained_and_replayable(client):
    first = build([('00101', 1, '一般', VOTES)])
    report = make(client, [('一号楼', first)]).json()
    notice_id = report['manifest']['notice_id']
    stored = client.get(f'/api/notices/{notice_id}/sources').json()['sources']
    assert len(stored) == 1 and stored[0]['name'] == '一号楼'
    assert b64encode(first).decode() == stored[0]['data_base64']


def test_seal_blocks_repeat_and_amendment_lists_impact(client):
    first = build([('00101', 1, '一般', '甲:反对;乙:反对;丙:弃权')])
    notice_id = make(client, [('一号楼', first)]).json()['manifest']['notice_id']
    sealed = client.post(f'/api/notices/{notice_id}/seal')
    assert sealed.status_code == 200 and sealed.json()['sealed'] is True
    repeat = client.post(f'/api/notices/{notice_id}/seal')
    assert (repeat.status_code, repeat.json()['code']) == (409, 'NOTICE_SEALED')

    higher = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    assessment = client.post(f'/api/notices/{notice_id}/amendments',
                             json=payload([('二号楼补传', higher)])).json()
    assert assessment['would_change'] is True
    item, = assessment['affected']
    assert item['key'] == '00101' and item['conclusion_changed'] is True
    assert (item['before']['outcome'], item['after']['outcome']) == ('未通过', '通过')
    # 仅评估不入库：公示批次列表仍只有封存的那一批。
    assert [row['id'] for row in client.get('/api/notices').json()] == [notice_id]


def test_amendment_requires_sealed_batch(client):
    first = build([('00101', 1, '一般', VOTES)])
    notice_id = make(client, [('一号楼', first)]).json()['manifest']['notice_id']
    response = client.post(f'/api/notices/{notice_id}/amendments',
                           json=payload([('补传', first)]))
    assert (response.status_code, response.json()['code']) == (422, 'NOTICE_UNSEALED')


def test_confirm_after_review_creates_new_notice_keeps_old(client):
    first = build([('00101', 1, '一般', '甲:反对;乙:反对;丙:弃权')])
    sealed_id = make(client, [('一号楼', first)]).json()['manifest']['notice_id']
    client.post(f'/api/notices/{sealed_id}/seal')
    higher = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    confirmed = client.post(f'/api/notices/{sealed_id}/confirm',
                            json=payload([('二号楼补传', higher)])).json()
    new_id = confirmed['manifest']['notice_id']
    assert new_id != sealed_id and motion(confirmed, '00101')['adopted']['revision'] == 2
    history = client.get('/api/notices').json()
    assert {row['id'] for row in history} == {sealed_id, new_id}
    # 旧封存批次原样保留，结论未被改写。
    sealed_record = client.get(f'/api/notices/{sealed_id}').json()
    assert sealed_record['sealed'] is True
    assert motion(sealed_record, '00101')['adopted']['revision'] == 1
    # 新批次包含两份来源文件。
    assert len(confirmed['file_details']) == 2


def test_blocked_higher_revision_is_listed_not_silently_dropped(client):
    good = build([('00101', 1, '一般', VOTES)])
    notice_id = make(client, [('一号楼', good)]).json()['manifest']['notice_id']
    client.post(f'/api/notices/{notice_id}/seal')
    # 修订 2 缺少业务字段，无法采信：不得让修订 1 静默接替，也不得形成新公示。
    broken = io.StringIO(newline='')
    writer = csv.writer(broken)
    writer.writerow(HEADER)
    writer.writerow(['00101', '2', '2026-11-18T09:30:00+08:00', '一般', OWNERSHIP, 'N/A', ''])
    assessment = client.post(f'/api/notices/{notice_id}/amendments',
                             json=payload([('坏表', broken.getvalue().encode())])).json()
    assert assessment['affected'] == []
    item, = assessment['blocked']
    assert item['key'] == '00101' and item['reasons']
    assert item['candidate_revision'] == 2 and item['previous_revision'] == 1
    assert len(client.get('/api/notices').json()) == 1


def test_duplicate_source_name_rejected(client):
    first = build([('00101', 1, '一般', VOTES)])
    response = make(client, [('同名', first), ('同名', first)])
    assert (response.status_code, response.json()['code']) == (422, 'NOTICE_NAME')


def test_unknown_notice_404(client):
    response = client.get('/api/notices/missing')
    assert (response.status_code, response.json()['code']) == (404, 'NOTICE_UNKNOWN')


def test_quarantine_and_suppressed_carry_source_trace(client):
    first = build([('00101', 1, '一般', VOTES)])
    older = build([('00101', 1, '一般', VOTES)])
    report = make(client, [('一号楼', first), ('二号楼', older)]).json()
    duplicates = [row for row in report['suppressed'] if row['key'] == '00101']
    duplicate, = duplicates
    assert duplicate['source_id'] == 'dong-02' and duplicate['source_name'] == '二号楼'


def test_multi_source_counts_stay_balanced(client):
    first = build([('00101', 1, '一般', VOTES), ('00102', 1, '一般', VOTES)])
    second = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    report = make(client, [('一号楼', first), ('二号楼', second)]).json()
    counts = report['counts']
    assert counts['input'] == sum(counts[k] for k in
                                  ('accepted', 'rejected', 'suppressed', 'blank', 'repeated_header'))
    assert report['balanced'] and counts['sources'] == 2


def test_confirm_keeps_sealed_ledger_basis(client):
    book = (BOOK_HEADER + '00101,240\n').encode()
    first = build([('00101', 1, '一般', '甲:反对;乙:反对;丙:弃权')])
    sealed_id = make(client, [('一号楼', first)], book=book).json()['manifest']['notice_id']
    client.post(f'/api/notices/{sealed_id}/seal')
    higher = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    # 请求里带一份完全不同的外部账，确认后仍须以封存批次的账为基准。
    other_book = (BOOK_HEADER + '00101,1\n').encode()
    confirmed = client.post(f'/api/notices/{sealed_id}/confirm',
                            json=payload([('二号楼补传', higher)], other_book)).json()
    assert confirmed['manifest']['book_sha256'] == \
        client.get(f'/api/notices/{sealed_id}').json()['manifest']['book_sha256']
    row, = (r for r in confirmed['book']['rows'] if r['key'] == '00101')
    assert row['reference'] == '240'


def test_motion_history_marks_each_revision_outcome(client):
    first = build([('00101', 1, '一般', '甲:反对;乙:反对;丙:弃权')])
    second = build([('00101', 2, '一般', '甲:赞成;乙:赞成;丙:赞成')])
    report = make(client, [('一号楼', first), ('二号楼', second)]).json()
    history = motion(report, '00101')['history']
    assert [(h['revision'], h['outcome'], h['changed']) for h in history] == \
        [(1, '未通过', False), (2, '通过', True)]
