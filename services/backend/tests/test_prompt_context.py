import json

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
import pytest

from src.services.answer_policy import finalize_answer, normalize_citations, render_context_answer, quote_in_source, SAFETY_ANSWER, UNSUPPORTED_ANSWER
from src.services.context import EvidenceContextBuilder
from src.services.corpus import KnowledgeFile, internal_document_hash
from src.services.prompt_context import ContextLimits, PromptContextBuilder, byte_size, pack_evidence, recent_turns, source_items
from src.services.prompts import CONTEXT_SYSTEM_PROMPT
from src.services.rag import RagService


def prepared(text, fragments):
    file = KnowledgeFile("资料.txt", text, internal_document_hash(text, "资料.txt"))
    docs = [Document(id=str(i), page_content=fragment, metadata={
        "source": file.filename, "document_hash": file.document_hash, "chunk_index": i})
        for i, fragment in enumerate(fragments)]
    return EvidenceContextBuilder(lambda: [file], ()).build(docs).documents


def test_overlapping_entries_are_exactly_deduplicated_with_provenance():
    text = "# A型\n仅限干燥环境。\n1. 滤网不可水洗。\n2. 滤网完全晾干后装回。\n3. 其他。"
    docs = prepared(text, ["1. 滤网不可水洗。\n2. 滤网完全晾干", "2. 滤网完全晾干后装回。"])
    result = pack_evidence(docs, "滤网如何维护？", 12000)
    combined = "\n".join(d.page_content for d in result.documents)
    assert combined.count("2. 滤网完全晾干后装回。") == 1
    assert result.duplicates == 1 and "仅限干燥环境。" in combined and "不可水洗" in combined
    assert len(result.documents) == 1
    assert source_items(result.documents)[0]["source_spans"] == [{"start_line": 1, "end_line": 4}]


def test_different_conditions_and_negations_are_not_deduplicated():
    text = "# A型\n仅限A型。\n1. 滤网不得水洗。\n# B型\n仅限B型。\n1. 滤网允许水洗。"
    docs = prepared(text, [text])
    result = pack_evidence(docs, "滤网能水洗吗？", 12000)
    assert "仅限A型" in result.documents[0].page_content
    assert "仅限B型" in result.documents[0].page_content
    assert "不得水洗" in result.documents[0].page_content and "允许水洗" in result.documents[0].page_content
    assert result.duplicates == 0


def test_budget_selects_relevant_complete_entry_and_never_cuts_its_condition():
    text = "1. 其他功能。" + "其他内容。" * 200 + "\n2. 滤网维护：完全晾干，温度≤35℃，不得水洗。\n3. 其他。"
    docs = prepared(text, [text])
    result = pack_evidence(docs, "滤网维护", 650)
    assert result.evidence_bytes <= 650
    assert "2. 滤网维护：完全晾干，温度≤35℃，不得水洗。" in result.documents[0].page_content
    assert result.dropped_units >= 1 and "1. 其他功能" not in result.documents[0].page_content


def test_oversized_unstructured_evidence_is_omitted_instead_of_truncated():
    result = pack_evidence([Document(page_content="不可删除条件" * 1000)], "条件", 100)
    assert not result.documents and result.dropped_units == 1


def test_history_retains_recent_whole_turns_and_does_not_mutate_storage():
    messages = [HumanMessage("型号A，更正为B"), AIMessage("确认B"), HumanMessage("最新问题"), AIMessage("最新结果")]
    selected = recent_turns(messages, 160)
    assert [m.content for m in selected] == ["最新问题", "最新结果"]
    assert len(messages) == 4
    assert recent_turns([SystemMessage("历史指令"), AIMessage("孤立回答"), HumanMessage("未完成")], 1000) == []


def test_full_serialized_input_including_escaping_and_history_stays_in_budget():
    limits = ContextLimits(total=4500, evidence=1800, history=1000)
    builder = PromptContextBuilder("固定规则。", limits)
    question = '\x00"\\😀' * 80
    docs = [Document(page_content='引号"与反斜杠\\不可省略条件。' * 70), Document(page_content="小片段完整条件。")]
    evidence = builder.evidence(question, docs)
    history = [HumanMessage("旧问题" * 100), AIMessage("旧答案" * 100), HumanMessage("近期"), AIMessage("更正")]
    value, diagnostic = builder.messages(question, evidence.documents, history)
    payload = json.loads(value["request_payload"])
    assert payload["question"] == question and payload["references"] == source_items(evidence.documents)
    assert diagnostic["input_bytes"] <= limits.total
    assert evidence.evidence_bytes <= limits.evidence
    assert len(value["history"]) % 2 == 0
    assert all(len(d.page_content) in [len(x.page_content) for x in docs] for d in evidence.documents)


@pytest.mark.parametrize("bad", [-1, 1.5, True])
def test_invalid_byte_limits_fail_explicitly(bad):
    with pytest.raises(ValueError):
        ContextLimits(total=bad)


