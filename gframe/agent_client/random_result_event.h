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

} // namespace ygo::agent_client
