#include "lan_test_runner.h"
#include "agent_controller.h"

#include "../deck_manager.h"
#include "../duelclient.h"
#include "../game.h"
#include "../netserver.h"
#include "../../ocgcore/common.h"

#include <nlohmann/json.hpp>
#include <charconv>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace ygo::agent_client {
namespace {

std::string Environment(const char* name, const char* fallback = "") {
	const auto* value = std::getenv(name);
	return value && *value ? value : fallback;
}

int IntegerEnvironment(const char* name, int fallback, int minimum, int maximum) {
	const auto value = Environment(name);
	if(value.empty()) return fallback;
	int result = 0;
	const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
	if(parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()
	   || result < minimum || result > maximum)
		throw std::runtime_error(std::string("Invalid environment variable: ") + name);
	return result;
}

constexpr std::uint32_t loopback_address = 0x7f000001U;

} // namespace

LanTestRunner& LanTestRunner::Instance() {
	static LanTestRunner runner;
	return runner;
}

LanTestRunner::LanTestRunner()
	: role_(Environment("YGOPRO_AGENT_E2E_ROLE")),
	  visible_(Environment("YGOPRO_AGENT_E2E_GUI") == "1") {}

bool LanTestRunner::Active() const noexcept { return !role_.empty(); }
bool LanTestRunner::Visible() const noexcept { return Active() && visible_; }
const std::string& LanTestRunner::Role() const noexcept { return role_; }

void LanTestRunner::Start() {
	if(!Active()) return;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(started_) return;
		started_ = true;
		start_time_ = std::chrono::steady_clock::now();
	}
	result_path_ = Environment("YGOPRO_AGENT_E2E_RESULT_PATH");
	if(result_path_.empty()) result_path_ = "agent-e2e-" + role_ + ".json";
	deck_path_ = Environment("YGOPRO_AGENT_E2E_DECK", "deck/test/test.ydk");
	surrender_path_ = Environment("YGOPRO_AGENT_E2E_SURRENDER_PATH");
	if(Visible()) checkpoint_path_ = Environment("YGOPRO_AGENT_E2E_CHECKPOINT_PATH");
	try {
		if(role_ != "host" && role_ != "guest") throw std::runtime_error("E2E role must be host or guest");
		if(Environment("YGOPRO_AGENT_ENABLE") != "1")
			throw std::runtime_error("E2E requires YGOPRO_AGENT_ENABLE=1");
		if(!AgentController::Instance().IsControlling())
			throw std::runtime_error("Agent controller initialization failed or control is disabled");
		if(!mainGame || !mainGame->device) throw std::runtime_error("Game device is not initialized");
		port_ = static_cast<std::uint16_t>(IntegerEnvironment("YGOPRO_AGENT_E2E_PORT", 7921, 1, 65535));
		timeout_ = std::chrono::milliseconds(IntegerEnvironment("YGOPRO_AGENT_E2E_TIMEOUT_MS", 300000, 1, 3600000));
		if(!std::filesystem::is_regular_file(std::filesystem::u8path(deck_path_)))
			throw std::runtime_error("Deck file does not exist: " + deck_path_);
		{
			std::lock_guard<std::mutex> game_lock(mainGame->gMutex);
			mainGame->bot_mode = false;
			// StartClient bypasses the main-menu button that normally hides this window.
			mainGame->wMainMenu->setVisible(false);
			mainGame->ebNickName->setText(role_ == "host" ? L"Agent E2E Host" : L"Agent E2E Guest");
			mainGame->ebJoinHost->setText(L"127.0.0.1");
			mainGame->ebJoinPass->setText(L"");
			if(role_ == "host") {
				mainGame->ebServerName->setText(L"Agent E2E Single Duel");
				mainGame->ebServerPass->setText(L"");
				mainGame->cbRule->setSelected(5);
				mainGame->cbMatchMode->setSelected(0);
				mainGame->cbHostLFlist->setSelected(mainGame->cbHostLFlist->getItemCount() - 1);
				mainGame->cbDuelRule->setSelected(DEFAULT_DUEL_RULE - 1);
				mainGame->ebStartHand->setText(L"5");
				mainGame->ebStartLP->setText(L"8000");
				mainGame->ebDrawCount->setText(L"1");
				mainGame->ebTimeLimit->setText(L"0");
				mainGame->chkNoCheckDeck->setChecked(true);
				mainGame->chkNoShuffleDeck->setChecked(Environment("YGOPRO_AGENT_E2E_FIXED_DECK") == "1");
			}
		}
		if(role_ == "host" && !NetServer::StartServer(port_, loopback_address, nullptr, false))
			throw std::runtime_error("Cannot start loopback duel server");
		if(!DuelClient::StartClient(loopback_address, port_, role_ == "host"))
			throw std::runtime_error("Cannot start loopback duel client");
	} catch(const std::exception& exception) {
		OnError(exception.what());
		Finish();
	}
}

