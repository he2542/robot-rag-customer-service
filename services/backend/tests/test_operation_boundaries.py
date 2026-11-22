import json

import pytest

from src.services.answer_policy import operation_boundary, render_context_answer, SAFETY_ANSWER


def render(text,question='机器人运行时有异响，该怎么处理？'):
    return render_context_answer(json.dumps({'decision':'answer','claims':[{'text':text,'quote':text}]},ensure_ascii=False),
                                 [{'id':'S1','excerpt':text}],question)


@pytest.mark.parametrize('text',[
    '主刷轴承生锈导致旋转卡顿，可滴专用润滑油处理。',
    '主刷轴承生锈导致旋转卡顿，应检测是否进水或长期未维护；修复方法为滴专用润滑油。',
    '轴承卡顿，可滴1滴专用润滑油，无法缓解则更换主刷。',
    '电机轴承卡顿，建议加注润滑脂。',
    '不要重启，轴承卡顿时可滴专用润滑油。',
    '轴承卡顿，先滴专用润滑油，之后联系专业售后。',
    '轴承卡顿，可滴专用润滑油后联系专业售后。',
])
def test_reject_lubrication_with_target_in_previous_clause(text):
    assert render(text)==SAFETY_ANSWER


@pytest.mark.parametrize('text',[
    '主刷轴承卡顿，不要自行滴专用润滑油，应联系专业售后。',
    '主刷轴承卡顿，由专业售后加注润滑脂。',
    '清理尘盒毛发，保持滤网干燥。',
    '轴承的问题由售后处理。清理尘盒中的油污。',
])
def test_preserve_prohibitions_professional_role_and_routine_cleaning(text):
    assert text in render(text) and '[S1]' in render(text)


@pytest.mark.parametrize('question',[
    '按课程资料的选购建议，这台设备的电机有没有防止过热或过载损坏的保护措施？',
    '电机支持过热保护吗？',
    '过热保护功能有什么作用？',
    '过热保护怎么工作？',
])
def test_feature_question_does_not_claim_an_existing_fault(question):
    assert operation_boundary(question)==''
    text='电机带过热、过载保护，避免长时间高负荷工作损坏。'
    result=render(text,question)
    assert result==text+' [S1]'


@pytest.mark.parametrize('question',[
    '机器已经过热了，怎么办？',
    '机器人运行时过热，有过热保护吗？',
    '刚触发过热保护并停机，该怎么处理？',
    '有没有过热保护？现在外壳烫手还有异味。',
    '电池故障了，能继续充电吗？',
])
def test_actual_fault_wins_over_feature_wording(question):
    assert '停止使用和充电' in operation_boundary(question)
