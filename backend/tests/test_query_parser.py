import json
from types import SimpleNamespace

import pytest

from backend.services.chat import query_parser
from backend.services.chat.intent import Intent
from backend.services.chat.query_parser import (
    _TOOLS,
    _declare,
    _parse_call,
    rewrite_query,
)
from backend.services.chat.timerange import TimeRange, TimeRangeKind
from backend.services.llm.generation import ToolCall


def call(name: str, **args) -> ToolCall:
    return ToolCall(name=name, args=args)


@pytest.fixture
def generator(monkeypatch):
    """rewrite_query가 생성 모델에 넘긴 도구를 담고, 정해 둔 호출을 돌려주게 한다."""
    sent: dict = {}
    reply = SimpleNamespace(calls=[])

    def choose_tool(system, messages, tools):
        sent.update(system=system, messages=messages, tools=tools)
        return reply.calls

    fake = SimpleNamespace(model="test-model", choose_tool=choose_tool)
    monkeypatch.setattr(query_parser, "get_generator", lambda: fake)
    return SimpleNamespace(sent=sent, reply=reply)


def test_search_history_becomes_recall_with_its_period_and_count():
    parsed = _parse_call(
        [call("search_history", time_range={"kind": "yesterday"}, query="리액트 상태관리", desired_count=3)],
        "어제 본 리액트 상태관리 글 3개만",
    )

    assert parsed.intent is Intent.RECALL
    assert parsed.query == "리액트 상태관리"
    assert parsed.time_range.kind is TimeRangeKind.YESTERDAY
    assert parsed.desired_count == 3
    assert parsed.target_index is None


def test_search_history_without_a_period_has_none():
    parsed = _parse_call([call("search_history", query="파이썬 비동기")], "파이썬 비동기 글 찾아줘")

    assert parsed.time_range == TimeRange()


def test_show_detail_carries_the_index_and_uses_the_title_hint_as_query():
    parsed = _parse_call([call("show_detail", target_index=2, title_hint="된장찌개")], "두 번째 것 자세히")

    assert parsed.intent is Intent.DETAIL
    assert parsed.target_index == 2
    assert parsed.query == "된장찌개"


def test_build_dashboard_keeps_the_period_and_the_raw_message():
    parsed = _parse_call(
        [call("build_dashboard", time_range={"kind": "this_month"})], "이번 달 사이트별로 몇 개 봤어"
    )

    assert parsed.intent is Intent.DASHBOARD
    assert parsed.time_range.kind is TimeRangeKind.THIS_MONTH
    assert parsed.query == "이번 달 사이트별로 몇 개 봤어"


def test_chat_becomes_etc_with_the_raw_message():
    parsed = _parse_call([call("chat")], "안녕")

    assert parsed.intent is Intent.ETC
    assert parsed.query == "안녕"


def test_only_the_first_of_several_calls_is_used():
    parsed = _parse_call([call("chat"), call("search_history", query="김치찌개")], "안녕")

    assert parsed.intent is Intent.ETC


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [call("delete_everything")],
        [call("show_detail", title_hint="된장찌개")],  # target_index 누락
        [call("search_history", query="x", time_range={"kind": "next_year"})],
    ],
    ids=["no call", "unknown tool", "missing argument", "invalid enum"],
)
def test_unreadable_calls_give_none(calls):
    assert _parse_call(calls, "아무 말") is None


def test_every_tool_is_declared_with_a_description_and_no_refs():
    for tool in _TOOLS:
        declaration = _declare(tool)

        assert declaration.description
        assert "$ref" not in json.dumps(declaration.parameters or {})


def test_argument_descriptions_reach_the_declared_schema():
    search = _declare(next(tool for tool in _TOOLS if tool.name == "search_history"))
    properties = search.parameters["properties"]

    assert "time_range" in properties["query"]["description"]
    assert "recent_days" in properties["time_range"]["properties"]["kind"]["description"]
    # 하위 모델을 풀어 넣어도 필드에 붙인 설명이 정의 쪽 설명보다 앞선다.
    assert properties["time_range"]["description"] == "찾을 기록의 기간."


def test_a_tool_without_arguments_declares_no_parameters():
    chat = _declare(next(tool for tool in _TOOLS if tool.name == "chat"))

    assert chat.parameters is None


def test_rewrite_query_offers_every_tool_and_returns_the_parsed_call(generator):
    generator.reply.calls = [call("search_history", query="김치찌개 레시피")]

    parsed = rewrite_query("김치찌개 레시피 찾아줘")

    assert [tool.name for tool in generator.sent["tools"]] == [tool.name for tool in _TOOLS]
    assert generator.sent["messages"][-1].text == "김치찌개 레시피 찾아줘"
    assert parsed.intent is Intent.RECALL
    assert parsed.query == "김치찌개 레시피"


def test_rewrite_query_falls_back_to_etc_when_no_tool_is_called(generator):
    generator.reply.calls = []

    parsed = rewrite_query("김치찌개 레시피 찾아줘")

    assert parsed.intent is Intent.ETC
    assert parsed.query == "김치찌개 레시피 찾아줘"
