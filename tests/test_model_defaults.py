"""Model migration: no network, preserve explicit historical-model overrides."""
from types import SimpleNamespace

import pytest

from qa_pipeline_agent1 import OpenAIAgent1
from qa_pipeline_agent2 import OpenAIAgent2
from qa_pipeline_agent3 import OpenAIAgent3
from qa_pipeline_grounding import OpenAIGroundingReviewer


@pytest.mark.parametrize("agent_type", [OpenAIAgent1, OpenAIAgent2, OpenAIAgent3, OpenAIGroundingReviewer])
def test_model_default_and_override_precedence(monkeypatch, agent_type):
    client = SimpleNamespace()
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert agent_type(client=client).model == "gpt-6.1-sol"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-terra")
    assert agent_type(client=client).model == "gpt-5.6-terra"
    assert agent_type(model="gpt-6.1-sol", client=client).model == "gpt-6.1-sol"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    assert agent_type(model="gpt-5.6-terra", client=client).model == "gpt-5.6-terra"
