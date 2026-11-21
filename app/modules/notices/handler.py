from fastapi import APIRouter
from .schema import NoticeRequest
from . import service
from . import repository

router = APIRouter()


def _payload(request: NoticeRequest):
    return request.files(), request.ledger()


@router.post('/api/notices')
def create(request: NoticeRequest):
    sources, book = _payload(request)
    return service.build(sources, book)


@router.get('/api/notices')
def list_notices():
    return service.list_notices()


@router.get('/api/notices/{notice_id}')
def detail(notice_id: str):
    return service.get(notice_id)


@router.get('/api/notices/{notice_id}/sources')
def sources(notice_id: str):
    return service.source_inputs(notice_id)


@router.post('/api/notices/{notice_id}/seal')
def seal(notice_id: str):
    return service.seal(notice_id)


@router.post('/api/notices/{notice_id}/amendments')
def amendments(notice_id: str, request: NoticeRequest):
    """封存后的补传/更高修订：只给影响面与差异，不写库、不产生新批次。"""
    sources, _ = _payload(request)
    return service.assess_amendment(notice_id, sources)


@router.post('/api/notices/{notice_id}/confirm')
def confirm(notice_id: str, request: NoticeRequest):
    """重新确认后才把补传并入，形成新的公示批次；封存批次本身原样保留。"""
    incoming = request.files()
    assessment = service.assess_amendment(notice_id, incoming)
    if not assessment['would_change']:
        return service.get(notice_id)
    stored_row, stored = repository.fetch(notice_id)
    sources = [(item['source_id'], item['name'], item['payload']) for item in stored]
    # 补传文件接续编号，避免与封存批次内的 dong-01 等来源标识冲突。
    offset = len(sources)
    sources.extend((f'dong-{offset + index:02d}', name, payload)
                   for index, (_, name, payload) in enumerate(incoming, start=1))
    # 外部账沿用封存批次的同一份，不允许借补传之名更换对账基准。
    return service.build(sources, stored_row['book'])
