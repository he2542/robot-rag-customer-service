import json

import pytest

from src.services.answer_policy import render_context_answer

QUOTE='5. 拖布（可水洗）：正常使用3-6个月更换，宠物环境1-2个月更换。'


def render(text,quote=QUOTE,question='各类耗材的维护节奏怎样？'):
    return render_context_answer(json.dumps({'decision':'answer','claims':[{'text':text,'quote':quote}]},ensure_ascii=False),
        [{'id':'S1','excerpt':quote}],question)


@pytest.mark.parametrize('extra',['自动洗机型每3个月更换。','每日清理。','每周清理。'])
def test_additional_cycle_is_replaced_with_full_supported_entry(extra):
    out=render('拖布正常使用3-6个月更换；'+extra)
    assert '拖布（可水洗）：正常使用3-6个月更换，宠物环境1-2个月更换。 [S1]' in out
    assert extra not in out


def test_equivalent_range_uses_original_entry():
    text='拖布正常使用3至6个月更换，宠物环境1～2个月更换。'
    assert '拖布（可水洗）：正常使用3-6个月更换，宠物环境1-2个月更换。 [S1]' in render(text)


def test_matching_cycle_keeps_all_original_conditions():
    text='宠物环境下，拖布1-2个月更换。'
    assert '正常使用3-6个月更换，宠物环境1-2个月更换。 [S1]' in render(text)


def test_ordinary_troubleshooting_is_not_rewritten_by_cycle_rule():
    text='每周清理。'
    assert render(text,question='拖布脏了怎么办？')==text+' [S1]'


def test_recovered_cycle_entry_does_not_restore_dangerous_procedure():
    quote='1. 主刷轴承每月滴专用润滑油。'
    result=render('主刷轴承每周滴专用润滑油。',quote)
    assert '每月滴' not in result and '每周滴' not in result
    assert '专业售后' in result


@pytest.mark.parametrize('text', [
    '所有滤网正常使用3-6个月更换，宠物环境1-2个月更换。',
    '拖布正常使用1-2个月更换，宠物环境3-6个月更换。',
    '所有环境下拖布3-6个月更换。',
])
def test_matching_cycles_cannot_preserve_wrong_component_or_condition(text):
    out = render(text)
    assert '拖布（可水洗）：正常使用3-6个月更换，宠物环境1-2个月更换。 [S1]' in out
    assert text not in out


def test_separate_entries_keep_their_source_and_negation():
    a = '1. A型滤网不得水洗，每月更换。'
    b = '2. B型滤网可水洗，每周清理。'
    raw = json.dumps({'decision':'answer','claims':[{'text':'所有滤网可水洗，每月更换，每周清理。','quote':a+'\n'+b}]},ensure_ascii=False)
    refs = [{'id':'S1','excerpt':a}, {'id':'S2','excerpt':b}]
    out = render_context_answer(raw, refs, '耗材的维护周期怎样？')
    assert a[3:]+' [S1]' in out and b[3:]+' [S2]' in out
    assert '所有滤网' not in out


@pytest.mark.parametrize('quote,refs', [
    ('拖布正常使用3-6个月更换。', [{'id':'S1','excerpt':'1. 拖布正常使用3-6个月更换，宠物环境1-2个月更换。'}]),
    (QUOTE, [{'id':'S1','excerpt':QUOTE}, {'id':'S2','excerpt':QUOTE}]),
    (QUOTE, [{'id':'S1','excerpt':QUOTE+'\n'+QUOTE}]),
    (QUOTE+'\n2. 所有部件每周清理。', [{'id':'S1','excerpt':QUOTE}]),
])
def test_partial_ambiguous_or_mixed_invalid_entries_are_not_restored(quote,refs):
    from src.services.answer_policy import UNSUPPORTED_ANSWER
    raw = json.dumps({'decision':'answer','claims':[{'text':'所有部件每周清理。','quote':quote}]},ensure_ascii=False)
    assert render_context_answer(raw,refs,'耗材的维护周期怎样？') == UNSUPPORTED_ANSWER


def test_identical_original_entries_are_displayed_once():
    raw = json.dumps({'decision':'answer','claims':[{'text':'结论一','quote':QUOTE},{'text':'结论二','quote':QUOTE}]},ensure_ascii=False)
    out = render_context_answer(raw,[{'id':'S1','excerpt':QUOTE}],'耗材的维护周期怎样？')
    assert out.count('拖布（可水洗）') == 1