void LanTestRunner::OnError(std::string error) {
	if(!Active()) return;
	std::lock_guard<std::mutex> lock(mutex_);
	if(error_.empty() && !finished_) error_ = std::move(error);
}

void LanTestRunner::OnPacket(std::uint8_t type, const std::uint8_t* payload, std::size_t length) {
	if(!Active()) return;
	std::lock_guard<std::mutex> lock(mutex_);
	if(!started_ || finished_) return;
	if(length && !payload) { error_ = "Null LAN packet payload"; return; }
	switch(type) {
	case STOC_JOIN_GAME:
		if(length < sizeof(STOC_JoinGame)) error_ = "Truncated STOC_JOIN_GAME";
		else joined_ = true;
		break;
	case STOC_TYPE_CHANGE:
		if(length < sizeof(STOC_TypeChange)) error_ = "Truncated STOC_TYPE_CHANGE";
		else {
			self_type_ = payload[0] & 0x0f;
			if(self_type_ >= 2) error_ = "Test client was not assigned a duelist seat";
		}
		break;
	case STOC_HS_PLAYER_CHANGE:
		if(length < sizeof(STOC_HS_PlayerChange)) error_ = "Truncated STOC_HS_PlayerChange";
		else {
			const auto position = payload[0] >> 4;
			const auto state = payload[0] & 0x0f;
			if(position < 2) {
				if(state == PLAYERCHANGE_READY) ready_[position] = true;
				else if(state == PLAYERCHANGE_NOTREADY || state == PLAYERCHANGE_LEAVE) ready_[position] = false;
			}
		}
		break;
	case STOC_DUEL_START: duel_started_ = true; break;
	case STOC_GAME_MSG:
		if(length && payload[0] == MSG_WIN) {
			if(length < 3) error_ = "Truncated MSG_WIN";
			else { win_seen_ = true; winner_ = payload[1]; win_reason_ = payload[2]; }
		}
		break;
	case STOC_DUEL_END: duel_end_ = true; break;
	case STOC_ERROR_MSG:
		if(length < sizeof(STOC_ErrorMsg)) error_ = "Truncated STOC_ERROR_MSG";
		else {
			STOC_ErrorMsg packet{};
			std::memcpy(&packet, payload, sizeof packet);
			error_ = "Game server error: msg=" + std::to_string(packet.msg) + ", code=" + std::to_string(packet.code);
		}
		break;
	default: break;
	}
}

