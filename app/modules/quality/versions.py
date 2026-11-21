from collections import defaultdict
from app.evidence import finding


def split_versions(records, unverified):
    groups = defaultdict(list)
    for record in records:
        groups[record['key']].append(record)
    ready, duplicates, conflicts = [], [], []
    for key, group in sorted(groups.items()):
        latest = max(row['revision'] for row in group)
        pending = unverified.get(key, 0)
        if pending >= latest:
            for row in group:
                marked = finding(row,'REV_BLOCKED',f'修订 {pending} 仍有来源未采信')
                marked['source_id'] = row.get('source_id')
                conflicts.append(marked)
            continue
        candidates = sorted((row for row in group if row['revision']==latest),key=lambda row:row['line'])
        older = [row for row in group if row['revision']!=latest]
        for row in older:
            marked = finding(row,'SUPERSEDED',f'修订 {latest} 取代旧版本')
            marked['source_id'] = row.get('source_id')
            duplicates.append(marked)
        signatures = {tuple(row['fields'].items()) for row in candidates}
        if len(signatures)>1:
            for row in candidates:
                marked = finding(row,'REV_CONFLICT',f'最高修订 {latest} 的来源字段互相冲突')
                marked['source_id'] = row.get('source_id')
                conflicts.append(marked)
        else:
            ready.append(candidates[0])
            for row in candidates[1:]:
                marked = finding(row,'EXACT_DUP',f'同为修订 {latest}，保留第 {candidates[0]["line"]} 行')
                marked['source_id'] = row.get('source_id')
                duplicates.append(marked)
    return ready,duplicates,conflicts
