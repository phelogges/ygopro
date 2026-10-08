#ifndef YGO_AGENT_CLIENT_AGENT_CONTROLLER_H
#define YGO_AGENT_CLIENT_AGENT_CONTROLLER_H

#include "agent_process.h"
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
	static AgentController &Instance();
	void Initialize();
	void Stop();
	void Toggle(); // main thread, F10
	bool IsControlling() const noexcept;
	bool HasPendingDecision() const noexcept;
	std::uint64_t SubmissionSerial() const noexcept;
	void OnResponseSubmitted();
	void OnWirePacket(bool incoming, const void *bytes, std::size_t length);
	void OnPreDuelDecision(DecisionSource source);
	void OnGameMessage(const std::uint8_t *bytes, std::size_t length, bool already_answered);
	void OnDuelStart();
	void OnDuelEnd();
	void Poll(); // main thread
	// Returns only information visible to this client; also used by local
	// recording.
	nlohmann::json BuildObservation() const;

  private:
	struct Pending {
		DecisionPrompt decision;
		std::uint64_t prompt_id;
		std::int64_t deadline_unix_ms;
		std::uint64_t state_version = 0;
		nlohmann::json frozen_snapshot;
		std::vector<nlohmann::json> frozen_events;
		bool submitted = false;
		bool frozen = false;
	};
	struct Completed {
		std::uint64_t prompt_id;
		std::uint64_t state_version;
		std::uint64_t event_id;
		bool sync;
		bool status;
		bool background;
		bool terminal;
		bool ready;
		bool query_result;
		bool action_result;
		std::string duel_id;
		agent::HttpResult result;
	};
	struct ActionReceipt {
		std::string duel_id;
		std::uint64_t prompt_id = 0;
		std::uint64_t state_version = 0;
		std::string action_id;
		std::string status;
		int attempts = 0;
	};
	struct TerminalPending {
		std::string duel_id;
		std::vector<nlohmann::json> events;
		std::uint64_t acknowledged_event_id;
		bool history_complete;
		int attempts = 0;
	};

	AgentController() = default;
	~AgentController();
	AgentController(const AgentController &) = delete;
	AgentController &operator=(const AgentController &) = delete;

	void OnDecision(DecisionPrompt decision);
	void SubmitPending();
	void SubmitBackgroundSync();
	void SubmitTerminalSync();
	void SubmitActionResult();
	void HandleQuery(const nlohmann::json &reply, std::uint64_t prompt_id, std::uint64_t state_version);
	bool StartService();
	bool RestartTransport();
	void OnHttpResult(agent::HttpResult result);
	void RecordEvent(const std::uint8_t *bytes, std::size_t length, bool card_hint_visible);
	void Log(const nlohmann::json &record);
	void FailCurrent(const std::string &code);
	std::string NewId();

	mutable std::mutex mutex_;
	std::mutex log_mutex_;
	agent::HttpClient http_;
	AgentProcess process_;
	bool initialized_ = false;
	bool available_ = false;
	bool controlling_ = false;
	bool v3_ = false;
	bool ready_ = false;
	std::string profile_ = "config";
	std::string boot_nonce_;
	std::string server_executable_ = "./agent-server";
	std::string host_ = "127.0.0.1";
	std::string token_;
	std::uint16_t port_ = 8910;
	int timeout_ms_ = 15000;
	std::string database_sha256_;
	std::string session_id_;
	std::string duel_id_;
	std::uint64_t next_prompt_id_ = 0;
	std::uint64_t next_event_id_ = 0;
	std::uint64_t next_state_version_ = 0;
	std::uint64_t acknowledged_state_version_ = 0;
	std::uint64_t acknowledged_event_id_ = 0;
	std::uint64_t in_flight_prompt_id_ = 0;
	std::uint64_t in_flight_event_id_ = 0;
	std::uint64_t in_flight_state_version_ = 0;
	bool in_flight_sync_ = false;
	bool in_flight_status_ = false;
	bool in_flight_background_ = false;
	bool in_flight_terminal_ = false;
	bool in_flight_ready_ = false;
	bool in_flight_query_result_ = false;
	bool in_flight_action_result_ = false;
	bool action_result_queued_ = false;
	std::string in_flight_duel_id_;
	std::optional<ActionReceipt> action_receipt_;
	bool needs_status_ = false;
	bool history_complete_ = true;
	std::optional<Pending> pending_;
	std::deque<Completed> completed_;
	std::deque<std::string> notices_;
	std::vector<nlohmann::json> events_;
	std::optional<TerminalPending> terminal_;
	std::string phase_ = "unknown";
	int turn_player_ = -1;
	std::ofstream log_file_;
	std::size_t log_size_ = 0;
	bool log_truncated_ = false;
	std::atomic<std::uint64_t> submission_serial_{0};
};

} // namespace ygo::agent_client
#endif
