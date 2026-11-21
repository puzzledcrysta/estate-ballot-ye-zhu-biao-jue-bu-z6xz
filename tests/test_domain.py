from decimal import Decimal
import pytest
from app.errors import DataError
from app.modules.domain.rule import evaluate


def test_repeat_owner(cases):
    actual, proof = evaluate(cases['repeat_owner'])
    assert actual == Decimal('160')
    assert Decimal(str(dict((label, value) for label, value, _ in proof)['产权人数'])) == Decimal('3')


def test_special_boundary(cases):
    actual, proof = evaluate(cases['special_boundary'])
    assert actual == Decimal('75')
    assert str(dict((label, value) for label, value, _ in proof)['双门槛']) == '通过'


def test_participation_exact(cases):
    actual, proof = evaluate(cases['participation_exact'])
    assert actual == Decimal('60')
    assert str(dict((label, value) for label, value, _ in proof)['双门槛']) == '通过'


def test_only_area(cases):
    # TRAP-106
    actual, proof = evaluate(cases['only_area'])
    assert actual == Decimal('90')
    assert str(dict((label, value) for label, value, _ in proof)['双门槛']) == '未通过'


def test_fractional(cases):
    actual, proof = evaluate(cases['fractional'])
    assert actual == Decimal('9.9009')
    assert Decimal(str(dict((label, value) for label, value, _ in proof)['赞成人数'])) == Decimal('1')


def test_no_votes(cases):
    actual, proof = evaluate(cases['no_votes'])
    assert actual == Decimal('0')
    assert Decimal(str(dict((label, value) for label, value, _ in proof)['参与人数'])) == Decimal('0')


def test_bad_shares(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['bad_shares'])
    assert error.value.code == 'ESTATE_SHARE'


def test_conflicting_vote(cases):
    # TRAP-14
    with pytest.raises(DataError) as error:
        evaluate(cases['conflicting_vote'])
    assert error.value.code == 'ESTATE_CONFLICT'


def test_not_owner(cases):
    with pytest.raises(DataError) as error:
        evaluate(cases['not_owner'])
    assert error.value.code == 'ESTATE_BALLOT'
