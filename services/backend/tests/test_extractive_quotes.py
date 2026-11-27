import json
import pytest
from src.services.answer_policy import render_context_answer, SAFETY_ANSWER, UNSUPPORTED_ANSWER


def render(question,text,quote,excerpt=None):
    raw=json.dumps({'decision':'answer','claims':[{'text':text,'quote':quote}]},ensure_ascii=False)
    return render_context_answer(raw,[{'id':'S1','excerpt':quote if excerpt is None else excerpt}],question,extractive_quotes=True)


def test_extract_full_evidence_retains_preceding_operation_and_numbers():
    quote='关闭门窗减少灰尘进入，在APP中设置大吸力和中档出水量，适当降低清扫频次。'
    answer=render('怎样减少扫拖频次？','在APP中设置大吸力。',quote)
    assert answer==quote+' [S1]'


def test_extract_discards_generated_unsupported_specifics():
    quote='APP支持多语言切换，适合外籍人士使用。'
    answer=render('APP支持哪些语言？','支持英语和法语。',quote)
    assert answer==quote+' [S1]' and '英语' not in answer


def test_extract_does_not_restore_repair_steps_user_already_tried():
    quote='若无法修改参数，可重启APP并解锁设置。'
    answer=render('我已经重启APP，下一步怎么做？','解锁设置。',quote)
    assert answer=='解锁设置。 [S1]'


def test_unverified_quote_is_still_rejected():
    answer=render('如何操作？','检查滤网。','检查滤网并晾干后使用。',excerpt='资料没有该步骤。')
    assert answer==UNSUPPORTED_ANSWER


def test_battery_removal_in_quote_is_not_hidden_by_safe_generated_text():
    quote='电池长时间不用时，充至50%-70%后拆卸存放。'
    assert render('长期怎么存放？','每月补电即可。',quote)==SAFETY_ANSWER


def test_no_steps_are_invented_when_copying_a_complete_entry():
    quote='关闭拖地功能，防止浸湿长毛地毯导致发霉。'
    answer=render('长毛地毯如何防霉？','清洗所有配件并消毒。',quote)
    assert '消毒' not in answer and answer==quote+' [S1]'


def test_structured_internal_inspection_keeps_the_professional_role_across_targets():
    quote='故障现象：噪音过大；检测：主刷是否缠绕杂物，轮组是否卡顿，电机是否故障；修复：清理缠绕物，电机异响则联系售后。'
    result=render('工作时噪音大怎么处理？','清理主刷。',quote)
    assert result.startswith('专业售后检查项：') and '电机是否故障' in result


def test_structured_accessible_cleaning_does_not_require_internal_service():
    quote='故障现象：吸力下降；检测：尘盒是否满，滤网是否堵塞；修复：清理尘盒和滤网。'
    result=render('吸力下降怎么处理？','清理滤网。',quote)
    assert result==quote+' [S1]'


def test_professional_role_is_not_duplicated_after_clause_level_checking():
    quote='故障现象：机身发热严重，有异味；检测：电机是否过载，电池是否短路，风道是否堵塞；修复：立即关机冷却，清理风道，联系售后检测电机和电池。'
    result=render('外壳烫手有怪味，提示哪些问题？','电机可能过载。',quote)
    assert result.count('专业售后检查项：')==1
