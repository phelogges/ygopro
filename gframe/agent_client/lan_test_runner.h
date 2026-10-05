#ifndef YGO_AGENT_LAN_TEST_RUNNER_H
#define YGO_AGENT_LAN_TEST_RUNNER_H

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <string>

namespace ygo::agent_client {

// Opt-in real LAN protocol automation; never synthesizes UI input.
class LanTestRunner final {
public:
	static LanTestRunner& Instance();
	bool Active() const noexcept;
	bool Visible() const noexcept;
	const std::string& Role() const noexcept;
	void Start(); // main thread, after Game::Initialize
	void Poll(); // main thread, before taking Game::gMutex
	// Payload excludes the STOC type; copies facts only, on the network thread.
	void OnPacket(std::uint8_t type, const std::uint8_t* payload, std::size_t length);
	void OnError(std::string error); // optional transport error notification

private:
	LanTestRunner();
	void Finish(); // main thread; writes result and closes only headless devices
	const std::string role_;
	const bool visible_;
	std::mutex mutex_;
	bool started_ = false;
	bool finished_ = false;
	bool joined_ = false;
	bool deck_sent_ = false;
	bool ready_sent_ = false;
	bool start_sent_ = false;
	bool duel_started_ = false;
	bool surrender_sent_ = false;
	bool win_seen_ = false;
	bool duel_end_ = false;
	bool ready_[2] = {false, false};
	std::uint8_t self_type_ = 0xff;
	std::uint8_t winner_ = 0xff;
	std::uint8_t win_reason_ = 0xff;
	std::string error_;
	std::string deck_path_;
	std::string result_path_;
	std::string surrender_path_;
	std::string checkpoint_path_;
	std::uint16_t port_ = 7921;
	std::chrono::milliseconds timeout_{300000};
	std::chrono::steady_clock::time_point start_time_{};
};

} // namespace ygo::agent_client
#endif
