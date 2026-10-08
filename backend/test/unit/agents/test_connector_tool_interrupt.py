"""真实 LangGraph ToolNode 注入身份并传播连接器 interrupt。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from yuxi.agents.connectors.tools import get_connector_tools
from yuxi.services.connectors.service import ConnectorApprovalRequired
from yuxi.services.connectors.base import ConnectorExecution


@pytest.mark.asyncio
async def test_tool_schema_preserves_nested_constraints_and_raw_parameter_types():
    """完整 schema 传给模型，发送前校验必须看到原始类型和额外字段。"""
    from yuxi.services.connectors.schemas import validate_params, ConnectorSchemaError

    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "minimum": 1},
            "choice": {"type": "object", "properties": {"kind": {"enum": ["A", "B"]}}, "required": ["kind"]},
        },
        "required": ["count", "choice"],
        "additionalProperties": True,
    }
    service = AsyncMock()
    service.get_connector_metadata.return_value = {"operations": [{"slug": "read", "request_schema": schema}]}
    observed = []

    async def execute(_connector, _operation, params, **_kwargs):
        observed.append(params)
        validate_params(params, schema)
        return {"invocation_id": "invocation", "success": True, "data": params}

    service.prepare_and_execute.side_effect = execute
    context = SimpleNamespace(connectors=["crm"], uid="actor", run_id="run", request_id="request")
    with patch("yuxi.services.connectors.factory.get_connector_service", return_value=service):
        tool = (await get_connector_tools(context))[0]
    model_schema = tool.tool_call_schema
    assert isinstance(model_schema, dict)
    assert model_schema["properties"] == schema["properties"]
    builder = StateGraph(MessagesState, context_schema=object)
    builder.add_node("tools", ToolNode([tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    valid = {"count": 1, "choice": {"kind": "A"}, "trace": "keep-this-field"}
    await graph.ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call",
                            "name": tool.name,
                            "args": valid,
                        }
                    ],
                )
            ]
        },
        context=context,
    )
    assert observed[-1] == valid
    with pytest.raises(ConnectorSchemaError):
        await graph.ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "bad-call",
                                "name": tool.name,
                                "args": {**valid, "count": "1"},
                            }
                        ],
                    )
                ]
            },
            context=context,
        )
    assert observed[-1]["count"] == "1"


def test_connector_interrupt_has_its_own_stream_payload():
    """连接器批准必须显示指定调用，不能变成虚构的选择问题。"""
    from yuxi.services.chat_service import build_pending_interrupt_payload

    result = build_pending_interrupt_payload(
        {
            "type": "connector_approval",
            "invocation_id": "invocation",
            "digest": "digest",
        },
        "thread",
    )
    assert result == {
        "status": "connector_approval_required",
        "invocation_id": "invocation",
        "digest": "digest",
        "thread_id": "thread",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", ["approval", "unknown"])
async def test_tool_node_uses_injected_call_id_and_interrupts_until_persisted_approval(initial):
    """interrupt 不得变为普通工具输出，恢复复用原 tool_call_id。"""
    service = AsyncMock()
    service.resolve_agent_execution.return_value = ConnectorExecution(
        invocation_id="invocation",
        actor_uid="actor",
        consumer_type="agent",
        logical_call_key="agent:request:injected-call",
        connector_revision=1,
        operation_revision=1,
        agent_request_id="request",
        agent_run_id="run",
        tool_call_id="injected-call",
    )
    service.get_connector_metadata.return_value = {
        "operations": [
            {
                "slug": "write",
                "operation_type": "write",
                "http_method": "POST",
                "connector_revision": 1,
                "operation_revision": 1,
            }
        ]
    }
    service.prepare_and_execute.side_effect = [
        ConnectorApprovalRequired("invocation", "digest", None)
        if initial == "approval"
        else {"invocation_id": "invocation", "success": False, "remote_outcome": "unknown"},
        {"invocation_id": "invocation", "success": True, "data": {"saved": True}},
    ]
    service.get_user_invocation.return_value = {"request_digest": "digest", "request_summary": {"target": "synthetic"}}
    context = SimpleNamespace(connectors=["crm"], uid="actor", run_id="run", request_id="request")
    with patch("yuxi.services.connectors.factory.get_connector_service", return_value=service):
        tools = await get_connector_tools(context)
    builder = StateGraph(MessagesState, context_schema=object)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "test-tool-thread"}}
    result = await graph.ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "injected-call",
                            "name": tools[0].name,
                            "args": {},
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        },
        config,
        context=context,
    )
    assert result["__interrupt__"][0].value["invocation_id"] == "invocation"
    assert service.resolve_agent_execution.call_args.kwargs["tool_call_id"] == "injected-call"
    execution = service.prepare_and_execute.call_args.kwargs["execution"]
    assert execution.tool_call_id == "injected-call"
    assert execution.logical_call_key == "agent:request:injected-call"
    result = await graph.ainvoke(Command(resume={"invocation_id": "invocation"}), config, context=context)
    assert "__interrupt__" not in result
    assert json.loads(result["messages"][-1].content)["result"] == {"saved": True}
    executions = [call.kwargs["execution"] for call in service.prepare_and_execute.call_args_list]
    assert {execution.logical_call_key for execution in executions} == {"agent:request:injected-call"}
