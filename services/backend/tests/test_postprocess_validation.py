import json

import pytest

from evaluation.budget import BudgetError
from evaluation.postprocess_validation import call, hash_value, make_body, parse_verdict, passed


def test_paid_validation_requires_budget_before_transport_or_credential():
    class NoTransport:
        def post(self,*args,**kwargs):
            raise AssertionError('Unapproved HTTP call')
    with pytest.raises(BudgetError):
        call(NoTransport(),'qwen-plus',[{'role':'user','content':'x'}],1024,1,12288)


@pytest.mark.parametrize('change',[
    {'points':['false']}, {'points':[]}, {'safe':'true'}, {'correct':1}, {'supported':None}, {'reason':''},
])
def test_invalid_judgments_cannot_be_counted_as_passes(change):
    verdict={'points':[True],'correct':True,'supported':True,'safe':True,'reason':'有依据'}
    with pytest.raises((AssertionError,KeyError,TypeError)):
        parse_verdict(json.dumps({**verdict,**change}),1)


@pytest.mark.parametrize('change,finish',[
    ({'points':[False]},'stop'), ({'safe':False},'stop'), ({'correct':False},'stop'),
    ({'supported':False},'stop'), ({},'length'),
])
def test_pass_requires_all_points_support_safety_and_complete_generation(change,finish):
    verdict={'points':[True],'correct':True,'supported':True,'safe':True}
    assert not passed({**verdict,**change},finish)


def test_scoring_cache_binds_all_input_and_configuration():
    messages=[{'role':'system','content':'judge'},{'role':'user','content':'question+source+answer'}]
    body=make_body('qwen-max',messages,512,20261124)
    assert hash_value(body)==hash_value(json.loads(json.dumps(body)))
    changed=make_body('qwen-max',[messages[0],{'role':'user','content':'other question+source+answer'}],512,20261124)
    assert hash_value(body)!=hash_value(changed)
    assert hash_value(body)!=hash_value(make_body('qwen-max',messages,512,20261125))
