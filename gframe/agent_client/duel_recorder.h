#ifndef YGO_AGENT_CLIENT_DUEL_RECORDER_H
#define YGO_AGENT_CLIENT_DUEL_RECORDER_H

#include "decision_codec.h"

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace ygo {
struct Deck;
struct HostInfo;

namespace agent_client {

// Local diagnostic capture. It has no Agent transport or server dependency.
class DuelRecorder final {
public:
	static DuelRecorder& Instance();
	bool Active() const noexcept { return active_; }
	void OnWirePacket(bool incoming, const void* bytes, std::size_t length);
	void OnRoomJoined(const HostInfo& info);
	void OnDeckSubmitted(const Deck& deck);
	void OnPreDuelDecision(DecisionSource source);
	void OnGameMessage(const std::uint8_t* bytes, std::size_t length, bool already_answered);
	void OnDuelStart();
	void OnDuelEnd();
	void OnConnectionClosed(const char* reason);
	void OnReplaySavePrompt();
	void OnReplaySaveResolved();

private:
	struct SubmittedResponse {
		std::uint8_t packet_type{};
		std::vector<std::uint8_t> payload;
	};
	DuelRecorder();
	DuelRecorder(const DuelRecorder&) = delete;
	DuelRecorder& operator=(const DuelRecorder&) = delete;
	void Write(nlohmann::json record);
	void CaptureResponse(std::uint8_t packet_type, const std::uint8_t* payload, std::size_t length);
	void FinishResponse(const SubmittedResponse& response);
	void RecordPrompt(ParseDecisionResult parsed, const std::uint8_t* bytes,
		std::size_t length, bool auto_answered, nlohmann::json observation);

	bool active_ = false;
	std::string record_id_;
	std::string role_;
	std::ofstream file_;
	std::mutex mutex_;
	std::uint64_t sequence_ = 0;
	std::size_t bytes_written_ = 0;
	std::size_t max_log_bytes_ = 100 * 1024 * 1024;
	bool log_truncated_ = false;
	bool duel_ended_ = false;
	bool connection_closed_ = false;
	std::uint64_t prompt_id_ = 0;
	std::optional<DecisionPrompt> pending_;
	std::optional<SubmittedResponse> early_response_;
	bool suppress_next_response_ = false;
	std::string phase_ = "unknown";
	int turn_player_ = -1;
	std::optional<int> winner_;
	std::optional<int> win_reason_;
};

} // namespace agent_client
} // namespace ygo

#endif
