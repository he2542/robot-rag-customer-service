import json
from langchain_core.documents import Document
from src.services.evidence_navigation import navigation
from src.services.prompt_context import ContextLimits, PromptContextBuilder, source_items
from src.services.prompts import CONTEXT_SYSTEM_PROMPT, NAVIGATION_CONTEXT_SYSTEM_PROMPT

def test_navigation_points_to_real_full_line_and_does_not_rewrite_sources():
    sources=[{'id':'S1','excerpt':'1. 电池寿命。\n90. 语言支持：APP支持多语言切换。'}]
    before=json.dumps(sources,ensure_ascii=False)
    result=navigation('APP支持哪些语言？',sources)
    assert result[0]=={'source_id':'S1','excerpt_line':2,'label':'90. 语言支持：APP支持多语言切换。'}
    assert json.dumps(sources,ensure_ascii=False)==before

def test_combined_model_question_ranks_a_matching_qa_header_first():
    sources=[{'id':'S1','excerpt':'7. 集尘袋耗材维护。\n8. 清洁刷自动洗拖布。'},
             {'id':'S2','excerpt':'62. **自动集尘+自动洗拖布机型的耗材如何搭配更换？**\n- 集尘袋1-2个月更换一次。'}]
    assert navigation('自动集尘又带自动洗拖布功能的机型，各类耗材的维护节奏是怎样的？',sources)[0]['source_id']=='S2'

def test_duplicate_item_numbers_keep_source_and_line_identity():
    sources=[{'id':'S1','excerpt':'1. 滤网不可水洗。\n1. 滤网允许水洗。'},
             {'id':'S2','excerpt':'1. 滤网完全晾干。'}]
    pointers=navigation('滤网水洗',sources)
    assert len({(p['source_id'],p['excerpt_line']) for p in pointers})==len(pointers)
    assert len(pointers)==3

def test_disabled_builder_preserves_existing_payload():
    doc=Document(page_content='1. 滤网不可水洗。',metadata={'source':'资料.txt'})
    result,_=PromptContextBuilder(CONTEXT_SYSTEM_PROMPT).messages('滤网',[doc],[])
    assert json.loads(result['request_payload'])=={'question':'滤网','references':source_items([doc])}

def test_navigation_does_not_remove_conflicting_evidence_and_counts_budget():
    docs=[Document(page_content='1. A型滤网不可水洗。',metadata={'source':'A.txt'}),
          Document(page_content='1. B型滤网允许水洗。',metadata={'source':'B.txt'})]
    builder=PromptContextBuilder(NAVIGATION_CONTEXT_SYSTEM_PROMPT,navigation_enabled=True)
    prepared,diagnostic=builder.messages('滤网能水洗吗？',docs,[])
    data=json.loads(prepared['request_payload'])
    assert data['references']==source_items(docs)
    assert {p['source_id'] for p in data['entry_navigation']}=={'S1','S2'}
    assert diagnostic['input_bytes']<=builder.limits.total

def test_navigation_and_escaping_fit_the_serialized_total_budget():
    docs=[Document(page_content='1. 滤网"维护\\条件。'*50,metadata={'source':'资料.txt'})]
    builder=PromptContextBuilder('固定规则',ContextLimits(total=1800,evidence=1500),navigation_enabled=True)
    packed=builder.evidence('滤网',docs)
    _,diagnostic=builder.messages('滤网',packed.documents,[])
    assert diagnostic['input_bytes']<=1800