def test_oversized_current_question_is_not_silently_modified():
    with pytest.raises(ValueError, match="exceed"):
        PromptContextBuilder("系统规则", ContextLimits(total=100)).messages("问题" * 100, [], [])


def test_group_citations_are_normalized_but_item_numbers_are_never_guessed():
    text = "事实[S1, S2]；错误[如S3-1、S3-2等]，裸号S3-109，未知[S9]；[提示]保留。"
    clean = normalize_citations(text, {"S1", "S2", "S3"})
    assert "[S1][S2]" in clean and "S3-" not in clean and "S9" not in clean and "[提示]" in clean
    assert finalize_answer("明确结论但没有引用。", {"S1"}) == UNSUPPORTED_ANSWER
    assert finalize_answer("请提供具体型号？", {"S1"}) == "请提供具体型号？"


@pytest.mark.parametrize("answer", [
    "关闭电源，重新插拔电池。不要拆解电池[S1]。",
    "检查拖布电机是否有卡顿，失败后联系售后[S1]。",
    "用手轻拉确认连接处是否牢固[S1]。",
    "关闭过度碰撞保护，再重启[S1]。",
])
def test_explicit_prohibited_action_cannot_be_undone_by_a_later_disclaimer(answer):
    assert finalize_answer(answer, {"S1"}) == SAFETY_ANSWER


@pytest.mark.parametrize("answer", [
    "不要重新插拔电池，联系专业售后[S1]。",
    "电机轴承可能异常，请专业人员检查[S1]。",
    "检查滤网是否堵塞，按说明清洁[S1]。",
    "充电触点有灰尘，先断电并用干布清洁[S1]。",
])
def test_normal_evidence_and_prohibitions_are_not_blocked(answer):
    assert finalize_answer(answer, {"S1"}) == answer


def test_visible_validated_answer_is_stored_and_sessions_keep_native_roles():
    histories, prompts = {}, []
    def history(session):
        return histories.setdefault(session, InMemoryChatMessageHistory())
    class Retriever:
        def invoke(self, question):
            return [Document(page_content="资料不足，内部部件需要售后检查。")]
    def model(value):
        prompts.append(value.to_messages())
        return json.dumps({"decision": "answer", "claims": [
            {"text": "检查拖布电机是否有卡顿。", "quote": "资料不足，内部部件需要售后检查。"}]}, ensure_ascii=False)
    service = RagService(Retriever(), RunnableLambda(model), history, context_entries_enabled=True,
                         context_builder=EvidenceContextBuilder(lambda: [], ()))
    events = list(service.stream_answer("拖布异响", "A"))
    visible = "".join(e.get("content", "") for e in events)
    assert "专业售后检查项：" in visible and "[S1]" in visible
    assert histories["A"].messages[-1].content == visible
    assert prompts[0][0].content == CONTEXT_SYSTEM_PROMPT
    list(service.stream_answer("独立问题", "B"))
    assert len(prompts[1]) == 2 and len(histories["A"].messages) == 2


def test_structured_claims_render_real_sources_and_preserve_conflicting_conditions():
    raw = json.dumps({"decision": "conflict", "claims": [
        {"text": "A型不得水洗。", "quote": "A型不得水洗。"},
        {"text": "B型按说明可水洗。", "quote": "B型按说明可水洗。"}]}, ensure_ascii=False)
    assert render_context_answer(raw, [{"id":"S1","excerpt":"A型不得水洗。"},{"id":"S2","excerpt":"B型按说明可水洗。"}]) == "资料中的适用条件或说明存在差异：\n\nA型不得水洗。 [S1]\n\nB型按说明可水洗。 [S2]"


@pytest.mark.parametrize("value", [
    {"decision": "answer", "claims": [{"text": "结论", "sources": []}]},
    {"decision": "answer", "claims": [{"text": "结论", "sources": ["S99"]}]},
    {"decision": "answer", "claims": [{"text": "结论", "sources": ["S1-7"]}]},
    {"decision": "answer", "claims": "结论"},
    {"decision": "clarify", "question": "不带来源的陈述"},
])
def test_malformed_claims_never_receive_a_guessed_citation(value):
    assert render_context_answer(json.dumps(value), {"S1"}) == UNSUPPORTED_ANSWER


def test_clarification_and_referral_do_not_expose_internal_json():
    assert render_context_answer('{"decision":"clarify","question":"具体型号是什么？"}', {"S1"}) == "具体型号是什么？"
    assert "专业售后" in render_context_answer('{"decision":"refer","claims":[]}', {"S1"})
    assert "不足以确认" in render_context_answer('{"decision":"insufficient","claims":[]}', {"S1"})


def test_history_names_and_tool_payloads_cannot_bypass_the_budget():
    history = [HumanMessage("问题", name="x" * 10000), AIMessage("回答", additional_kwargs={"tool_calls": [{"id": "x" * 10000}]})]
    result = recent_turns(history, 300)
    assert [m.content for m in result] == ["问题", "回答"]
    assert all(not m.name and not m.additional_kwargs for m in result)


