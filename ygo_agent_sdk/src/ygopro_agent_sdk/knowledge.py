from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

HIDDEN_KNOWLEDGE_ZONES = frozenset({"hand", "deck", "extra"})


@dataclass
class KnowledgeLedger:
    """Agent-owned memory updated only from explicit observations.

    It preserves duplicate card counts and never invents which known card left a
    hidden zone when the client did not identify that card.
    """

    _hidden_cards: dict[tuple[str, str], Counter[int]] = field(default_factory=dict)
    _possible_hidden_cards: dict[tuple[str, str], Counter[int]] = field(default_factory=dict)
    _hidden_slots: dict[tuple[str, str, int], int] = field(default_factory=dict)
    _public_slots: dict[tuple[str, str, int], int] = field(default_factory=dict)
    _observations: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "hidden_zone_shuffled":
            player, zone = event.get("player"), event.get("zone")
            if isinstance(player, str) and isinstance(zone, str):
                self._forget_hidden_slots(player, zone)
            return
        if kind == "cards_confirmed":
            cards = event.get("cards")
            if isinstance(cards, list):
                self._observations.append(copy.deepcopy(event))
                for observation in cards:
                    self._apply_confirmation(observation)
            return
        if kind == "cards_drawn":
            self._apply_draw(event)
            return
        if kind != "card_moved":
            return
        source, destination = event.get("from"), event.get("to")
        card = event.get("card")
        card_id = card.get("id") if isinstance(card, dict) else None
        if not isinstance(card_id, int) and isinstance(source, dict):
            source_key = self._slot_key(source)
            if source_key is not None:
                card_id = self._public_slots.get(source_key, self._hidden_slots.get(source_key))
        if not isinstance(card_id, int):
            if isinstance(source, dict):
                self._mark_hidden_zone_uncertain(source)
            return
        if isinstance(source, dict):
            self._discard(source, card_id)
        if isinstance(destination, dict):
            self._remember(destination, card_id)

    def remember_card(self, player: str, zone: str, card_id: int, slot_index: int = -1) -> None:
        """Apply an explicit Agent-side fact without pretending it came from the engine."""

        self._remember({"player": player, "zone": zone, "slot_index": slot_index}, card_id)

    def forget_card(self, player: str, zone: str, card_id: int, slot_index: int = -1) -> None:
        self._discard({"player": player, "zone": zone, "slot_index": slot_index}, card_id)

    def known_cards(self, player: str, zone: str) -> frozenset[int]:
        """Compatibility view containing distinct known card IDs."""

        return frozenset(self._hidden_cards.get((player, zone), Counter()))

    def known_card_counts(self, player: str, zone: str) -> dict[int, int]:
        """Return cards that are still certain to be in the hidden zone."""

        return dict(self._hidden_cards.get((player, zone), Counter()))

    def possible_card_counts(self, player: str, zone: str) -> dict[int, int]:
        """Return previously known cards whose continued presence is uncertain."""

        return dict(self._possible_hidden_cards.get((player, zone), Counter()))

    def observations(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(self._observations))

    def _apply_confirmation(self, observation: Any) -> None:
        if not isinstance(observation, dict):
            return
        card, location = observation.get("card"), observation.get("location")
        card_id = card.get("id") if isinstance(card, dict) else None
        if not isinstance(card_id, int) or not isinstance(location, dict):
            return
        self._remember(location, card_id)

    def _apply_draw(self, event: dict[str, Any]) -> None:
        player, cards = event.get("player"), event.get("cards")
        if not isinstance(player, str) or not isinstance(cards, list):
            return
        self._observations.append(copy.deepcopy(event))
        for card in cards:
            card_id = card.get("id") if isinstance(card, dict) else None
            if not (
                isinstance(card_id, int)
                and not isinstance(card_id, bool)
                and card.get("known", True) is not False
            ):
                self._mark_hidden_zone_uncertain({"player": player, "zone": "deck"})
                continue
            self._discard({"player": player, "zone": "deck"}, card_id)
            self._remember({"player": player, "zone": "hand"}, card_id)

    def _remember(self, location: dict[str, Any], card_id: int) -> None:
        player, zone = location.get("player"), location.get("zone")
        if not isinstance(player, str) or not isinstance(zone, str):
            return
        key = self._slot_key(location)
        if zone in HIDDEN_KNOWLEDGE_ZONES:
            if key is None:
                self._hidden_cards.setdefault((player, zone), Counter())[card_id] += 1
                self._decrement_possible(player, zone, card_id)
                return
            previous = self._hidden_slots.get(key)
            if previous == card_id:
                return
            if previous is not None:
                self._decrement(player, zone, previous)
            cards = self._hidden_cards.setdefault((player, zone), Counter())
            assigned = sum(
                1
                for slot, known_id in self._hidden_slots.items()
                if slot[:2] == (player, zone) and known_id == card_id
            )
            self._hidden_slots[key] = card_id
            if cards[card_id] <= assigned:
                cards[card_id] += 1
                self._decrement_possible(player, zone, card_id)
            return
        if key is not None:
            self._public_slots[key] = card_id

    def _discard(self, location: dict[str, Any], card_id: int) -> None:
        player, zone = location.get("player"), location.get("zone")
        if not isinstance(player, str) or not isinstance(zone, str):
            return
        key = self._slot_key(location)
        if zone in HIDDEN_KNOWLEDGE_ZONES:
            slotted = self._hidden_slots.pop(key, None) if key is not None else None
            removed_id = slotted if slotted is not None else card_id
            if self._decrement(player, zone, removed_id):
                if key is None:
                    self._forget_hidden_slots(player, zone)
            else:
                self._decrement_possible(player, zone, removed_id)
            return
        if key is not None:
            self._public_slots.pop(key, None)

    def _decrement(self, player: str, zone: str, card_id: int) -> bool:
        cards = self._hidden_cards.get((player, zone))
        if not cards or cards[card_id] <= 0:
            return False
        cards[card_id] -= 1
        if cards[card_id] == 0:
            del cards[card_id]
        if not cards:
            self._hidden_cards.pop((player, zone), None)
        return True

    def _decrement_possible(self, player: str, zone: str, card_id: int) -> bool:
        cards = self._possible_hidden_cards.get((player, zone))
        if not cards or cards[card_id] <= 0:
            return False
        cards[card_id] -= 1
        if cards[card_id] == 0:
            del cards[card_id]
        if not cards:
            self._possible_hidden_cards.pop((player, zone), None)
        return True

    def _mark_hidden_zone_uncertain(self, location: dict[str, Any]) -> None:
        player, zone = location.get("player"), location.get("zone")
        if not isinstance(player, str) or zone not in HIDDEN_KNOWLEDGE_ZONES:
            return
        cards = self._hidden_cards.pop((player, zone), None)
        if cards:
            self._possible_hidden_cards.setdefault((player, zone), Counter()).update(cards)
        self._forget_hidden_slots(player, zone)

    def _forget_hidden_slots(self, player: str, zone: str) -> None:
        for key in [key for key in self._hidden_slots if key[:2] == (player, zone)]:
            del self._hidden_slots[key]

    @staticmethod
    def _slot_key(location: dict[str, Any]) -> tuple[str, str, int] | None:
        slot_index = location.get("slot_index")
        if not isinstance(slot_index, int) or isinstance(slot_index, bool) or slot_index < 0:
            return None
        return (
            str(location.get("player", "")),
            str(location.get("zone", "")),
            slot_index,
        )
