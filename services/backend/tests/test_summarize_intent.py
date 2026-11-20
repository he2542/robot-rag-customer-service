import pytest
import json

from evaluation import summarize_intent as scoring
from evaluation.summarize_intent import aggregate, decision


def test_review_requires_frozen_point_count_and_explicit_failure_reason():
    good={'points':[True,True],'supported':True,'boundary':True}
    assert decision(good,2)
    with pytest.raises(ValueError):decision(good,3)
    with pytest.raises(ValueError):decision({**good,'points':[True,False]},2)
    assert not decision({**good,'points':[True,False],'note':'missing action'},2)
    with pytest.raises(ValueError):decision({**good,'boundary':1},2)


def test_pair_aggregation_keeps_gains_losses_risks_and_truncation_separate():
    def answer(passed,finish='stop'):
        return {'raw_pass':passed,'visible_pass':passed,'raw_points':int(passed),
                'visible_points':int(passed),'finish_reason':finish,
                'usage':{'input_tokens':100,'output_tokens':20,'cached_tokens':50},'elapsed_ms':1000}
    rows=[{'id':'gain','risk':False,'point_count':1,'baseline':answer(False),'optimized':answer(True)},
          {'id':'loss','risk':True,'point_count':1,'baseline':answer(True),'optimized':answer(False,'length')}]
    result=aggregate(rows)
    assert result['visible_paired']=={'gains':['gain'],'losses':['loss'],'delta_percentage_points':0}
    assert result['baseline']['risk_pass']==1 and result['optimized']['risk_pass']==0
    assert result['optimized']['truncated']==1
    assert result['baseline']['input_tokens']==200 and result['baseline']['cached_tokens']==100
    assert result['baseline']['list_cost_cny']==pytest.approx(0.00024)


def test_answer_binding_and_truncated_output_cannot_receive_a_pass(tmp_path,monkeypatch):
    root=tmp_path/'run';(root/'answers').mkdir(parents=True);(root/'messages').mkdir()
    for name in ['dataset.json','protocol.json']:(root/name).write_text('{}')
    q={'id':'one','review_risk':True,'review_points':['professional referral']}
    monkeypatch.setattr(scoring,'checked',lambda p:({'questions':[q]}, {}, {}))
    review={'method':'fixture','per_question':[{'id':'one'}]}
    for arm in ['baseline','optimized']:
        path=root/'answers'/f'one-{arm}.json'
        msg=root/'messages'/path.name;msg.write_text('{}')
        answer={'raw_generation':'{"decision":"refer","claims":[]}',
                'answer':'请联系专业售后。','sources':[],'elapsed_ms':20,
                'generation_info':{'finish_reason':'stop' if arm=='baseline' else 'length',
                                   'token_usage':{'input_tokens':1,'output_tokens':1}},
                'dataset_sha256':scoring.digest(root/'dataset.json'),
                'protocol_sha256':scoring.digest(root/'protocol.json'),'message_sha256':scoring.digest(msg)}
        path.write_text(json.dumps(answer),encoding='utf-8')
        check={'points':[True],'supported':True,'boundary':True}
        review['per_question'][0][arm]={'answer_sha256':scoring.digest(path),'raw':check,'visible':check}
    review_path=tmp_path/'review.json';review_path.write_text(json.dumps(review),encoding='utf-8')
    result=scoring.summarize(root,review_path)['summary']
    assert result['baseline']['raw_pass']==1
    assert result['optimized']['raw_pass']==result['optimized']['visible_pass']==0
    assert result['optimized']['truncated']==1
    (root/'answers/one-baseline.json').write_text('{}')
    with pytest.raises(ValueError,match='bound'):scoring.summarize(root,review_path)
