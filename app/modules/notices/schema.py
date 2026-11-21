from typing import Annotated
from pydantic import BaseModel, Field
from app.errors import DataError
from app.inputs import input_bytes, CsvText, EncodedCsv

# 一次公示批次最多合并 12 份楼栋送审文件，避免单次请求无限膨胀。
MAX_SOURCES = 12
NameText = Annotated[str, Field(max_length=120)]


class NoticeFile(BaseModel):
    name: NameText = ''
    data: CsvText | None = None
    data_base64: EncodedCsv | None = None

    def raw(self):
        # 公示批次的每份送审文件都必须显式上传，不使用样例兜底。
        return input_bytes(self.data, self.data_base64, None)


class NoticeRequest(BaseModel):
    sources: list[NoticeFile] = Field(min_length=1, max_length=MAX_SOURCES)
    book: CsvText | None = None
    book_base64: EncodedCsv | None = None

    def files(self):
        """返回 [(source_id, name, payload), ...]，source_id 按送审顺序生成并在批次内稳定。"""
        seen = set()
        result = []
        for index, item in enumerate(self.sources, start=1):
            payload = item.raw()
            source_id = f'dong-{index:02d}'
            name = item.name.strip() or f'第 {index} 批送审'
            if name in seen:
                raise DataError('NOTICE_NAME', f'送审文件名称重复：{name}')
            seen.add(name)
            result.append((source_id, name, payload))
        return result

    def ledger(self):
        from app.settings import SAMPLE_ROOT
        return input_bytes(self.book, self.book_base64, SAMPLE_ROOT / 'external.csv')
