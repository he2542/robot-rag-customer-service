import json

import pytest

from src.services.answer_policy import render_context_answer, UNSUPPORTED_ANSWER


A='1. A型滤网不得水洗，必须完全晾干。'
B='2. B型滤网可水洗，温度≤35℃。'
REFS=[{'id':'S1','excerpt':A+'\n9. 其他说明。'}, {'id':'S2','excerpt':B}]


def answer(quote,text='所有滤网都可以水洗，温度≤50℃。',refs=None):
    return render_context_answer(json.dumps({'decision':'answer','claims':[{'text':text,'quote':quote}]},ensure_ascii=False),REFS if refs is None else refs,'滤网维护有哪些要求？')


def test_verified_complete_entries_are_rendered_separately_instead_of_merged_claim():
    result=answer(A+'\n'+B)
    assert 'A型滤网不得水洗，必须完全晾干。 [S1]' in result
    assert 'B型滤网可水洗，温度≤35℃。 [S2]' in result
    assert '所有滤网' not in result and '50' not in result
    assert '分别' in result


@pytest.mark.parametrize('quote',[
    A+'\n'+B.replace('35','50'),
    A.replace('不得','可以')+'\n'+B,
    A+'\n2. 可水洗，温度≤35℃。',
    A+'……'+B,
    A+'\n任意解释\n'+B,
    A+'\n'+B[:-1],
])
def test_incomplete_or_modified_stitched_quote_is_not_salvaged(quote):
    assert answer(quote)==UNSUPPORTED_ANSWER


def test_ambiguous_fragment_is_not_given_an_arbitrary_source():
    assert answer(A+'\n'+B,refs=REFS+[{'id':'S3','excerpt':A}])==UNSUPPORTED_ANSWER


def test_literal_quote_keeps_existing_behavior():
    assert answer(A,text='A型滤网不得水洗。')=='A型滤网不得水洗。 [S1]'


def test_troubleshooting_keeps_unmatched_composite_rejected():
    raw=json.dumps({'decision':'answer','claims':[{'text':'混合操作建议','quote':A+'\n'+B}]},ensure_ascii=False)
    assert render_context_answer(raw,REFS,'滤网堵塞怎么办？')==UNSUPPORTED_ANSWER


def test_recovery_does_not_resurrect_disassembly_or_lubrication():
    unsafe='2. 每周拆解主刷仓，滴专用润滑油。'
    result=answer(A+'\n'+unsafe,refs=[REFS[0],{'id':'S2','excerpt':unsafe}])
    assert 'A型滤网不得水洗' in result
    assert '每周拆解' not in result and '滴专用' not in result
    assert '专业售后' in result
