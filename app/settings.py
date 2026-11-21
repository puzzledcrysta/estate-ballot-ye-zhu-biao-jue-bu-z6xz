import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / 'sample_data'
DB = Path(os.getenv('WORKBENCH_DB', str(ROOT/'state/ledger.sqlite3')))
TITLE = '业主表决簿'
SLUG = 'estate-ballot'
KEY = '表决议案'
FIELDS = ('议案类别', '产权单元', '表决票')
ROLE = '住宅小区业委会计票员'
UNIT = '平方米'
RULE_VERSION = 'estate-ballot-1.0'
SIGNATURE = '户与面积双计'
TABS = {'intake': '送审票册', 'contract': '产权字段', 'quality': '冲突票夹', 'domain': '份额计票', 'reconcile': '公示勾稽', 'runs': '议案记录', 'review': '计票底稿'}
