#pragma once

#include "../../ocgcore/common.h"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <utility>

#include <nlohmann/json.hpp>

namespace ygo::agent_client {

inline const char *CoinFaceForSelectedOption(std::uint32_t value) noexcept {
  if (value == 60)
    return "heads";
  if (value == 61)
    return "tails";
  return nullptr;
}

// The result bytes are public game messages. Coin faces follow the existing
// GUI display mapping: zero is tails and one is heads.
inline std::optional<nlohmann::json>
ParseRandomResultEvent(const std::uint8_t *bytes, std::size_t length,
                       int local_player) {
  if (!bytes || length < 4 ||
      (bytes[0] != MSG_TOSS_COIN && bytes[0] != MSG_TOSS_DICE) ||
      bytes[1] > 1 || local_player < 0 || local_player > 1)
    return std::nullopt;
  const bool coin = bytes[0] == MSG_TOSS_COIN;
  const std::size_t count = bytes[2];
  if (count == 0 || count > (coin ? 20U : 5U) || length != 3 + count)
    return std::nullopt;

  nlohmann::json results = nlohmann::json::array();
  for (std::size_t i = 0; i < count; ++i) {
    const auto result = bytes[3 + i];
    if (coin) {
      if (result > 1)
        return std::nullopt;
      results.push_back(result == 0 ? "tails" : "heads");
    } else {
      if (result < 1 || result > 6)
        return std::nullopt;
      results.push_back(result);
    }
  }
  return nlohmann::json{{"kind", coin ? "coin_tossed" : "dice_rolled"},
                        {"player", local_player},
                        {"count", count},
                        {"results", std::move(results)}};
}

// MSG_RANDOM_SELECTED contains locations, not card identities. Do not enrich
// it from ClientField, where hidden cards may retain cached identities.
inline std::optional<nlohmann::json> ParseRandomSelectionEvent(
    const std::uint8_t *bytes, std::size_t length, bool is_first,
    bool graveyard_inspection_allowed) {
  if (!bytes || length < 7 || bytes[0] != MSG_RANDOM_SELECTED || bytes[1] > 1)
    return std::nullopt;
  const std::size_t count = bytes[2];
  if (count == 0 || length != 3 + count * 4)
    return std::nullopt;

  nlohmann::json cards = nlohmann::json::array();
  for (std::size_t i = 0; i < count; ++i) {
    const auto *card = bytes + 3 + i * 4;
    const auto raw_location = card[1];
    const auto location = raw_location & 0x7f;
    if (card[0] > 1 ||
        (location != LOCATION_DECK && location != LOCATION_HAND &&
         location != LOCATION_MZONE && location != LOCATION_SZONE &&
         location != LOCATION_GRAVE && location != LOCATION_REMOVED &&
         location != LOCATION_EXTRA) ||
        ((raw_location & LOCATION_OVERLAY) && location != LOCATION_MZONE))
      return std::nullopt;
    const int player = is_first ? card[0] : 1 - card[0];
    nlohmann::json item{{"player", player}, {"location", raw_location}};
    const bool public_position = location == LOCATION_MZONE ||
                                 location == LOCATION_SZONE ||
                                 (location == LOCATION_GRAVE &&
                                  graveyard_inspection_allowed);
    const bool own_position = player == 0 && location != LOCATION_DECK &&
                              (location != LOCATION_GRAVE ||
                               graveyard_inspection_allowed);
    if (public_position || own_position)
      item["sequence"] = card[2];
    cards.push_back(std::move(item));
  }
  return nlohmann::json{{"kind", "cards_randomly_selected"},
                        {"player", is_first ? bytes[1] : 1 - bytes[1]},
                        {"count", count},
                        {"cards", std::move(cards)}};
}

// A facedown-card shuffle must not reveal source/destination mappings.
inline std::optional<nlohmann::json>
ParseSetShuffleEvent(const std::uint8_t *bytes, std::size_t length,
                     bool is_first) {
  if (!bytes || length < 19 || bytes[0] != MSG_SHUFFLE_SET_CARD ||
      (bytes[1] != LOCATION_MZONE && bytes[1] != LOCATION_SZONE))
    return std::nullopt;
  const std::size_t count = bytes[2];
  if (count < 2 || count > 5 || length != 3 + count * 8)
    return std::nullopt;
  const auto controller = bytes[3];
  if (controller > 1)
    return std::nullopt;
  for (std::size_t i = 0; i < count; ++i) {
    const auto *card = bytes + 3 + i * 4;
    if (card[0] != controller || card[1] != bytes[1] || card[2] >= 5)
      return std::nullopt;
  }
  return nlohmann::json{
      {"kind", "set_cards_shuffled"},
      {"player", is_first ? controller : 1 - controller},
      {"zone", bytes[1] == LOCATION_MZONE ? "monster" : "spell"},
      {"count", count}};
}

inline bool GameEventMessage(std::uint8_t type) {
  switch (type) {
  case MSG_TOSS_COIN:
  case MSG_TOSS_DICE:
  case MSG_RANDOM_SELECTED:
  case MSG_SHUFFLE_SET_CARD:
  case MSG_CONFIRM_DECKTOP:
  case MSG_CONFIRM_EXTRATOP:
  case MSG_SWAP_GRAVE_DECK:
  case MSG_REVERSE_DECK:
  case MSG_DECK_TOP:
  case MSG_SWAP:
  case MSG_FIELD_DISABLED:
  case MSG_EQUIP:
  case MSG_CARD_TARGET:
  case MSG_CANCEL_TARGET:
  case MSG_ADD_COUNTER:
  case MSG_REMOVE_COUNTER:
  case MSG_MISSED_EFFECT:
  case MSG_HAND_RES:
    return true;
  default:
    return false;
  }
}

inline std::optional<nlohmann::json> ParseGameEvent(
    const std::uint8_t *bytes, std::size_t length, bool is_first,
    bool graveyard_inspection_allowed, bool deck_reversed) {
  if (!bytes || length == 0 || !GameEventMessage(bytes[0]))
    return std::nullopt;
  const auto read_u16 = [](const std::uint8_t *at) {
    return std::uint16_t(at[0]) | (std::uint16_t(at[1]) << 8);
  };
  const auto read_u32 = [](const std::uint8_t *at) {
    return std::uint32_t(at[0]) | (std::uint32_t(at[1]) << 8) |
           (std::uint32_t(at[2]) << 16) | (std::uint32_t(at[3]) << 24);
  };
  const auto local_player = [is_first](std::uint8_t player) {
    return is_first ? int(player) : 1 - int(player);
  };
  const auto position = [local_player, graveyard_inspection_allowed](
                            const std::uint8_t *at)
      -> std::optional<nlohmann::json> {
    if (at[0] > 1)
      return std::nullopt;
    const auto location = at[1] & 0x7f;
    if (location != LOCATION_DECK && location != LOCATION_HAND &&
        location != LOCATION_MZONE && location != LOCATION_SZONE &&
        location != LOCATION_GRAVE && location != LOCATION_REMOVED &&
        location != LOCATION_EXTRA)
      return std::nullopt;
    if ((at[1] & LOCATION_OVERLAY) && location != LOCATION_MZONE)
      return std::nullopt;
    const int player = local_player(at[0]);
    nlohmann::json result{{"player", player}, {"location", at[1]}};
    const bool public_position =
        location == LOCATION_MZONE || location == LOCATION_SZONE ||
        (location == LOCATION_GRAVE && graveyard_inspection_allowed);
    const bool own_position =
        player == 0 && location != LOCATION_DECK &&
        (location != LOCATION_GRAVE || graveyard_inspection_allowed);
    if ((public_position || own_position) &&
        !((at[1] & LOCATION_OVERLAY) && player != 0))
      result["sequence"] = at[2];
    return result;
  };

  switch (bytes[0]) {
  case MSG_TOSS_COIN:
  case MSG_TOSS_DICE:
    if (length < 2 || bytes[1] > 1)
      return std::nullopt;
    return ParseRandomResultEvent(bytes, length, local_player(bytes[1]));
  case MSG_RANDOM_SELECTED:
    return ParseRandomSelectionEvent(bytes, length, is_first,
                                     graveyard_inspection_allowed);
  case MSG_SHUFFLE_SET_CARD:
    return ParseSetShuffleEvent(bytes, length, is_first);
  case MSG_CONFIRM_DECKTOP:
  case MSG_CONFIRM_EXTRATOP: {
    if (length < 3 || bytes[1] > 1 ||
        length != 3 + std::size_t(bytes[2]) * 7)
      return std::nullopt;
    const int player = local_player(bytes[1]);
    const auto location = bytes[0] == MSG_CONFIRM_DECKTOP ? LOCATION_DECK
                                                           : LOCATION_EXTRA;
    nlohmann::json cards = nlohmann::json::array();
    for (std::size_t i = 0; i < bytes[2]; ++i) {
      const auto *card = bytes + 3 + i * 7;
      if (card[4] > 1 || local_player(card[4]) != player || card[5] != location)
        return std::nullopt;
      nlohmann::json visible{{"player", local_player(card[4])},
                             {"location", location}};
      const auto card_id = read_u32(card) & 0x7fffffffU;
      if (card_id)
        visible["card_id"] = card_id;
      cards.push_back(std::move(visible));
    }
    return nlohmann::json{{"kind", "deck_cards_revealed"},
                          {"player", player},
                          {"zone", location == LOCATION_DECK ? "deck" : "extra"},
                          {"count", bytes[2]},
                          {"cards", std::move(cards)}};
  }
  case MSG_SWAP_GRAVE_DECK:
    if (length != 2 || bytes[1] > 1)
      return std::nullopt;
    return nlohmann::json{{"kind", "grave_deck_swapped"},
                          {"player", local_player(bytes[1])}};
  case MSG_REVERSE_DECK:
    if (length != 1)
      return std::nullopt;
    return nlohmann::json{{"kind", "deck_reversal_changed"},
                          {"deck_reversed", deck_reversed}};
  case MSG_DECK_TOP: {
    if (length != 7 || bytes[1] > 1)
      return std::nullopt;
    const auto code = read_u32(bytes + 3);
    nlohmann::json event{{"kind", "deck_top_observed"},
                         {"player", local_player(bytes[1])},
                         {"top_offset", bytes[2]},
                         {"card_reversed", (code & 0x80000000U) != 0}};
    if (code & 0x7fffffffU)
      event["card_id"] = code & 0x7fffffffU;
    return event;
  }
  case MSG_SWAP: {
    if (length != 17)
      return std::nullopt;
    auto first = position(bytes + 5);
    auto second = position(bytes + 13);
    if (!first || !second ||
        ((*first)["location"] != LOCATION_MZONE &&
         (*first)["location"] != LOCATION_SZONE) ||
        ((*second)["location"] != LOCATION_MZONE &&
         (*second)["location"] != LOCATION_SZONE))
      return std::nullopt;
    return nlohmann::json{{"kind", "cards_swapped"},
                          {"cards", nlohmann::json::array({*first, *second})}};
  }
  case MSG_FIELD_DISABLED: {
    if (length != 5)
      return std::nullopt;
    const auto raw = read_u32(bytes + 1);
    const auto local = is_first ? raw : (raw >> 16) | (raw << 16);
    return nlohmann::json{{"kind", "field_disabled_changed"},
                          {"value", local}};
  }
  case MSG_EQUIP:
  case MSG_CARD_TARGET:
  case MSG_CANCEL_TARGET: {
    if (length != 9)
      return std::nullopt;
    auto from = position(bytes + 1);
    auto to = position(bytes + 5);
    if (!from || !to)
      return std::nullopt;
    const char *kind = bytes[0] == MSG_EQUIP ? "equip_relation_established" :
                       bytes[0] == MSG_CARD_TARGET ? "card_target_relation_added" :
                                                     "card_target_relation_removed";
    return nlohmann::json{{"kind", kind},
                          {"cards", nlohmann::json::array({*from, *to})}};
  }
  case MSG_ADD_COUNTER:
  case MSG_REMOVE_COUNTER: {
    if (length != 8 || bytes[3] > 1)
      return std::nullopt;
    const std::uint8_t card[4]{bytes[3], bytes[4], bytes[5], 0};
    auto target = position(card);
    if (!target)
      return std::nullopt;
    return nlohmann::json{{"kind", bytes[0] == MSG_ADD_COUNTER
                                       ? "counter_added"
                                       : "counter_removed"},
                          {"counter_type", read_u16(bytes + 1)},
                          {"count", read_u16(bytes + 6)},
                          {"cards", nlohmann::json::array({*target})}};
  }
  case MSG_MISSED_EFFECT: {
    if (length != 9)
      return std::nullopt;
    auto handler = position(bytes + 1);
    if (!handler)
      return std::nullopt;
    // The native client writes this code's name to its visible duel log.
    nlohmann::json event{{"kind", "effect_timing_missed"},
                         {"cards", nlohmann::json::array({*handler})}};
    const auto card_id = read_u32(bytes + 5) & 0x7fffffffU;
    if (card_id)
      event["card_id"] = card_id;
    return event;
  }
  case MSG_HAND_RES: {
    if (length != 2 || (bytes[1] & 0xf0) != 0)
      return std::nullopt;
    const auto first = bytes[1] & 3;
    const auto second = (bytes[1] >> 2) & 3;
    if (first < 1 || first > 3 || second < 1 || second > 3)
      return std::nullopt;
    const char *choices[]{"", "rock", "paper", "scissors"};
    return nlohmann::json{{"kind", "hands_compared"},
                          {"self_choice", choices[is_first ? first : second]},
                          {"opponent_choice", choices[is_first ? second : first]}};
  }
  default:
    return std::nullopt;
  }
}

} // namespace ygo::agent_client
