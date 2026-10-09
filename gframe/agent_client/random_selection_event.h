#pragma once

#include "../../ocgcore/common.h"

#include <cstddef>
#include <cstdint>
#include <optional>
#include <utility>

#include <nlohmann/json.hpp>

namespace ygo::agent_client {

// MSG_RANDOM_SELECTED contains locations, not card identities. The packet is
// already filtered for this client by the game server; do not enrich it from
// ClientField, where hidden cards may retain cached identities.
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

} // namespace ygo::agent_client
