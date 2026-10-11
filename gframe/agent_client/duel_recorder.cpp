#include "duel_recorder.h"

#include "agent_controller.h"
#include "../deck_manager.h"
#include "../data_manager.h"
#include "../bufferio.h"
#include "../game.h"
#include "../network.h"

#include <chrono>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <utility>

namespace ygo::agent_client {
namespace {

constexpr std::size_t truncation_marker_reserve = 256;

std::int64_t NowUnixMs() {
	return std::chrono::duration_cast<std::chrono::milliseconds>(
		std::chrono::system_clock::now().time_since_epoch()).count();
}

std::string Base64(const void* bytes, std::size_t length) {
	static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
	const auto* input = static_cast<const std::uint8_t*>(bytes);
	std::string output;
	output.reserve(((length + 2) / 3) * 4);
	for(std::size_t i = 0; i < length; i += 3) {
		const std::uint32_t block = (std::uint32_t(input[i]) << 16)
			| (i + 1 < length ? std::uint32_t(input[i + 1]) << 8 : 0)
			| (i + 2 < length ? input[i + 2] : 0);
		output.push_back(alphabet[(block >> 18) & 63]);
		output.push_back(alphabet[(block >> 12) & 63]);
		output.push_back(i + 1 < length ? alphabet[(block >> 6) & 63] : '=');
		output.push_back(i + 2 < length ? alphabet[block & 63] : '=');
	}
	return output;
}

std::string PhaseName(std::uint16_t phase) {
	switch(phase) {
	case PHASE_DRAW: return "draw";
	case PHASE_STANDBY: return "standby";
	case PHASE_MAIN1: return "main_1";
	case PHASE_BATTLE_START: return "battle_start";
	case PHASE_BATTLE_STEP: return "battle_step";
	case PHASE_DAMAGE: return "damage";
	case PHASE_DAMAGE_CAL: return "damage_calculation";
	case PHASE_BATTLE: return "battle";
	case PHASE_MAIN2: return "main_2";
	case PHASE_END: return "end";
	default: return "unknown";
	}
}

void LocalizePrompt(nlohmann::json& prompt) {
	for(auto& candidate : prompt["candidates"]) {
		if(candidate.contains("card") && candidate["card"].contains("controller")) {
			auto& card = candidate["card"];
			const int controller = mainGame->LocalPlayer(card["controller"].get<int>());
			card["controller"] = controller;
			if(card.contains("location") && card.contains("sequence") && card["location"].is_string()) {
				const auto location = card["location"].get<std::string>();
				std::uint32_t mask = 0;
				if(location == "hand") mask = LOCATION_HAND;
				else if(location == "monster") mask = LOCATION_MZONE;
				else if(location == "spell") mask = LOCATION_SZONE;
				else if(location == "graveyard") mask = LOCATION_GRAVE;
				else if(location == "banished") mask = LOCATION_REMOVED;
				else if(location == "extra") mask = LOCATION_EXTRA;
				if(mask)
					card["instance_id"] = std::to_string(controller) + ":" + std::to_string(mask)
						+ ":" + std::to_string(card["sequence"].get<std::size_t>());
			}
		}
		if(candidate.contains("controller"))
			candidate["controller"] = mainGame->LocalPlayer(candidate["controller"].get<int>());
	}
}

template<typename Cards>
nlohmann::json CardIds(const Cards& cards) {
	auto ids = nlohmann::json::array();
	for(const auto& card : cards)
		ids.push_back(card->code);
	return ids;
}

} // namespace

DuelRecorder& DuelRecorder::Instance() {
	static DuelRecorder instance;
	return instance;
}

DuelRecorder::DuelRecorder() {
	const char* id = std::getenv("YGOPRO_DUEL_RECORD_ID");
	const char* role = std::getenv("YGOPRO_DUEL_RECORD_ROLE");
	const char* path = std::getenv("YGOPRO_DUEL_RECORD_PATH");
	if(!id || !*id || !role || !path || !*path)
		return;
	role_ = role;
	if(role_ != "host" && role_ != "guest")
		return;
	record_id_ = id;
	if(const char* limit = std::getenv("YGOPRO_DUEL_RECORD_MAX_BYTES")) {
		char* end = nullptr;
		errno = 0;
		const auto parsed = std::strtoull(limit, &end, 10);
		if(errno == 0 && end != limit && *end == '\0'
			&& parsed >= 1024 * 1024ULL && parsed <= 4096 * 1024 * 1024ULL)
			max_log_bytes_ = static_cast<std::size_t>(parsed);
	}
	file_.open(path, std::ios::binary | std::ios::trunc);
	active_ = file_.is_open();
	if(active_)
		Write({{"kind", "session"}, {"record_id", record_id_},
			{"schema_version", 1}, {"controller_space", "local"}});
}

void DuelRecorder::Write(nlohmann::json record) {
	if(!active_ || log_truncated_)
		return;
	record["seq"] = sequence_ + 1;
	record["role"] = role_;
	record["timestamp_unix_ms"] = NowUnixMs();
	const std::string line = record.dump() + '\n';
	if(bytes_written_ + truncation_marker_reserve >= max_log_bytes_
		|| line.size() > max_log_bytes_ - bytes_written_ - truncation_marker_reserve) {
		nlohmann::json marker{{"kind", "diagnostic_log_truncated"},
			{"seq", sequence_ + 1}, {"role", role_}, {"timestamp_unix_ms", NowUnixMs()}};
		const std::string marker_line = marker.dump() + '\n';
		file_.write(marker_line.data(), static_cast<std::streamsize>(marker_line.size()));
		file_.flush();
		bytes_written_ += marker_line.size();
		++sequence_;
		log_truncated_ = true;
		return;
	}
	file_.write(line.data(), static_cast<std::streamsize>(line.size()));
	file_.flush();
	bytes_written_ += line.size();
	++sequence_;
}

void DuelRecorder::OnWirePacket(bool incoming, const void* bytes, std::size_t length) {
	if(!active_ || !bytes || length < 3 || length > SIZE_NETWORK_BUFFER)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	Write({{"kind", "wire_packet"}, {"direction", incoming ? "inbound" : "outbound"},
		{"frame_base64", Base64(bytes, length)}});
	const auto* frame = static_cast<const std::uint8_t*>(bytes);
	const std::size_t declared_length = std::size_t(frame[0]) | (std::size_t(frame[1]) << 8);
	if(declared_length + 2 != length) {
		Write({{"kind", "error"}, {"code", "invalid_wire_frame_length"},
			{"declared_length", declared_length}, {"actual_length", length}});
		return;
	}
	if(incoming)
		return;
	if(frame[2] == CTOS_SURRENDER)
		Write({{"kind", "surrender"}});
	if(frame[2] == CTOS_RESPONSE || frame[2] == CTOS_HAND_RESULT || frame[2] == CTOS_TP_RESULT)
		CaptureResponse(frame[2], frame + 3, length - 3);
}

void DuelRecorder::CaptureResponse(std::uint8_t packet_type, const std::uint8_t* payload, std::size_t length) {
	if(suppress_next_response_) {
		suppress_next_response_ = false;
		return;
	}
	SubmittedResponse response{packet_type, {payload, payload + length}};
	if(!pending_) {
		if(early_response_)
			Write({{"kind", "error"}, {"code", "unpaired_response"}});
		early_response_ = std::move(response);
		return;
	}
	FinishResponse(response);
}

void DuelRecorder::FinishResponse(const SubmittedResponse& response) {
	nlohmann::json record{{"kind", "response"}, {"prompt_id", prompt_id_},
		{"packet_type", response.packet_type},
		{"payload_base64", Base64(response.payload.data(), response.payload.size())}};
	const auto decoded = DecodeDecisionResponse(*pending_, response.packet_type,
		response.payload.data(), response.payload.size());
	if(decoded.action) {
		auto action = *decoded.action;
		if(action.value("kind", "") == "select_places" && action.contains("places")) {
			for(auto& place : action["places"]) {
				if(place.contains("controller"))
					place["controller"] = mainGame->LocalPlayer(place["controller"].get<int>());
			}
			record["controller_space"] = "local";
		}
		record["action"] = std::move(action);
	} else
		record["error"] = {{"code", decoded.error.code}, {"message", decoded.error.message}};
	Write(std::move(record));
	pending_.reset();
}

void DuelRecorder::OnRoomJoined(const HostInfo& info) {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	Write({{"kind", "room_joined"}, {"mode", info.mode},
		{"no_shuffle_deck", info.no_shuffle_deck != 0},
		{"no_check_deck", info.no_check_deck != 0}, {"start_hand", info.start_hand},
		{"start_lp", info.start_lp}, {"draw_count", info.draw_count},
		{"time_limit", info.time_limit}});
}

void DuelRecorder::OnDeckSubmitted(const Deck& deck) {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	Write({{"kind", "deck_submitted"}, {"main", CardIds(deck.main)},
		{"extra", CardIds(deck.extra)}, {"side", CardIds(deck.side)}});
}

void DuelRecorder::RecordPrompt(ParseDecisionResult parsed, const std::uint8_t* bytes,
	std::size_t length, bool auto_answered, nlohmann::json observation) {
	if(!parsed.decision) {
		if(!parsed.error.code.empty() && parsed.error.code != "not_decision")
			Write({{"kind", "error"}, {"code", parsed.error.code},
				{"message", parsed.error.message}, {"raw_msg_base64", Base64(bytes, length)}});
		return;
	}
	auto prompt = parsed.decision->prompt();
	LocalizePrompt(prompt);
	const bool empty_chain = prompt.value("kind", "") == "chain"
		&& prompt["candidates"].size() == 1 && prompt["candidates"][0].value("kind", "") == "pass";
	if(empty_chain) {
		Write({{"kind", "automatic_pass"}, {"raw_msg_base64", Base64(bytes, length)}});
		if(early_response_)
			early_response_.reset();
		else
			suppress_next_response_ = true;
		return;
	}
	if(pending_)
		Write({{"kind", "error"}, {"code", "unpaired_prompt"}, {"prompt_id", prompt_id_}});
	pending_ = std::move(parsed.decision);
	++prompt_id_;
	observation["phase"] = phase_;
	observation["turn_player"] = turn_player_ < 0 ? 0 : turn_player_;
	Write({{"kind", "prompt"}, {"prompt_id", prompt_id_},
		{"raw_msg_base64", Base64(bytes, length)}, {"prompt", std::move(prompt)},
		{"observation", std::move(observation)}, {"auto_answered", auto_answered}});
	if(early_response_) {
		FinishResponse(*early_response_);
		early_response_.reset();
	}
}

void DuelRecorder::OnPreDuelDecision(DecisionSource source) {
	if(!active_)
		return;
	auto observation = AgentController::Instance().BuildObservation();
	std::lock_guard<std::mutex> lock(mutex_);
	RecordPrompt(ParseDecision(nullptr, 0, source), nullptr, 0, false, std::move(observation));
}

void DuelRecorder::OnGameMessage(const std::uint8_t* bytes, std::size_t length, bool already_answered) {
	if(!active_ || !bytes || length == 0)
		return;
	auto observation = AgentController::Instance().BuildObservation();
	std::vector<std::uint32_t> allowed_card_ids;
	if(bytes[0] == MSG_ANNOUNCE_CARD) {
		std::lock_guard<std::mutex> field_lock(mainGame->gMutex);
		for(const auto id : mainGame->dField.ancard) {
			if(id > 0)
				allowed_card_ids.push_back(static_cast<std::uint32_t>(id));
		}
	}
	std::lock_guard<std::mutex> lock(mutex_);
	if(bytes[0] == MSG_NEW_TURN && length >= 2)
		turn_player_ = mainGame->LocalPlayer(bytes[1]);
	else if(bytes[0] == MSG_NEW_PHASE && length >= 3)
		phase_ = PhaseName(std::uint16_t(bytes[1]) | (std::uint16_t(bytes[2]) << 8));
	else if(bytes[0] == MSG_WIN && length >= 3) {
		winner_ = bytes[1] < 2 ? mainGame->LocalPlayer(bytes[1]) : bytes[1];
		win_reason_ = bytes[2];
	}
	observation["phase"] = phase_;
	observation["turn_player"] = turn_player_ < 0 ? 0 : turn_player_;
	Write({{"kind", "visible_snapshot"}, {"message_type", bytes[0]},
		{"observation", observation}});
	if(bytes[0] == MSG_RETRY) {
		Write({{"kind", "error"}, {"code", "rejected_response"},
			{"raw_msg_base64", Base64(bytes, length)}});
		pending_.reset();
		return;
	}
	RecordPrompt(ParseDecision(bytes, length, DecisionSource::game_message,
		bytes[0] == MSG_ANNOUNCE_CARD ? &allowed_card_ids : nullptr,
		[](std::uint32_t description_id) {
			return BufferIO::EncodeUTF8String(std::wstring(dataManager.GetDesc(description_id)));
		}), bytes, length,
		already_answered, std::move(observation));
}

void DuelRecorder::OnDuelStart() {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	winner_.reset();
	win_reason_.reset();
	duel_ended_ = false;
	connection_closed_ = false;
	pending_.reset();
	early_response_.reset();
	suppress_next_response_ = false;
	phase_ = "unknown";
	turn_player_ = -1;
	Write({{"kind", "duel_start"}});
}

void DuelRecorder::OnDuelEnd() {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	if(duel_ended_)
		return;
	duel_ended_ = true;
	nlohmann::json record{{"kind", "duel_end"}, {"win_seen", winner_.has_value()}};
	if(winner_)
		record["winner"] = *winner_ == 2 ? "draw"
			: (*winner_ == 0 ? role_ : (role_ == "host" ? "guest" : "host"));
	if(win_reason_) record["win_reason"] = *win_reason_;
	Write(std::move(record));
}

void DuelRecorder::OnConnectionClosed(const char* reason) {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	if(duel_ended_ || connection_closed_)
		return;
	connection_closed_ = true;
	Write({{"kind", "connection_closed"}, {"reason", reason}});
}

void DuelRecorder::OnReplaySavePrompt() {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	Write({{"kind", "replay_save_pending"}});
}

void DuelRecorder::OnReplaySaveResolved() {
	if(!active_)
		return;
	std::lock_guard<std::mutex> lock(mutex_);
	Write({{"kind", "replay_save_resolved"}});
}

} // namespace ygo::agent_client