def test_noncycle_information_keeps_existing_behavior():
    text, quote = '耗材包括拖布。', '1. 耗材包括主刷和拖布。'
    assert render(text,quote)==text+' [S1]'


def test_complete_question_answer_preserves_named_part():
    quote = '57. 水箱密封圈多久更换？\n- 每6-12个月更换，开裂立即更换。'
    refs = [{'id':'S1','excerpt':'### 保养\n57. **水箱密封圈多久更换？**\n- 每6-12个月更换，开裂立即更换。\n58. 拖布如何保养？\n- 每周清理。'}]
    raw = json.dumps({'decision':'answer','claims':[{'text':'所有滤网每6-12个月更换。','quote':quote}]},ensure_ascii=False)
    out = render_context_answer(raw,refs,'耗材维护周期怎样？')
    assert '水箱密封圈多久更换？' in out and '每6-12个月更换，开裂立即更换。 [S1]' in out
    assert '所有滤网' not in out and '每周清理' not in out


def test_partial_question_answer_cannot_drop_later_condition():
    from src.services.answer_policy import UNSUPPORTED_ANSWER
    full = '1. 拖布多久更换？\n- 正常使用3-6个月更换。\n- 宠物环境1-2个月更换。'
    raw = json.dumps({'decision':'answer','claims':[{'text':'所有环境3-6个月更换。','quote':full.split('\n- 宠物')[0]}]},ensure_ascii=False)
    assert render_context_answer(raw,[{'id':'S1','excerpt':full}],'耗材维护周期怎样？') == UNSUPPORTED_ANSWER


@pytest.mark.parametrize('quote', [QUOTE[3:], QUOTE[3:].replace('拖布', '**拖布**')])
def test_complete_entry_without_number_is_restored_from_unique_source(quote):
    raw = json.dumps({'decision': 'answer', 'claims': [{'text': '所有部件每月换。', 'quote': quote}]}, ensure_ascii=False)
    out = render_context_answer(raw, [{'id': 'S1', 'excerpt': QUOTE}], '耗材维护周期怎样？')
    assert QUOTE[3:] + ' [S1]' in out
    assert '所有部件' not in out


@pytest.mark.parametrize('original', [
    '1. A型滤网不得水洗，每月更换。',
    '57. 水箱密封圈多久更换？\n- 每6-12个月更换，开裂立即更换。',
])
def test_unnumbered_full_entry_keeps_negation_and_multiline_conditions(original):
    quote = original.split('. ', 1)[1]
    raw = json.dumps({'decision': 'answer', 'claims': [{'text': '错误摘要每月换。', 'quote': quote}]}, ensure_ascii=False)
    out = render_context_answer(raw, [{'id': 'S2', 'excerpt': original}], '耗材维护周期怎样？')
    assert quote + ' [S2]' in out and '错误摘要' not in out


def test_unnumbered_dangerous_entry_still_rejected():
    full = '1. 主刷轴承每月滴专用润滑油。'
    raw = json.dumps({'decision': 'answer', 'claims': [{'text': '每月滴润滑油。', 'quote': full[3:]}]}, ensure_ascii=False)
    out = render_context_answer(raw, [{'id': 'S1', 'excerpt': full}], '耗材维护周期怎样？')
    assert '每月滴' not in out and '专业售后' in out


@pytest.mark.parametrize('quote, originals', [
    (QUOTE[3:], QUOTE + '\n6. ' + QUOTE[3:]),
    ('拖布正常使用3-6个月更换。', QUOTE),
    ('6. ' + QUOTE[3:], QUOTE),
])
def test_missing_number_does_not_allow_ambiguity_partial_or_wrong_number(quote, originals):
    from src.services.answer_policy import UNSUPPORTED_ANSWER
    raw = json.dumps({'decision': 'answer', 'claims': [{'text': '每月更换。', 'quote': quote}]}, ensure_ascii=False)
    assert render_context_answer(raw, [{'id': 'S1', 'excerpt': originals}], '耗材维护周期怎样？') == UNSUPPORTED_ANSWER
