"""Schema of `evals/dataset.jsonl`.

Labels point to documents and sections, never to chunk ids, so they stay valid when the
chunking strategy changes. Everything that can be checked by code (tool calls, abstention,
forbidden documents or strings, approval outcome) is expressed as data here; the LLM judge
is only used for answer correctness, guided by `key_facts`.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ToolName = Literal["buscar_normativa", "consultar_operacion", "abrir_incidencia"]


class Category(StrEnum):
    FACTUAL = "factual"
    EXACT_CODE = "exact_code"
    MULTI_HOP = "multi_hop"
    CURRENT_VS_OBSOLETE = "current_vs_obsolete"
    OPERATION = "operation"
    NO_ANSWER = "no_answer"
    PERMISSIONS = "permissions"
    INJECTION = "injection"
    HUMAN_APPROVAL = "human_approval"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SectionRef(_Strict):
    """A labelled piece of evidence. A retrieved chunk matches if it belongs to `doc_id`
    and its section is `section` or one of its subsections (e.g. "3" matches "3.1")."""

    doc_id: str = Field(pattern=r"^NOR-\d{3}$")
    section: str = Field(pattern=r"^\d+(\.\d+)*$")


class ToolCallSpec(_Strict):
    """A tool call. `args` is a subset: every key given must match; others are ignored."""

    name: ToolName
    args: dict[str, Any] = Field(default_factory=dict)


class Forbidden(_Strict):
    doc_ids: list[str] = Field(
        default_factory=list, description="Must be neither retrieved nor cited."
    )
    strings: list[str] = Field(
        default_factory=list, description="Must not appear in the final answer."
    )
    tool_calls: list[ToolCallSpec] = Field(
        default_factory=list, description="Must not be attempted (not even proposed)."
    )


class Approval(_Strict):
    """How the harness answers the human-approval interrupt."""

    decision: Literal["approve", "reject"]


class EvalCase(_Strict):
    id: str = Field(pattern=r"^[A-Z]{3}-\d{2}$")
    split: Literal["dev", "test"]
    category: Category
    critical: bool = Field(description="A failure fails the quality gate, whatever the averages.")
    employee_id: str = Field(pattern=r"^EMP-\d{3}$")
    question: str
    reference_answer: str
    key_facts: list[str] = Field(
        default_factory=list, description="Facts a correct answer must contain (for the judge)."
    )
    relevant: list[SectionRef] = Field(default_factory=list)
    expected_tool_calls: list[ToolCallSpec] = Field(default_factory=list)
    must_abstain: bool = False
    forbidden: Forbidden = Field(default_factory=Forbidden)
    approval: Approval | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _category_rules(self) -> Self:
        if self.category is Category.NO_ANSWER and not self.must_abstain:
            raise ValueError(f"{self.id}: no_answer cases must abstain")
        if self.must_abstain and (self.relevant or self.key_facts):
            raise ValueError(f"{self.id}: abstention cases have no relevant evidence or facts")
        if self.category is Category.HUMAN_APPROVAL:
            if self.approval is None:
                raise ValueError(f"{self.id}: human_approval cases need an approval decision")
            if not any(call.name == "abrir_incidencia" for call in self.expected_tool_calls):
                raise ValueError(f"{self.id}: human_approval cases must expect abrir_incidencia")
        elif self.approval is not None:
            raise ValueError(f"{self.id}: only human_approval cases take an approval decision")
        return self


def load_dataset(path: Path) -> list[EvalCase]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                cases.append(EvalCase.model_validate(json.loads(line)))
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    return cases
