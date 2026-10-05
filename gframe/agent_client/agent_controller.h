#ifndef YGO_AGENT_CLIENT_AGENT_CONTROLLER_H
#define YGO_AGENT_CLIENT_AGENT_CONTROLLER_H

#include "decision_codec.h"
#include "http_client.h"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace ygo::agent_client {

// Bridges the existing LAN client to the semantic Agent API. Game/GUI access
// remains on the caller's game thread; HTTP callbacks only enqueue results.
class AgentController final {
public:
	static AgentController& Instance();
	void Initialize();
	void Stop();
	void Toggle(); // main thread, F10
	bool IsControlling() const noexcept;
	bool HasPendingDecision() const noexcept;
	std::uint64_t SubmissionSerial() const noexcept;
	void OnResponseSubmitted();
	void OnWirePacket(bool incoming, const void* bytes, std::size_t length);
	void OnPreDuelDecision(DecisionSource source);
	void OnGameMessage(const std::uint8_t* bytes, std::size_t length, bool already_answered);
	void OnDuelStart();
	void OnDuelEnd();
	void Poll(); // main thread

private:
	struct Pending {
		DecisionPrompt decision;
		std::uint64_t prompt_id;
		std::int64_t deadline_unix_ms;
		bool submitted = false;
	};
	struct Completed {
		std::uint64_t prompt_id;
		agent::HttpResult result;
	};

	AgentController() = default;
	~AgentController();
	AgentController(const AgentController&) = delete;
	AgentController& operator=(const AgentController&) = delete;

	void OnDecision(DecisionPrompt decision);
	void SubmitPending();
	bool RestartTransport();
	void OnHttpResult(agent::HttpResult result);
	void RecordEvent(const std::uint8_t* bytes, std::size_t length);
	void Log(const nlohmann::json& record);
	void FailCurrent(const std::string& code);
	std::string NewId();
	nlohmann::json BuildObservation() const;

	mutable std::mutex mutex_;
	std::mutex log_mutex_;
	agent::HttpClient http_;
	bool initialized_ = false;
	bool available_ = false;
	bool controlling_ = false;
	std::string host_ = "127.0.0.1";
	std::string token_;
	std::uint16_t port_ = 8910;
	int timeout_ms_ = 15000;
	std::string database_sha256_;
	std::string session_id_;
	std::string duel_id_;
	std::uint64_t next_prompt_id_ = 0;
	std::uint64_t next_event_id_ = 0;
	std::uint64_t in_flight_prompt_id_ = 0;
	std::optional<Pending> pending_;
	std::deque<Completed> completed_;
	std::deque<std::string> notices_;
	std::vector<nlohmann::json> events_;
	std::string phase_ = "unknown";
	int turn_player_ = -1;
	std::ofstream log_file_;
	std::size_t log_size_ = 0;
	std::atomic<std::uint64_t> submission_serial_{0};
};

} // namespace ygo::agent_client
#endif
