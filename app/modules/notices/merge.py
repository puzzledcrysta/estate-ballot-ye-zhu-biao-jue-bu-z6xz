"""多楼栋送审文件合并为一次公示批次。

每个来源文件独立走完导入、归一与质检，再按业务键（表决议案）跨文件选最高修订，
旧版"后到覆盖"不会把已通过议案翻回旧结论；全程保留每个来源的原始字节与逐条痕迹。
"""
from collections import defaultdict
from hashlib import sha256
from app.errors import DataError
from app.evidence import distribution, finding
from app.modules.intake.service import intake
from app.modules.intake.reader import decode
from app.modules.contract.service import normalize
from app.modules.quality.versions import split_versions
from app.modules.domain.service import calculate
from app.modules.domain.rule import evaluate
from app.modules.reconcile.service import compare


def describe(index, payload, name):
    """来源文件清单：顺序、名称（可空）、字节摘要与编码。"""
    text, encoding = decode(payload)
    label = (name or '').strip() or f'送审文件 {index}'
    return {'index': index, 'name': label[:120], 'sha256': sha256(payload).hexdigest(),
            'bytes': len(payload), 'encoding': encoding}


def _tag_suppressed(row, code, detail, source_id):
    marked = dict(row)
    marked['source_id'] = source_id
    marked.setdefault('code', code)
    marked.setdefault('detail', detail)
    return marked


def merge(sources, book):
    """sources: [(source_id, payload), ...]，book: 外部账字节。返回合并复算结果。"""
    if not sources:
        raise DataError('NOTICE_EMPTY', '至少需要一份送审文件')
    manifests, contracts, rejected, suppressed = [], [], [], []
    input_total = blank_total = header_total = 0
    for source_id, payload in sources:
        raw = intake(payload)
        passed, bad = normalize(raw)
        for row in passed:
            row['source_id'] = source_id
        for row in bad:
            row['source_id'] = source_id
        contracts.extend(passed)
        rejected.extend(bad)
        input_total += raw['input_count']
        blank_total += len(raw['blank_lines'])
        header_total += len(raw['header_lines'])
        manifests.append({'source_id': source_id, 'rows': raw['input_count'],
                          'accepted_rows': len(raw['rows']), 'rejected_rows': len(raw['rejected']),
                          'blank_lines': raw['blank_lines'], 'header_lines': raw['header_lines'],
                          'encoding': raw['encoding']})

    # 跨文件按业务键选最高修订；未采信的高修订同样阻断旧版接替。
    unverified = {}
    for row in rejected:
        if 'revision' in row:
            unverified[row['key']] = max(row['revision'], unverified.get(row['key'], 0))
    ready, duplicates, conflicts = split_versions(contracts, unverified)
    for row in duplicates:
        suppressed.append(_tag_suppressed(row, row['code'], row['detail'], row.get('source_id')))
    for row in conflicts:
        rejected.append(_tag_suppressed(row, row['code'], row['detail'], row.get('source_id')))

    accepted, domain_bad = calculate(ready)
    # calculate 重建记录会丢来源标记，按行号+业务键从 ready 补回楼栋来源。
    origin = {(row['key'], row['line']): row.get('source_id') for row in ready}
    for row in accepted:
        row['source_id'] = origin.get((row['key'], row['line']))
    for row in domain_bad:
        row['source_id'] = row.get('source_id') or origin.get((row['key'], row['line']))
    rejected.extend(domain_bad)
    rejected.sort(key=lambda row: (row['source_id'], row['line']))
    suppressed.sort(key=lambda row: (row['source_id'], row['line']))

    counts = {'input': input_total, 'accepted': len(accepted), 'rejected': len(rejected),
              'suppressed': len(suppressed), 'blank': blank_total, 'repeated_header': header_total,
              'sources': len(sources)}
    balanced = input_total == sum(counts[key] for key in
                                  ('accepted', 'rejected', 'suppressed', 'blank', 'repeated_header'))
    if not balanced:
        raise RuntimeError('合并批次来源记录数量无法闭合')
    return {'sources': manifests, 'counts': counts, 'balanced': balanced,
            'accepted': accepted, 'quarantine': rejected, 'suppressed': suppressed,
            'reasons': distribution(rejected), 'book': compare(accepted, book),
            '_contracts': contracts, '_rejected': rejected}


def _revision_outcome(records):
    """对同一议案同一修订的一组送审记录复算结论。

    返回 (outcome, blocked_code)：同版字段冲突或业务错误时结论为 None 并附原因，
    与批次级"旧版无法接替"的隔离口径保持一致。
    """
    signatures = {tuple(row['fields'].items()) for row in records}
    if len(signatures) > 1:
        return None, 'REV_CONFLICT'
    try:
        _, proof = evaluate(records[0]['fields'])
    except DataError as error:
        return None, error.code
    return next(item[1] for item in proof if item[0] == '双门槛'), None


def motion_summaries(merged, contracts, rejected):
    """按议案汇总：采用哪栋哪次送审、参与/赞成结果、同案全部送审痕迹与逐修订结论变化。"""
    accepted = {row['key']: row for row in merged['accepted']}
    # 按 (议案, 修订) 归集所有归一成功的送审记录（含被替代/重复的旧表）。
    revisions = defaultdict(list)
    for row in contracts:
        revisions[(row['key'], row['revision'])].append(row)
    blocked_revisions = defaultdict(list)
    for row in rejected:
        if 'revision' in row:
            blocked_revisions[(row['key'], row['revision'])].append(row)

    traces = defaultdict(list)
    for bucket, status in ((merged['accepted'], '采信'), (merged['suppressed'], '替代'),
                           (merged['quarantine'], '隔离')):
        for row in bucket:
            traces[row['key']].append({'source_id': row.get('source_id'), 'line': row['line'],
                                       'revision': row.get('revision'), 'status': status,
                                       'code': row.get('code', ''), 'detail': row.get('detail', '')})
    summaries = []
    for key in sorted(traces):
        adopted = accepted.get(key)
        history, prior = [], None
        revision_numbers = sorted({rev for (k, rev) in revisions if k == key}
                                  | {rev for (k, rev) in blocked_revisions if k == key})
        for revision in revision_numbers:
            rows = revisions.get((key, revision), [])
            blocked = blocked_revisions.get((key, revision), [])
            if rows:
                outcome, code = _revision_outcome(rows)
            else:
                outcome, code = None, blocked[0]['code']
            submissions = [row for row in traces[key] if row['revision'] == revision]
            # 只在上一修订有可判定结论时比较；阻断/冲突修订不重置对照基线。
            changed = outcome is not None and prior is not None and prior != outcome
            history.append({'revision': revision, 'outcome': outcome, 'blocked_code': code,
                            'changed': changed,
                            'submissions': sorted(submissions, key=lambda row: (row['source_id'] or '', row['line']))})
            if outcome is not None:
                prior = outcome
        if adopted is not None:
            metrics = {item['metric']: item['value'] for item in adopted['proof']}
            current = {'outcome': metrics['双门槛'], 'participation_area': metrics['参与面积'],
                       'participation_owners': metrics['参与人数'], 'yes_area': metrics['赞成面积'],
                       'yes_owners': metrics['赞成人数'], 'source_id': adopted.get('source_id'),
                       'line': adopted['line'], 'revision': adopted['revision']}
        else:
            current = None
        summaries.append({'key': key, 'adopted': current, 'history': history,
                          'conclusion_changed': any(item['changed'] for item in history),
                          'submission_count': len(traces[key])})
    return summaries