def test_quote_must_be_literal_and_cannot_be_replaced_with_a_made_up_source_id():
    refs = [{"id": "S1", "excerpt": "滤网完全晾干后再装回。"}]
    valid = {"decision": "answer", "claims": [{"text": "滤网完全晾干再装回。", "quote": "滤网完全晾干后再装回。", "sources": ["S99"]}]}
    assert "[S1]" in render_context_answer(json.dumps(valid, ensure_ascii=False), refs)
    valid["claims"][0]["quote"] = "用加热器烘干后装回。"
    assert render_context_answer(json.dumps(valid, ensure_ascii=False), refs) == UNSUPPORTED_ANSWER


def test_quote_formatting_does_not_relax_conditions_negation_or_numbers():
    assert quote_in_source("- 一次性拖布为单次使用，随用随换。", "可水洗拖布3-6个月更换；一次性拖布为单次使用，随用随换。")
    assert quote_in_source("温度≤35℃，不得水洗。", "**温度≤35℃，不得水洗。**")
    assert not quote_in_source("温度≤50℃，不得水洗。", "温度≤35℃，不得水洗。")
    assert not quote_in_source("温度≤35℃，可以水洗。", "温度≤35℃，不得水洗。")
    assert not quote_in_source("编号10", "编号1 0")
    assert not quote_in_source("** ** ** **", "任何正文")


def test_identical_text_in_different_model_files_keeps_both_applicability_scopes():
    docs = [Document(page_content="安装后必须完全晾干。", metadata={"source": name}) for name in ["A型号.txt", "B型号.txt"]]
    result = pack_evidence(docs, "B型号", 2000)
    assert len(result.documents) == 2 and result.duplicates == 0


def test_one_unsafe_or_unverifiable_claim_does_not_erase_supported_safe_advice():
    refs = [{"id": "S1", "excerpt": "先断电，再清理滤网杂物。给电机轴承加润滑油。"}]
    raw = {"decision": "answer", "claims": [
        {"text": "先断电，再清理滤网杂物。", "quote": "先断电，再清理滤网杂物。"},
        {"text": "给电机轴承加润滑油。", "quote": "给电机轴承加润滑油。"},
        {"text": "用加热器烘干。", "quote": "用加热器烘干。"}]}
    result = render_context_answer(json.dumps(raw, ensure_ascii=False), refs)
    assert "先断电，再清理滤网杂物。 [S1]" in result
    assert SAFETY_ANSWER in result and "给电机轴承加润滑油" not in result
    assert "用加热器烘干" not in result


@pytest.mark.parametrize("question", ["\x00" * 4000, "😀" * 4000], ids=["control-4000", "emoji-4000"])
def test_maximum_api_question_is_preserved_with_default_input_budget(question):
    builder = PromptContextBuilder(CONTEXT_SYSTEM_PROMPT)
    evidence = builder.evidence(question, [Document(page_content="保留完整条件。" * 500)])
    value, diagnostic = builder.messages(question, evidence.documents,
        [HumanMessage("历史" * 1000), AIMessage("记录" * 1000)])
    assert json.loads(value["request_payload"])["question"] == question
    assert diagnostic["input_bytes"] <= 32 * 1024


def test_confirmed_abnormal_symptoms_do_not_permit_charging_retry():
    refs = [{"id": "S1", "excerpt": "开机后立即自动关机，可能因电量耗尽或过热；应先充满电重试。"}]
    raw = {"decision": "answer", "claims": [{"text": refs[0]["excerpt"], "quote": refs[0]["excerpt"]}]}
    result = render_context_answer(json.dumps(raw, ensure_ascii=False), refs, "一开机就报警关机怎么处理？")
    assert result.startswith("请先停止使用和充电")
    assert "可能因电量耗尽或过热" in result and "应先充满电重试" not in result


def test_wiring_inspection_is_explicitly_assigned_to_professionals():
    refs = [{"id": "S1", "excerpt": "每月检查拖地模组的电线排线，确保无破损、松动。"}]
    raw = {"decision": "answer", "claims": [{"text": refs[0]["excerpt"], "quote": refs[0]["excerpt"]}]}
    result = render_context_answer(json.dumps(raw, ensure_ascii=False), refs, "电线排线平时要注意啥？")
    assert result.startswith("先断电") and "不要拉扯" in result
    assert "专业售后检查项：" in result


def test_charging_component_names_are_not_instructions_to_continue_charging():
    text = "充电座发热严重可能因通风不良、非原装充电座或存在短路问题。"
    refs = [{"id": "S1", "excerpt": text}]
    raw = {"decision": "answer", "claims": [{"text": text, "quote": text}]}
    result = render_context_answer(json.dumps(raw, ensure_ascii=False), refs, "充电座烫得厉害，可能是什么原因？")
    assert result.startswith("请先停止使用和充电") and text + " [S1]" in result


@pytest.mark.parametrize("question", ["电池选什么类型", "拖布有异味怎么清洁", "电源线长度是多少", "电机功率是多少"])
def test_normal_topics_do_not_trigger_symptom_specific_referral(question):
    from src.services.answer_policy import operation_boundary
    assert operation_boundary(question) == ""
