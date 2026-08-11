from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RequirementId = Annotated[str, StringConstraints(pattern=r"^REQ-[A-Z]+-\d{3}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChangeType(str, Enum):
    MODIFIED = "MODIFIED"


class AnalysisDecision(str, Enum):
    PROCEED = "PROCEED"
    PARTIAL_PROCEED = "PARTIAL_PROCEED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    BLOCKED = "BLOCKED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    ERROR = "ERROR"


class ChangeRequest(StrictModel):
    request_id: NonEmptyStr
    change_type: ChangeType = ChangeType.MODIFIED
    target_requirement_id: RequirementId
    before_value: NonEmptyStr
    after_value: NonEmptyStr
    description: NonEmptyStr
    reason: NonEmptyStr | None = None
    acceptance_notes: list[NonEmptyStr] = Field(default_factory=list)
    out_of_scope: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def before_and_after_must_differ(self) -> "ChangeRequest":
        if self.before_value.casefold() == self.after_value.casefold():
            raise ValueError("before_value와 after_value는 달라야 합니다.")
        return self


class SrsRequirement(StrictModel):
    requirement_id: RequirementId
    statement: NonEmptyStr
    acceptance_criteria: NonEmptyStr


class Impact(StrictModel):
    requirement_id: RequirementId
    reason: NonEmptyStr


class Evidence(StrictModel):
    requirement_id: RequirementId
    evidence_text: NonEmptyStr


class Agent1Analysis(StrictModel):
    request_id: NonEmptyStr
    change_type: ChangeType
    target_requirement_id: RequirementId
    before_condition: NonEmptyStr
    after_condition: NonEmptyStr
    changed_fields: list[NonEmptyStr] = Field(min_length=1)
    direct_impacts: list[Impact] = Field(min_length=1)
    related_impacts: list[Impact] = Field(default_factory=list)
    verified_scope: list[NonEmptyStr] = Field(min_length=1)
    excluded_scope: list[NonEmptyStr] = Field(default_factory=list)
    information_gaps: list[NonEmptyStr] = Field(default_factory=list)
    user_questions: list[NonEmptyStr] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)
    decision: AnalysisDecision


class CheckResult(StrictModel):
    rule_id: NonEmptyStr
    status: CheckStatus
    message: NonEmptyStr


class Checkpoint1Result(StrictModel):
    checkpoint: str = "CP1"
    status: CheckStatus
    checks: list[CheckResult] = Field(min_length=1)

