#ifndef YGOPRO_AGENT_PROTOCOL_H
#define YGOPRO_AGENT_PROTOCOL_H

#include <cstdint>
#include <string_view>

namespace ygo::agent_protocol {

inline constexpr uint32_t protocol_version{3};

enum class Direction : uint8_t { local, queued, outbound, inbound };
enum class MessageType : uint8_t { hello, hello_ack, decision_request, action, duel_event, tool_call, tool_result };
enum class ResponseKind : uint8_t { choice, integer, cards, cancel };
enum class Event : uint8_t {
	timeout, invalid_action, card_moved, chain_added, chain_solving, chain_resolved,
	chain_ended, chain_negated, chain_disabled, decision_submitted,
	surrender_requested, duel_ended, summon_attempted, summon_succeeded,
	life_points_changed, cards_drawn, hidden_zone_shuffled, engine_hint,
	cards_confirmed, cards_indicated, card_relation_added, card_relation_removed,
	pre_duel_hand_result, turn_started, phase_changed, attack_declared,
	battle_snapshot, attack_disabled
};
enum class Player : uint8_t { self, opponent };
enum class DuelWinner : uint8_t { self, opponent, draw };
enum class Zone : uint8_t { unknown, deck, hand, main_monster, extra_monster, spell_trap, graveyard, banished, extra };
enum class Position : uint8_t { unknown, hidden, face_up, face_down, face_up_attack, face_down_attack, face_up_defense, face_down_defense };
enum class DeltaMode : uint8_t { none, snapshot, json_patch };
enum class SummonType : uint8_t { normal, special, flip };
enum class LifePointChange : uint8_t { damage, recover, cost, set };
enum class HintType : uint8_t {
	unknown, event, message, select_message, option_selected, effect, race,
	attribute, code, number, card, zone
};
enum class CardRelation : uint8_t { equip, card_target };
enum class CardObservationKind : uint8_t { confirm_cards, confirm_deck_top, confirm_extra_top, deck_top };
enum class PreDuelHand : uint8_t { unknown, rock, scissors, paper };
enum class PreDuelHandOutcome : uint8_t { unknown, win, loss, draw };
enum class CardIdProvenance : uint8_t { unavailable, engine_message, public_client_cache };
enum class Phase : uint8_t {
	unknown, draw, standby, main_1, battle_start, battle_step, damage,
	damage_calculation, battle, main_2, end
};
enum class MoveReason : uint8_t {
	destroy, release, temporary, material, summon, battle, effect, cost, adjust,
	lost_target, rule, special_summon, disabled_summon, flip, discard,
	reverse_damage, reverse_recover, return_to_deck, fusion, synchro, ritual,
	xyz, replace, draw, redirect, reveal, link, lost_overlay, maintenance, action
};
enum class Decision : uint8_t {
	unknown, pre_duel_hand, pre_duel_turn_order, idle_command, battle_command,
	effect_yes_no, yes_no, option, card, chain, place, position, tribute,
	counter, sum, unselect_card, sort_card, announce_race, announce_attribute,
	announce_card, announce_number, rock_paper_scissors
};
enum class Action : uint8_t {
	unknown, accept, decline, select_option, normal_summon, special_summon, change_position,
	set_monster, set_spell_trap, activate, enter_battle_phase, enter_main_phase_2,
	end_phase, attack, pass_chain, face_up_attack, face_down_attack,
	face_up_defense, face_down_defense, rock, scissors, paper, go_first, go_second
};

constexpr std::string_view ToString(Direction value) noexcept {
	switch(value) { case Direction::local: return "local"; case Direction::queued: return "queued"; case Direction::outbound: return "outbound"; case Direction::inbound: return "inbound"; }
	return "local";
}
constexpr std::string_view ToString(MessageType value) noexcept {
	switch(value) { case MessageType::hello: return "hello"; case MessageType::hello_ack: return "hello_ack"; case MessageType::decision_request: return "decision_request"; case MessageType::action: return "action"; case MessageType::duel_event: return "duel_event"; case MessageType::tool_call: return "tool_call"; case MessageType::tool_result: return "tool_result"; }
	return "hello";
}
constexpr std::string_view ToString(ResponseKind value) noexcept {
	switch(value) { case ResponseKind::choice: return "choice"; case ResponseKind::integer: return "integer"; case ResponseKind::cards: return "cards"; case ResponseKind::cancel: return "cancel"; }
	return "choice";
}
constexpr std::string_view ToString(Event value) noexcept {
	switch(value) {
	case Event::timeout: return "timeout"; case Event::invalid_action: return "invalid_action";
	case Event::card_moved: return "card_moved"; case Event::chain_added: return "chain_added";
	case Event::chain_solving: return "chain_solving"; case Event::chain_resolved: return "chain_resolved";
	case Event::chain_ended: return "chain_ended"; case Event::chain_negated: return "chain_negated";
	case Event::chain_disabled: return "chain_disabled"; case Event::decision_submitted: return "decision_submitted";
	case Event::surrender_requested: return "surrender_requested"; case Event::duel_ended: return "duel_ended";
	case Event::summon_attempted: return "summon_attempted"; case Event::summon_succeeded: return "summon_succeeded";
	case Event::life_points_changed: return "life_points_changed"; case Event::cards_drawn: return "cards_drawn";
	case Event::hidden_zone_shuffled: return "hidden_zone_shuffled";
	case Event::engine_hint: return "engine_hint"; case Event::cards_confirmed: return "cards_confirmed";
	case Event::cards_indicated: return "cards_indicated";
	case Event::card_relation_added: return "card_relation_added";
	case Event::card_relation_removed: return "card_relation_removed";
	case Event::pre_duel_hand_result: return "pre_duel_hand_result";
	case Event::turn_started: return "turn_started"; case Event::phase_changed: return "phase_changed";
	case Event::attack_declared: return "attack_declared"; case Event::battle_snapshot: return "battle_snapshot";
	case Event::attack_disabled: return "attack_disabled";
	}
	return "invalid_action";
}
constexpr std::string_view ToString(Player value) noexcept { return value == Player::self ? "self" : "opponent"; }
constexpr std::string_view ToString(DuelWinner value) noexcept {
	switch(value) { case DuelWinner::self: return "self"; case DuelWinner::opponent: return "opponent"; case DuelWinner::draw: return "draw"; }
	return "draw";
}
constexpr std::string_view ToString(Zone value) noexcept {
	switch(value) {
	case Zone::deck: return "deck"; case Zone::hand: return "hand"; case Zone::main_monster: return "main_monster"; case Zone::extra_monster: return "extra_monster";
	case Zone::spell_trap: return "spell_trap"; case Zone::graveyard: return "graveyard";
	case Zone::banished: return "banished"; case Zone::extra: return "extra"; default: return "unknown";
	}
}
constexpr std::string_view ToString(Position value) noexcept {
	switch(value) {
	case Position::hidden: return "hidden"; case Position::face_up: return "face_up"; case Position::face_down: return "face_down";
	case Position::face_up_attack: return "face_up_attack"; case Position::face_down_attack: return "face_down_attack";
	case Position::face_up_defense: return "face_up_defense"; case Position::face_down_defense: return "face_down_defense";
	default: return "unknown";
	}
}
constexpr std::string_view ToString(DeltaMode value) noexcept {
	switch(value) { case DeltaMode::none: return "none"; case DeltaMode::snapshot: return "snapshot"; case DeltaMode::json_patch: return "json_patch"; }
	return "none";
}
constexpr std::string_view ToString(SummonType value) noexcept {
	switch(value) { case SummonType::normal: return "normal"; case SummonType::special: return "special"; case SummonType::flip: return "flip"; }
	return "normal";
}
constexpr std::string_view ToString(LifePointChange value) noexcept {
	switch(value) { case LifePointChange::damage: return "damage"; case LifePointChange::recover: return "recover"; case LifePointChange::cost: return "cost"; case LifePointChange::set: return "set"; }
	return "set";
}
constexpr std::string_view ToString(HintType value) noexcept {
	switch(value) {
	case HintType::event: return "event"; case HintType::message: return "message";
	case HintType::select_message: return "select_message"; case HintType::option_selected: return "option_selected";
	case HintType::effect: return "effect"; case HintType::race: return "race";
	case HintType::attribute: return "attribute"; case HintType::code: return "code";
	case HintType::number: return "number"; case HintType::card: return "card";
	case HintType::zone: return "zone"; default: return "unknown";
	}
}
constexpr std::string_view ToString(CardRelation value) noexcept {
	return value == CardRelation::equip ? "equip" : "card_target";
}
constexpr std::string_view ToString(CardObservationKind value) noexcept {
	switch(value) {
	case CardObservationKind::confirm_cards: return "confirm_cards";
	case CardObservationKind::confirm_deck_top: return "confirm_deck_top";
	case CardObservationKind::confirm_extra_top: return "confirm_extra_top";
	case CardObservationKind::deck_top: return "deck_top";
	}
	return "confirm_cards";
}
constexpr std::string_view ToString(PreDuelHand value) noexcept {
	switch(value) {
	case PreDuelHand::rock: return "rock"; case PreDuelHand::scissors: return "scissors";
	case PreDuelHand::paper: return "paper"; default: return "unknown";
	}
}
constexpr std::string_view ToString(PreDuelHandOutcome value) noexcept {
	switch(value) {
	case PreDuelHandOutcome::win: return "win"; case PreDuelHandOutcome::loss: return "loss";
	case PreDuelHandOutcome::draw: return "draw"; default: return "unknown";
	}
}
constexpr std::string_view ToString(CardIdProvenance value) noexcept {
	switch(value) {
	case CardIdProvenance::engine_message: return "engine_message";
	case CardIdProvenance::public_client_cache: return "public_client_cache";
	default: return "unavailable";
	}
}
constexpr std::string_view ToString(Phase value) noexcept {
	switch(value) {
	case Phase::draw: return "draw"; case Phase::standby: return "standby";
	case Phase::main_1: return "main_1"; case Phase::battle_start: return "battle_start";
	case Phase::battle_step: return "battle_step"; case Phase::damage: return "damage";
	case Phase::damage_calculation: return "damage_calculation"; case Phase::battle: return "battle";
	case Phase::main_2: return "main_2"; case Phase::end: return "end";
	default: return "unknown";
	}
}
constexpr std::string_view ToString(MoveReason value) noexcept {
	switch(value) {
	case MoveReason::destroy: return "destroy"; case MoveReason::release: return "release";
	case MoveReason::temporary: return "temporary"; case MoveReason::material: return "material";
	case MoveReason::summon: return "summon"; case MoveReason::battle: return "battle";
	case MoveReason::effect: return "effect"; case MoveReason::cost: return "cost";
	case MoveReason::adjust: return "adjust"; case MoveReason::lost_target: return "lost_target";
	case MoveReason::rule: return "rule"; case MoveReason::special_summon: return "special_summon";
	case MoveReason::disabled_summon: return "disabled_summon"; case MoveReason::flip: return "flip";
	case MoveReason::discard: return "discard"; case MoveReason::reverse_damage: return "reverse_damage";
	case MoveReason::reverse_recover: return "reverse_recover"; case MoveReason::return_to_deck: return "return_to_deck";
	case MoveReason::fusion: return "fusion"; case MoveReason::synchro: return "synchro";
	case MoveReason::ritual: return "ritual"; case MoveReason::xyz: return "xyz";
	case MoveReason::replace: return "replace"; case MoveReason::draw: return "draw";
	case MoveReason::redirect: return "redirect"; case MoveReason::reveal: return "reveal";
	case MoveReason::link: return "link"; case MoveReason::lost_overlay: return "lost_overlay";
	case MoveReason::maintenance: return "maintenance"; case MoveReason::action: return "action";
	}
	return "effect";
}
constexpr std::string_view ToString(Decision value) noexcept {
	switch(value) {
	case Decision::pre_duel_hand: return "pre_duel_hand"; case Decision::pre_duel_turn_order: return "pre_duel_turn_order";
	case Decision::idle_command: return "idle_command"; case Decision::battle_command: return "battle_command";
	case Decision::effect_yes_no: return "effect_yes_no"; case Decision::yes_no: return "yes_no";
	case Decision::option: return "option"; case Decision::card: return "card"; case Decision::chain: return "chain";
	case Decision::place: return "place"; case Decision::position: return "position"; case Decision::tribute: return "tribute";
	case Decision::counter: return "counter"; case Decision::sum: return "sum"; case Decision::unselect_card: return "unselect_card";
	case Decision::sort_card: return "sort_card"; case Decision::announce_race: return "announce_race";
	case Decision::announce_attribute: return "announce_attribute"; case Decision::announce_card: return "announce_card";
	case Decision::announce_number: return "announce_number"; case Decision::rock_paper_scissors: return "rock_paper_scissors";
	default: return "unknown";
	}
}
constexpr std::string_view ToString(Action value) noexcept {
	switch(value) {
	case Action::unknown: return "unknown";
	case Action::accept: return "accept"; case Action::decline: return "decline"; case Action::select_option: return "select_option";
	case Action::normal_summon: return "normal_summon"; case Action::special_summon: return "special_summon";
	case Action::change_position: return "change_position"; case Action::set_monster: return "set_monster";
	case Action::set_spell_trap: return "set_spell_trap"; case Action::activate: return "activate";
	case Action::enter_battle_phase: return "enter_battle_phase"; case Action::enter_main_phase_2: return "enter_main_phase_2";
	case Action::end_phase: return "end_phase"; case Action::attack: return "attack"; case Action::pass_chain: return "pass_chain";
	case Action::face_up_attack: return "face_up_attack"; case Action::face_down_attack: return "face_down_attack";
	case Action::face_up_defense: return "face_up_defense"; case Action::face_down_defense: return "face_down_defense";
	case Action::rock: return "rock"; case Action::scissors: return "scissors"; case Action::paper: return "paper";
	case Action::go_first: return "go_first"; case Action::go_second: return "go_second";
	}
	return "unknown";
}

} // namespace ygo::agent_protocol

#endif
