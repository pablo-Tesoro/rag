"""Runs one evaluation case through the real agent graph and records what happened.

The case runs in-process on the same graph and dependencies as the API (`agent_deps`), with
two differences: incidents go to a sandbox, and conversations live in an in-memory
checkpointer. The run records everything the checks and the judge need: the final answer,
every tool call the model attempted, what was retrieved, the tool results the model saw
(the evidence for the judge), how the approval went, tokens and latency. When tracing is
on, it also records the id of each traced invocation, to go from a failed case to its trace.

The harness answers approval interrupts itself: with the case's decision the first time,
and with a rejection for anything else (it never approves a write it was not told to).
"""

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.callbacks import Callbacks
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from bank_assistant.agent.graph import AgentDeps, build_graph
from bank_assistant.agent.schemas import ANSWER_TOOL
from bank_assistant.agent.state import AgentContext, AgentState
from bank_assistant.identity import Employee
from bank_assistant.retrieval import RetrievalMode
from evals.sandbox import SandboxIncidents
from evals.schema import EvalCase

MAX_APPROVAL_ROUNDS = 3  # a model that keeps proposing incidents is cut off here


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class RetrievedRecord:
    doc_id: str
    section: str
    status: str


@dataclass
class CaseRun:
    case_id: str
    repeat: int
    thread_id: str
    answer: dict[str, Any] | None = None
    # Every call the model attempted except `responder`, in order, proposals included.
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    retrieved: list[RetrievedRecord] = field(default_factory=list)
    evidence: str = ""  # the tool results the model saw and the approval decisions
    proposals: list[dict[str, Any]] = field(default_factory=list)  # incidents it proposed
    decisions: dict[str, bool] = field(default_factory=dict)  # tool call id -> approved
    incidents_before_decision: int | None = None  # written when the first proposal paused
    incidents_created: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    error: str | None = None
    trace_ids: list[str] = field(default_factory=list)  # one per invocation (turn or resume)


async def run_case(
    deps: AgentDeps,
    case: EvalCase,
    employee: Employee,
    *,
    mode: RetrievalMode,
    repeat: int = 1,
    recursion_limit: int = 20,
    metadata: dict[str, Any] | None = None,
    callbacks: Callbacks = None,
) -> CaseRun:
    sandbox = SandboxIncidents()
    graph = build_graph(replace(deps, incidents=sandbox), checkpointer=InMemorySaver())
    thread_id = f"eval-{case.id}-{repeat}-{uuid.uuid4().hex[:8]}"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": recursion_limit,
        "run_name": "eval_case",
        "tags": ["eval", case.id],
        # LangSmith groups the runs of a conversation by `thread_id`.
        "metadata": {
            "case_id": case.id,
            "repeat": repeat,
            "thread_id": thread_id,
            **(metadata or {}),
        },
        "callbacks": callbacks,
    }
    context = AgentContext(employee=employee, retrieval_mode=mode)
    run = CaseRun(case_id=case.id, repeat=repeat, thread_id=thread_id)

    def traced(config: RunnableConfig) -> RunnableConfig:
        trace_id = uuid.uuid4()
        run.trace_ids.append(str(trace_id))
        return {**config, "run_id": trace_id}

    started = time.perf_counter()
    try:
        state: AgentState = {
            "messages": [HumanMessage(case.question)],
            "employee_id": employee.id,
            "retrieved": {},
            "final_answer": None,
        }
        result: dict[str, Any] = await graph.ainvoke(state, traced(config), context=context)
        rounds = 0
        while result.get("__interrupt__"):
            rounds += 1
            if rounds > MAX_APPROVAL_ROUNDS:
                raise RuntimeError(f"more than {MAX_APPROVAL_ROUNDS} incident proposals")
            proposal = result["__interrupt__"][0].value
            run.proposals.append(proposal["args"])
            first = rounds == 1
            if first:
                run.incidents_before_decision = sandbox.created
            approve = first and case.approval is not None and case.approval.decision == "approve"
            run.decisions[proposal["tool_call_id"]] = approve
            command: Command[Any] = Command(resume={"approved": approve})
            result = await graph.ainvoke(command, traced(config), context=context)
        _record_final_state(run, result)
    except Exception as error:  # the run is reported as an error, not as a quality failure
        run.error = f"{type(error).__name__}: {str(error)[:300]}"
    run.incidents_created = sandbox.created
    run.latency_s = time.perf_counter() - started
    return run


def _record_final_state(run: CaseRun, result: dict[str, Any]) -> None:
    messages: list[AnyMessage] = result["messages"]
    run.answer = result.get("final_answer")
    run.retrieved = [
        RetrievedRecord(ref["doc_id"], ref["section"], ref["status"])
        for ref in (result.get("retrieved") or {}).values()
    ]
    evidence = []
    for message in messages:
        if isinstance(message, AIMessage):
            run.llm_calls += 1
            if message.usage_metadata:
                run.input_tokens += message.usage_metadata["input_tokens"]
                run.output_tokens += message.usage_metadata["output_tokens"]
            run.tool_calls += [
                ToolCallRecord(call["name"], dict(call["args"]))
                for call in message.tool_calls
                if call["name"] != ANSWER_TOOL
            ]
        elif isinstance(message, ToolMessage) and message.name != ANSWER_TOOL:
            decision = run.decisions.get(message.tool_call_id)
            if decision is not None:
                # The judge must know a human approved (or rejected) before the write:
                # otherwise "incident registered" reads as a skipped confirmation.
                verb = "aprobó" if decision else "rechazó"
                evidence.append(f"[aprobacion_humana]\nEl empleado {verb} la incidencia propuesta.")
            evidence.append(f"[{message.name}]\n{message.text}")
    run.evidence = "\n\n".join(evidence)
