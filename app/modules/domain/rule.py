from collections import defaultdict
from decimal import Decimal as D
from app.errors import DataError
from .values import number, parts


def ownership(text):
    households, properties = defaultdict(D), set()
    for item in parts(text):
        name, sep, body = item.partition(':')
        area, second, shares = body.partition(':')
        if not sep or not second or not name or name in properties:
            raise DataError('ESTATE_TITLE', f'房屋产权重复或缺字段 {name}')
        properties.add(name)
        size = number(area, D('0.01'), 10**7)
        fractions = {}
        for value in shares.split('+'):
            owner, equals, pct = value.partition('=')
            if not owner or not equals or owner in fractions:
                raise DataError('ESTATE_SHARE', f'{name} 内份额字段有误')
            fractions[owner] = number(pct, D('0.0001'), 100)
        if sum(fractions.values()) != 100:
            raise DataError('ESTATE_SHARE', f'{name} 权属份额之和须为 100%')
        for owner, pct in fractions.items():
            households[owner] += size*pct/100
    if not households:
        raise DataError('ESTATE_TITLE', '没有可计算的产权单元')
    return households


def evaluate(row):
    owners = ownership(row['产权单元'])
    thresholds = {'一般': (1, 2, False), '特别': (3, 4, True)}
    if row['议案类别'] not in thresholds:
        raise DataError('ESTATE_KIND', '议案类别须为一般或特别')
    ballots = {}
    for item in parts(row['表决票']):
        owner, sep, choice = item.partition(':')
        if not sep or owner not in owners or choice not in {'赞成','反对','弃权'}:
            raise DataError('ESTATE_BALLOT', f'表决票无效 {item}')
        if owner in ballots and ballots[owner] != choice:
            raise DataError('ESTATE_CONFLICT', f'{owner} 有互相矛盾的表决票')
        ballots[owner] = choice
    yes = [owner for owner,choice in ballots.items() if choice=='赞成']
    area, votes = sum(owners.values()), len(ballots)
    turnout, approved = sum((owners[owner] for owner in ballots), D(0)), sum((owners[owner] for owner in yes), D(0))
    quorum = turnout*3 >= area*2 and votes*3 >= len(owners)*2
    numerator, denominator, inclusive = thresholds[row['议案类别']]
    margins = [approved*denominator-turnout*numerator, len(yes)*denominator-votes*numerator]
    passed = quorum and all(value >= 0 if inclusive else value > 0 for value in margins)
    return approved, [('产权面积',area,'平方米'),('参与面积',turnout,'平方米'),('赞成面积',approved,'平方米'),
                      ('产权人数',len(owners),'人'),('参与人数',votes,'人'),('赞成人数',len(yes),'人'),
                      ('双门槛','通过' if passed else '未通过','')]
