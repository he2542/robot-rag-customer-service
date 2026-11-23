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


def test_equivalent_range_format_does_not_change_an_existing_claim():
    text='拖布正常使用3至6个月更换，宠物环境1～2个月更换。'
    assert render(text)==text+' [S1]'


def test_existing_matching_cycle_and_condition_are_preserved():
    text='宠物环境下，拖布1-2个月更换。'
    assert render(text)==text+' [S1]'


def test_ordinary_troubleshooting_is_not_rewritten_by_cycle_rule():
    text='每周清理。'
    assert render(text,question='拖布脏了怎么办？')==text+' [S1]'


def test_recovered_cycle_entry_does_not_restore_dangerous_procedure():
    quote='1. 主刷轴承每月滴专用润滑油。'
    result=render('主刷轴承每周滴专用润滑油。',quote)
    assert '每月滴' not in result and '每周滴' not in result
    assert '专业售后' in result
