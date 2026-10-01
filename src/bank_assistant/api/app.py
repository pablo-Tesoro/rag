"""FastAPI application.

    POST /chat                        ask a question (new or existing thread)
    POST /chat/{thread_id}/approval   approve or reject the pending incident
    GET  /healthz                     liveness: the process is up
    GET  /readyz                      readiness: database reachable and data loaded

The employee arrives in the `X-Employee-Id` header. There is no real authentication, but the
identity is handled as a verified token would be: it goes into the agent's runtime context
for every call, and a thread can only be continued or approved by the employee who owns it.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from bank_assistant.agent.guards import working_calls_in_turn
from bank_assistant.agent.state import AgentContext
from bank_assistant.api.schemas import (
    Answer,
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    PendingAction,
)
from bank_assistant.config import Settings, get_settings
from bank_assistant.identity import Employee
from bank_assistant.logs import configure_logging, pseudonymize
from bank_assistant.services import AgentGraph, Services, open_services

log = logging.getLogger(__name__)

ServicesFactory = Callable[[Settings], AbstractAsyncContextManager[Services]]


def create_app(services_factory: ServicesFactory | None = None) -> FastAPI:
    factory = services_factory or (lambda settings: open_services(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = get_settings()
        configure_logging(settings.log_level)
        async with factory(settings) as services:
            app.state.services = services
            yield

    app = FastAPI(title="Banco Olvessa assistant (fictitious)", lifespan=lifespan)

    def get_services(request: Request) -> Services:
        services: Services = request.app.state.services
        return services

    def agent_graph(services: Annotated[Services, Depends(get_services)]) -> AgentGraph:
        if services.graph is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, services.unavailable_reason)
        return services.graph

    def current_employee(
        services: Annotated[Services, Depends(get_services)],
        x_employee_id: Annotated[str | None, Header()] = None,
    ) -> Employee:
        employee = services.employees.get(x_employee_id) if x_employee_id else None
        if employee is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or missing employee")
        return employee

    ServicesDep = Annotated[Services, Depends(get_services)]
    EmployeeDep = Annotated[Employee, Depends(current_employee)]
    GraphDep = Annotated[AgentGraph, Depends(agent_graph)]

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(services: ServicesDep) -> JSONResponse:
        checks = await services.readiness()
        ready = all(checks.values())
        code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse({"ready": ready, "checks": checks}, status_code=code)

    @app.post("/chat")
    async def chat(
        body: ChatRequest, services: ServicesDep, graph: GraphDep, employee: EmployeeDep
    ) -> ChatResponse:
        thread_id = body.thread_id or uuid.uuid4().hex
        snapshot = await _owned_snapshot(graph, employee, thread_id, must_exist=False)
        if snapshot is not None and snapshot.interrupts:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This conversation is waiting for an approval: use /chat/{thread_id}/approval",
            )
        graph_input = {
            "messages": [HumanMessage(body.message)],
            "employee_id": employee.id,
            "final_answer": None,  # reset the structured answer of the previous turn
        }
        return await _run_turn(services, graph, employee, thread_id, graph_input)

    @app.post("/chat/{thread_id}/approval")
    async def approve(
        thread_id: str,
        body: ApprovalRequest,
        services: ServicesDep,
        graph: GraphDep,
        employee: EmployeeDep,
    ) -> ChatResponse:
        snapshot = await _owned_snapshot(graph, employee, thread_id, must_exist=True)
        if snapshot is None or not snapshot.interrupts:
            raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for approval")
        command: Command[str] = Command(resume={"approved": body.approved})
        return await _run_turn(services, graph, employee, thread_id, command)

    return app


def _run_config(services: Services, employee: Employee, thread_id: str) -> RunnableConfig:
    settings = services.settings
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": settings.agent_recursion_limit,
        "run_name": "chat_turn",
        # Trace metadata, for filtering in LangSmith. No personal data.
        "metadata": {
            "employee_ref": pseudonymize(
                employee.id, settings.log_pseudonym_key.get_secret_value()
            ),
            "thread_id": thread_id,
            "prompt_version": services.prompt.label,
            "retrieval_mode": settings.retrieval_mode.value,
            "llm_model": settings.llm_model,
        },
        "tags": [
            "api",
            f"prompt:{services.prompt.version}",
            f"retrieval:{settings.retrieval_mode}",
        ],
        "callbacks": list(services.callbacks),
    }


async def _owned_snapshot(
    graph: AgentGraph, employee: Employee, thread_id: str, *, must_exist: bool
) -> Any:
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    owner = snapshot.values.get("employee_id") if snapshot.values else None
    if owner is None:
        if must_exist:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        return None
    if owner != employee.id:
        # Same answer as a missing thread: do not reveal that it exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return snapshot


async def _run_turn(
    services: Services, graph: AgentGraph, employee: Employee, thread_id: str, graph_input: Any
) -> ChatResponse:
    settings = services.settings
    config = _run_config(services, employee, thread_id)
    context = AgentContext(employee=employee, retrieval_mode=settings.retrieval_mode)
    started = time.perf_counter()
    response = ChatResponse(
        thread_id=thread_id,
        status="failed",
        prompt_version=services.prompt.version,
        retrieval_mode=settings.retrieval_mode.value,
    )
    try:
        result = await asyncio.wait_for(
            graph.ainvoke(graph_input, config, context=context),
            timeout=settings.request_timeout_s,
        )
    except (GraphRecursionError, TimeoutError) as error:
        response.answer = Answer(
            texto="No he podido completar la consulta. Inténtalo de nuevo en una conversación "
            "nueva o formula la pregunta de otra manera.",
            citas=[],
            sin_evidencia=True,
            terminacion="error",
        )
        _log_turn(services, employee, thread_id, response, started, error=type(error).__name__)
        return response

    interrupts = result.get("__interrupt__")
    if interrupts:
        response.status = "pending_approval"
        response.pending_action = PendingAction.model_validate(interrupts[0].value)
    else:
        response.status = "completed"
        response.answer = Answer.model_validate(result["final_answer"])
    _log_turn(
        services,
        employee,
        thread_id,
        response,
        started,
        tools=working_calls_in_turn(result["messages"]),
    )
    return response


def _log_turn(
    services: Services,
    employee: Employee,
    thread_id: str,
    response: ChatResponse,
    started: float,
    **extra: object,
) -> None:
    key = services.settings.log_pseudonym_key.get_secret_value()
    log.info(
        "chat.turn",
        extra={
            "fields": {
                "employee_ref": pseudonymize(employee.id, key),
                "thread_id": thread_id,
                "status": response.status,
                "terminacion": response.answer.terminacion if response.answer else None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "prompt_version": services.prompt.label,
                "retrieval_mode": response.retrieval_mode,
                **extra,
            }
        },
    )


app = create_app()