void LanTestRunner::Poll() {
	if(!Active()) return;
	bool send_deck = false;
	bool may_start = false;
	bool done = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!started_ || finished_) return;
		if(error_.empty() && std::chrono::steady_clock::now() - start_time_ > timeout_)
			error_ = "E2E timeout while waiting for " + std::string(!joined_ ? "room join" : !duel_started_ ? "duel start" : "duel result");
		if(duel_end_ && !win_seen_ && error_.empty())
			error_ = "Duel ended without an authoritative MSG_WIN";
		done = !error_.empty() || duel_end_;
		send_deck = !done && joined_ && self_type_ < 2 && !deck_sent_;
		may_start = !done && role_ == "host" && ready_sent_ && !start_sent_ && ready_[0] && ready_[1];
	}
	if(done) { Finish(); return; }
	if(!checkpoint_path_.empty()) {
		std::error_code filesystem_error;
		const bool reached = std::filesystem::is_regular_file(std::filesystem::u8path(checkpoint_path_), filesystem_error);
		if(filesystem_error && filesystem_error != std::errc::no_such_file_or_directory) {
			OnError("Cannot inspect E2E checkpoint trigger: " + filesystem_error.message());
			Finish();
			return;
		}
		if(reached) { Finish(); return; }
	}
	if(!AgentController::Instance().IsControlling()) {
		OnError("Agent control was disabled during E2E; no manual fallback is available");
		Finish();
		return;
	}
	if(!surrender_path_.empty()) {
		bool may_surrender = false;
		{
			std::lock_guard<std::mutex> lock(mutex_);
			may_surrender = duel_started_ && !duel_end_ && !surrender_sent_;
		}
		if(may_surrender) {
			std::error_code filesystem_error;
			const bool triggered = std::filesystem::is_regular_file(std::filesystem::u8path(surrender_path_), filesystem_error);
			if(filesystem_error && filesystem_error != std::errc::no_such_file_or_directory) {
				OnError("Cannot inspect E2E surrender trigger: " + filesystem_error.message());
				Finish();
				return;
			}
			if(triggered) {
				bool send_surrender = false;
				{
					std::lock_guard<std::mutex> lock(mutex_);
					if(error_.empty() && duel_started_ && !duel_end_ && !surrender_sent_) {
						surrender_sent_ = true;
						send_surrender = true;
					}
				}
				if(send_surrender) DuelClient::SendPacketToServer(CTOS_SURRENDER);
			}
		}
	}
	if(send_deck) {
		try {
			const auto path = std::filesystem::u8path(deck_path_).wstring();
			std::lock_guard<std::mutex> game_lock(mainGame->gMutex);
			if(!deckManager.LoadCurrentDeck(path.c_str()) || deckManager.current_deck.main.empty())
				throw std::runtime_error("Cannot load a nonempty test deck: " + deck_path_);
			DuelClient::SendUpdateDeck(deckManager.current_deck);
			DuelClient::SendPacketToServer(CTOS_HS_READY);
			std::lock_guard<std::mutex> lock(mutex_);
			deck_sent_ = true;
			ready_sent_ = true;
		} catch(const std::exception& exception) { OnError(exception.what()); Finish(); }
	}
	if(may_start) {
		std::lock_guard<std::mutex> game_lock(mainGame->gMutex);
		if(mainGame->chkHostPrepReady[0]->isChecked() && mainGame->chkHostPrepReady[1]->isChecked()) {
			DuelClient::SendPacketToServer(CTOS_HS_START);
			std::lock_guard<std::mutex> lock(mutex_);
			start_sent_ = true;
		}
	}
}

void LanTestRunner::Finish() {
	nlohmann::json result;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(finished_) return;
		finished_ = true;
		result = {{"schema_version", 1}, {"role", role_},
			{"status", error_.empty() ? "finished" : "error"}, {"error", error_},
			{"joined", joined_}, {"self_type", self_type_}, {"deck_sent", deck_sent_},
			{"ready_sent", ready_sent_}, {"start_sent", start_sent_},
			{"duel_started", duel_started_}, {"surrender_sent", surrender_sent_},
			{"win_seen", win_seen_}, {"duel_end", duel_end_},
			{"winner", win_seen_ ? nlohmann::json(winner_) : nlohmann::json(nullptr)},
			{"win_reason", win_seen_ ? nlohmann::json(win_reason_) : nlohmann::json(nullptr)},
			{"ready", {ready_[0], ready_[1]}}, {"deck_path", deck_path_}, {"port", port_},
			{"elapsed_ms", std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start_time_).count()}};
	}
	try {
		std::ofstream output(std::filesystem::u8path(result_path_), std::ios::binary | std::ios::trunc);
		if(!output) throw std::runtime_error("Cannot open E2E result file: " + result_path_);
		output << result.dump(2) << '\n';
		output.flush();
		if(!output) throw std::runtime_error("Cannot write E2E result file: " + result_path_);
	} catch(const std::exception& exception) {
		std::cerr << exception.what() << '\n' << result.dump() << '\n';
	}
	if(Visible()) AgentController::Instance().Stop();
	else if(mainGame && mainGame->device) mainGame->device->closeDevice();
}

} // namespace ygo::agent_client
