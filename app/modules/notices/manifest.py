from hashlib import sha256
from app.settings import RULE_VERSION


def notice_manifest(sources, book):
    """同一组来源字节（与顺序无关）与同一外部账生成同一公示批次指纹。

    sources: [(source_id, name, payload), ...]
    """
    source_hashes = [sha256(payload).hexdigest() for _, _, payload in sources]
    book_hash = sha256(book).hexdigest()
    # 指纹只取决于字节集合，送审顺序变化不产生新批次；展示顺序仍按提交顺序保留。
    basis = '|'.join(sorted(source_hashes))
    notice_id = sha256(f'{RULE_VERSION}:notice:{basis}:{book_hash}'.encode()).hexdigest()
    files = [{'source_id': source_id, 'name': name, 'sha256': digest}
             for (source_id, name, _), digest in zip(sources, source_hashes)]
    return {'notice_id': notice_id, 'source_sha256': source_hashes,
            'book_sha256': book_hash, 'version': RULE_VERSION, 'files': files}
