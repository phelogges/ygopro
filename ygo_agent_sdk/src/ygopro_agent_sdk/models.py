from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .framing import encode_frame


@dataclass(frozen=True, slots=True)
class EffectDescriptor:
    """Description metadata associated with an engine activation candidate.

    The ID and candidate flags come from the engine message. Text is resolved
    from local client resources and the zero-based offset is client-derived;
    neither is a printed effect number.
    """

    description_id: int
    description_offset: int | None
    description_text: str | None
    engine_candidate_index: int | None
    raw_flags: int | None
    operation: bool | None
    reset: bool | None
    forced: bool | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Choice:
    id: int
    action: str
    card: dict[str, Any] | None
    effect_candidate: EffectDescriptor | None
    option: dict[str, Any] | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CardSelection:
    index: int
    card: dict[str, Any]
    selection_sequence: int


@dataclass(frozen=True, slots=True)
class DuelEvent:
    """An engine-observed fact emitted by agent_client without causal inference."""

    session_id: str
    duel_id: str
    event_id: int
    kind: str
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ActionResponse:
    request_id: int
    action: dict[str, Any]
    session_id: str | None = None
    duel_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "type": "action",
            "request_id": self.request_id,
            "action": self.action,
        }
        if self.session_id is not None:
            message["session_id"] = self.session_id
        if self.duel_id is not None:
            message["duel_id"] = self.duel_id
        return message

    def to_frame(self) -> bytes:
        return encode_frame(self.to_dict())


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    request_id: int
    session_id: str
    duel_id: str
    event_id: int
    state_revision: int
    kind: str
    choices: tuple[Choice, ...]
    card_choices: tuple[CardSelection, ...]
    min_cards: int
    max_cards: int
    selection_hint: dict[str, Any] | None
    raw: dict[str, Any]

    def choose(self, choice_id: int) -> ActionResponse:
        if not any(choice.id == choice_id for choice in self.choices):
            raise ValueError("choice_id is not legal for this request")
        return ActionResponse(
            self.request_id,
            {"kind": "choice", "choice_id": choice_id},
            self.session_id,
            self.duel_id,
        )

    def choose_cards(self, indices: list[int]) -> ActionResponse:
        valid = {card.index for card in self.card_choices}
        count_is_valid = self.min_cards <= len(indices) <= self.max_cards
        if len(indices) != len(set(indices)) or not count_is_valid:
            raise ValueError("card selection count is invalid")
        if any(index not in valid for index in indices):
            raise ValueError("card selection includes an illegal index")
        return ActionResponse(
            self.request_id,
            {"kind": "cards", "indices": indices},
            self.session_id,
            self.duel_id,
        )
