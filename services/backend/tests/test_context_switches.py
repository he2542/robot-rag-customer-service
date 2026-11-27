import runpy
from pathlib import Path
import pytest
import dotenv
from langchain_core.runnables import RunnableLambda
from src import config
from src.services.rag import RagService
from src.services.prompts import EXTRACTIVE_CONTEXT_SYSTEM_PROMPT


@pytest.mark.parametrize('name,attribute',[
    ('RAG_CONTEXT_NAVIGATION_ENABLED','context_navigation_enabled'),
    ('RAG_CONTEXT_EXTRACTIVE_QUOTES','context_extractive_quotes'),
])
@pytest.mark.parametrize('value,expected',[('true',True),('false',False),('TRUE',True)])
def test_context_switches_parse_booleans_without_reading_user_env(monkeypatch,name,attribute,value,expected):
    monkeypatch.setattr(dotenv,'load_dotenv',lambda *a,**k:False)
    monkeypatch.setenv(name,value)
    values=runpy.run_path(str(Path(config.__file__)))
    assert values[attribute] is expected


@pytest.mark.parametrize('name',['RAG_CONTEXT_NAVIGATION_ENABLED','RAG_CONTEXT_EXTRACTIVE_QUOTES'])
def test_context_switches_reject_misspelled_values(monkeypatch,name):
    monkeypatch.setattr(dotenv,'load_dotenv',lambda *a,**k:False)
    monkeypatch.setenv(name,'yes')
    with pytest.raises(ValueError,match=name):runpy.run_path(str(Path(config.__file__)))


def test_service_uses_config_with_explicit_test_override(monkeypatch):
    monkeypatch.setattr(config,'context_navigation_enabled',True)
    monkeypatch.setattr(config,'context_extractive_quotes',True)
    model=RunnableLambda(lambda _: '')
    service=RagService(object(),model,context_entries_enabled=True)
    assert service.prompt_context.navigation_enabled and service.context_extractive_quotes
    assert service.context_system_prompt==EXTRACTIVE_CONTEXT_SYSTEM_PROMPT
    control=RagService(object(),model,context_entries_enabled=True,context_navigation_enabled=False,context_extractive_quotes=False)
    assert not control.prompt_context.navigation_enabled and not control.context_extractive_quotes
