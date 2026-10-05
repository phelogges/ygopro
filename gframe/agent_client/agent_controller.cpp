#include "agent_controller.h"

#include "sha256_file.h"
#include "../client_card.h"
#include "../bufferio.h"
#include "../duelclient.h"
#include "../game.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <random>
#include <sstream>
#include <string_view>
#include <utility>

namespace ygo::agent_client {
namespace {

constexpr std::size_t max_log_size = 10 * 1024 * 1024;
constexpr std::size_t max_pending_events = 512;

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
		const std::uint32_t a = input[i];
		const std::uint32_t b = i + 1 < length ? input[i + 1] : 0;
		const std::uint32_t c = i + 2 < length ? input[i + 2] : 0;
		const std::uint32_t block = (a << 16) | (b << 8) | c;
		output.push_back(alphabet[(block >> 18) & 63]);
		output.push_back(alphabet[(block >> 12) & 63]);
		output.push_back(i + 1 < length ? alphabet[(block >> 6) & 63] : '=');
		output.push_back(i + 2 < length ? alphabet[block & 63] : '=');
	}
	return output;
}

bool EnabledByEnvironment() {
	const char* value = std::getenv("YGOPRO_AGENT_ENABLE");
	return value && std::string(value) == "1";
}

std::optional<int> EnvInt(const char* name, int minimum, int maximum) {
	const char* value = std::getenv(name);
	if(!value || !*value)
		return std::nullopt;
	char* end = nullptr;
	const long parsed = std::strtol(value, &end, 10);
	if(!end || *end || parsed < minimum || parsed > maximum)
		return std::nullopt;
	return static_cast<int>(parsed);
}

std::string PhaseName(std::uint16_t value) {
	switch(value) {
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

std::string PositionName(std::uint8_t position) {
	switch(position) {
	case POS_FACEUP_ATTACK: return "face_up_attack";
	case POS_FACEDOWN_ATTACK: return "face_down_attack";
	case POS_FACEUP_DEFENSE: return "face_up_defense";
	case POS_FACEDOWN_DEFENSE: return "face_down_defense";
	default: return "unknown";
	}
}

bool CardKnown(const ClientCard& card, int player, std::uint32_t location) {
	if(card.code == 0)
		return false;
	if(location == LOCATION_DECK)
		return false;
	if(player == 0)
		return true;
	if(location == LOCATION_HAND)
		return false;
	if(location == LOCATION_GRAVE)
		return true;
	return (card.position & POS_FACEUP) != 0;
}

nlohmann::json SerializeCard(const ClientCard& card, int player,
	std::string_view zone, std::uint32_t location, std::size_t sequence) {
	nlohmann::json data{
		{"instance_id", std::to_string(player) + ":" + std::to_string(location) + ":" + std::to_string(sequence)},
		{"controller", player},
		{"location", zone},
		{"sequence", sequence},
		{"position", PositionName(card.position)},
		{"known", CardKnown(card, player, location)}
	};
	if(CardKnown(card, player, location)) {
		data["card_id"] = card.code;
		if(card.position & POS_FACEUP) {
			data["attack"] = card.attack;
			data["defense"] = card.defense;
			data["level"] = card.level;
			data["rank"] = card.rank;
			data["link"] = card.link;
		}
		data["owner"] = card.owner;
		if(!card.counters.empty())
			data["counters"] = card.counters;
	}
	return data;
}

void AppendZone(nlohmann::json& zones, int player, const char* name,
	std::uint32_t location, const std::vector<ClientCard*>& cards,
	bool hide_contents) {
	const auto count = std::count_if(cards.begin(), cards.end(), [](const auto* card) { return card != nullptr; });
	nlohmann::json zone{{"player", player}, {"name", name}, {"count", count}, {"cards", nlohmann::json::array()}};
	if(!hide_contents) {
		for(std::size_t i = 0; i < cards.size(); ++i) {
			if(cards[i])
				zone["cards"].push_back(SerializeCard(*cards[i], player, name, location, i));
		}
	}
	zones.push_back(std::move(zone));
}

void ShowAgentMessage(const std::string& message) {
	wchar_t converted[512]{};
	BufferIO::DecodeUTF8(message.c_str(), converted);
	mainGame->AddChatMsg(converted, 9);
}

void DismissPromptWindows() {
	std::lock_guard<std::mutex> ui_lock(mainGame->gMutex);
	for(auto& fading : mainGame->fadingList) {
		if(fading.signalAction) {
			fading.signalAction = false;
			fading.guiFading->setRelativePosition(fading.fadingSize);
			fading.guiFading->setVisible(false);
		}
	}
	for(irr::gui::IGUIElement* window : {mainGame->wQuery, mainGame->wOptions,
		mainGame->wPosSelect, mainGame->wCardSelect, mainGame->wANCard,
		mainGame->wANNumber, mainGame->wANAttribute, mainGame->wANRace,
		mainGame->wHand, mainGame->wFTSelect})
		window->setVisible(false);
}

} // namespace

AgentController& AgentController::Instance() {
	static AgentController instance;
	return instance;
}

AgentController::~AgentController() { Stop(); }

std::string AgentController::NewId() {
	std::random_device source;
	std::ostringstream output;
	output << std::hex << std::setfill('0');
	for(int i = 0; i < 4; ++i)
		output << std::setw(8) << source();
	return output.str();
}

void AgentController::Initialize() {
	std::lock_guard<std::mutex> lock(mutex_);
	if(initialized_)
		return;
	initialized_ = true;
	if(!EnabledByEnvironment())
		return;
	if(const char* value = std::getenv("YGOPRO_AGENT_HOST"))
		host_ = value;
	if(const char* value = std::getenv("YGOPRO_AGENT_TOKEN"))
		token_ = value;
	if(const auto value = EnvInt("YGOPRO_AGENT_PORT", 1, 65535))
		port_ = static_cast<std::uint16_t>(*value);
	if(const auto value = EnvInt("YGOPRO_AGENT_TIMEOUT_MS", 100, 120000))
		timeout_ms_ = *value;
	if(host_ != "127.0.0.1" && host_ != "localhost" && host_ != "::1" && token_.empty())
		return;
	const char* database_path = std::getenv("YGOPRO_AGENT_DB_PATH");
	const auto digest = agent::ComputeFileSha256(database_path && *database_path ? database_path : "cards.cdb");
	if(!digest)
		return;
	database_sha256_ = digest.hex;
	if(const char* path = std::getenv("YGOPRO_AGENT_LOG_PATH"); path && *path)
		log_file_.open(path, std::ios::binary | std::ios::app);
	session_id_ = NewId();
	available_ = http_.Start(host_, port_, token_, timeout_ms_,
		[this](agent::HttpResult result) { OnHttpResult(std::move(result)); });
	controlling_ = available_;
}

void AgentController::Stop() {
	{
		std::lock_guard<std::mutex> lock(mutex_);
		controlling_ = false;
		available_ = false;
		pending_.reset();
	}
	http_.Stop();
}

bool AgentController::IsControlling() const noexcept {
	std::lock_guard<std::mutex> lock(mutex_);
	return controlling_;
}

bool AgentController::HasPendingDecision() const noexcept {
	std::lock_guard<std::mutex> lock(mutex_);
	return controlling_ && pending_.has_value();
}

std::uint64_t AgentController::SubmissionSerial() const noexcept {
	return submission_serial_.load();
}

void AgentController::OnResponseSubmitted() {
	submission_serial_.fetch_add(1);
	std::lock_guard<std::mutex> lock(mutex_);
	pending_.reset();
}

void AgentController::Log(const nlohmann::json& record) {
	std::lock_guard<std::mutex> lock(log_mutex_);
	if(!log_file_)
		return;
	const std::string line = record.dump() + '\n';
	if(log_size_ + line.size() > max_log_size)
		return;
	log_file_ << line;
	log_file_.flush();
	log_size_ += line.size();
}

void AgentController::OnWirePacket(bool incoming, const void* bytes, std::size_t length) {
	if(length == 0 || length > SIZE_NETWORK_BUFFER)
		return;
	Log({{"kind", "wire_packet"}, {"direction", incoming ? "inbound" : "outbound"},
		{"timestamp_unix_ms", NowUnixMs()}, {"frame_base64", Base64(bytes, length)}});
}

void AgentController::OnDuelStart() {
	std::lock_guard<std::mutex> lock(mutex_);
	if(duel_id_.empty())
		duel_id_ = NewId();
	phase_ = "unknown";
	turn_player_ = -1;
	events_.clear();
}

void AgentController::OnDuelEnd() {
	nlohmann::json terminal_events;
	std::string duel_id;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		terminal_events = events_;
		duel_id = duel_id_;
		pending_.reset();
		duel_id_.clear();
		events_.clear();
	}
	if(!duel_id.empty())
		Log({{"kind", "duel_finished"}, {"duel_id", duel_id},
			{"events", std::move(terminal_events)}, {"timestamp_unix_ms", NowUnixMs()}});
}

void AgentController::RecordEvent(const std::uint8_t* bytes, std::size_t length) {
	if(!bytes || length == 0)
		return;
	const std::uint8_t type = bytes[0];
	nlohmann::json event{{"event_id", ++next_event_id_}, {"kind", "game_message"},
		{"message_type", type}};
	if(type == MSG_NEW_TURN && length >= 2) {
		turn_player_ = mainGame->LocalPlayer(bytes[1]);
		event["kind"] = "turn_started";
		event["player"] = turn_player_;
		event["turn"] = mainGame->dInfo.turn;
	} else if(type == MSG_NEW_PHASE && length >= 3) {
		const std::uint16_t raw = std::uint16_t(bytes[1]) | (std::uint16_t(bytes[2]) << 8);
		phase_ = PhaseName(raw);
		event["kind"] = "phase_changed";
		event["phase"] = phase_;
	} else if(type == MSG_DRAW && length >= 3) {
		event["kind"] = "cards_drawn";
		event["player"] = mainGame->LocalPlayer(bytes[1]);
		event["count"] = bytes[2];
	} else if(type == MSG_MOVE && length >= 17) {
		event["kind"] = "card_moved";
		event["from_player"] = mainGame->LocalPlayer(bytes[5]);
		event["from_location"] = bytes[6];
		event["from_sequence"] = bytes[7];
		event["to_player"] = mainGame->LocalPlayer(bytes[9]);
		event["to_location"] = bytes[10];
		event["to_sequence"] = bytes[11];
	} else if(type == MSG_WIN && length >= 3) {
		event["kind"] = "duel_ended";
		event["winner"] = bytes[1] < 2 ? mainGame->LocalPlayer(bytes[1]) : bytes[1];
		event["reason"] = bytes[2];
	}
	if(events_.size() >= max_pending_events)
		events_.erase(events_.begin());
	events_.push_back(std::move(event));
}

nlohmann::json AgentController::BuildObservation() const {
	nlohmann::json snapshot;
	std::lock_guard<std::mutex> lock(mainGame->gMutex);
	snapshot["self_player"] = 0;
	snapshot["turn"] = mainGame->dInfo.turn;
	snapshot["life_points"] = {mainGame->dInfo.lp[0], mainGame->dInfo.lp[1]};
	snapshot["zones"] = nlohmann::json::array();
	for(int player = 0; player < 2; ++player) {
		const auto& field = mainGame->dField;
		AppendZone(snapshot["zones"], player, "deck", LOCATION_DECK, field.deck[player], true);
		AppendZone(snapshot["zones"], player, "hand", LOCATION_HAND, field.hand[player], player != 0);
		AppendZone(snapshot["zones"], player, "monster", LOCATION_MZONE, field.mzone[player], false);
		AppendZone(snapshot["zones"], player, "spell", LOCATION_SZONE, field.szone[player], false);
		AppendZone(snapshot["zones"], player, "graveyard", LOCATION_GRAVE, field.grave[player], false);
		AppendZone(snapshot["zones"], player, "banished", LOCATION_REMOVED, field.remove[player], false);
		AppendZone(snapshot["zones"], player, "extra", LOCATION_EXTRA, field.extra[player], false);
	}
	return snapshot;
}

void AgentController::OnGameMessage(const std::uint8_t* bytes, std::size_t length, bool already_answered) {
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!initialized_ || !available_ || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode)
			return;
		RecordEvent(bytes, length);
	}
	if(already_answered)
		return;
	std::vector<std::uint32_t> allowed_card_ids;
	if(bytes && length && bytes[0] == MSG_ANNOUNCE_CARD) {
		std::lock_guard<std::mutex> lock(mainGame->gMutex);
		for(const auto id : mainGame->dField.ancard) {
			if(id > 0)
				allowed_card_ids.push_back(static_cast<std::uint32_t>(id));
		}
	}
	auto parsed = ParseDecision(bytes, length, DecisionSource::game_message,
		bytes && length && bytes[0] == MSG_ANNOUNCE_CARD ? &allowed_card_ids : nullptr);
	if(!parsed.decision) {
		if(!parsed.error.code.empty() && parsed.error.code != "not_decision") {
			{
				std::lock_guard<std::mutex> lock(mutex_);
				pending_.reset();
			}
			FailCurrent(parsed.error.code);
		}
		return;
	}
	OnDecision(std::move(*parsed.decision));
}

void AgentController::OnPreDuelDecision(DecisionSource source) {
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!initialized_ || !available_)
			return;
	}
	auto parsed = ParseDecision(nullptr, 0, source);
	if(parsed.decision)
		OnDecision(std::move(*parsed.decision));
}

void AgentController::OnDecision(DecisionPrompt decision) {
	bool cancel_previous = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		cancel_previous = in_flight_prompt_id_ != 0;
		if(duel_id_.empty())
			duel_id_ = NewId();
		const auto now = NowUnixMs();
		std::int64_t deadline = now + timeout_ms_;
		if(mainGame->dInfo.time_limit && mainGame->dInfo.time_left[0])
			deadline = std::min(deadline, now + std::max(0, int(mainGame->dInfo.time_left[0]) * 1000 - 1000));
		pending_.emplace(Pending{std::move(decision), ++next_prompt_id_, deadline});
	}
	if(cancel_previous && !RestartTransport()) {
		FailCurrent("transport_start_failed");
		return;
	}
	Log({{"kind", "prompt_available"}, {"timestamp_unix_ms", NowUnixMs()}});
	if(IsControlling())
		SubmitPending();
}

bool AgentController::RestartTransport() {
	http_.Stop();
	const bool started = http_.Start(host_, port_, token_, timeout_ms_,
		[this](agent::HttpResult result) { OnHttpResult(std::move(result)); });
	std::lock_guard<std::mutex> lock(mutex_);
	available_ = started;
	in_flight_prompt_id_ = 0;
	completed_.clear();
	return started;
}

void AgentController::SubmitPending() {
	const auto snapshot = BuildObservation();
	nlohmann::json request;
	std::uint64_t prompt_id = 0;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_ || !controlling_ || !pending_ || pending_->submitted || in_flight_prompt_id_)
			return;
		prompt_id = pending_->prompt_id;
		auto prompt = pending_->decision.prompt();
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
						card["instance_id"] = std::to_string(controller) + ":" + std::to_string(mask) + ":" + std::to_string(card["sequence"].get<std::size_t>());
				}
			}
			if(candidate.contains("controller"))
				candidate["controller"] = mainGame->LocalPlayer(candidate["controller"].get<int>());
		}
		request = {
			{"schema_version", 1}, {"session_id", session_id_}, {"duel_id", duel_id_},
			{"prompt_id", prompt_id}, {"database_sha256", database_sha256_},
			{"deadline_unix_ms", pending_->deadline_unix_ms},
			{"observation", snapshot}, {"prompt", std::move(prompt)}
		};
		request["observation"]["turn_player"] = turn_player_ < 0 ? 0 : turn_player_;
		request["observation"]["phase"] = phase_;
		request["observation"]["events"] = events_;
		if(const char* role = std::getenv("YGOPRO_AGENT_E2E_ROLE"); role && *role)
			request["observation"]["test_role"] = role;
		in_flight_prompt_id_ = prompt_id;
	}
	Log({{"kind", "decision_request"}, {"message", request}, {"timestamp_unix_ms", NowUnixMs()}});
	if(!http_.Submit(request.dump())) {
		FailCurrent("transport_busy");
		return;
	}
	std::lock_guard<std::mutex> lock(mutex_);
	if(pending_ && pending_->prompt_id == prompt_id)
		pending_->submitted = true;
	events_.clear();
}

void AgentController::OnHttpResult(agent::HttpResult result) {
	std::lock_guard<std::mutex> lock(mutex_);
	completed_.push_back(Completed{in_flight_prompt_id_, std::move(result)});
	in_flight_prompt_id_ = 0;
}

void AgentController::FailCurrent(const std::string& code) {
	{
		std::lock_guard<std::mutex> lock(mutex_);
		controlling_ = false;
		in_flight_prompt_id_ = 0;
		notices_.push_back("Agent 已交还人工操作：" + code);
	}
	Log({{"kind", "agent_error"}, {"code", code}, {"timestamp_unix_ms", NowUnixMs()}});
}

void AgentController::Toggle() {
	Initialize();
	bool next = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_)
		{
			ShowAgentMessage("Agent 未就绪，请检查连接和卡片数据库配置");
			return;
		}
		controlling_ = !controlling_;
		next = controlling_;
		if(pending_) {
			pending_->prompt_id = ++next_prompt_id_;
			pending_->submitted = false;
			pending_->deadline_unix_ms = NowUnixMs() + timeout_ms_;
		}
	}
	if(!next) {
		RestartTransport(); // Cancels the in-flight request and its late response.
	} else {
		if(!RestartTransport()) {
			FailCurrent("transport_start_failed");
			return;
		}
		DismissPromptWindows();
		SubmitPending();
	}
	Log({{"kind", "control_changed"}, {"agent", next}, {"timestamp_unix_ms", NowUnixMs()}});
	ShowAgentMessage(next ? "Agent 已接管决斗（F10 交还人工）" : "已切换为人工操作（F10 恢复 Agent）");
}

void AgentController::Poll() {
	std::deque<Completed> completed;
	std::deque<std::string> notices;
	bool expired = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		completed.swap(completed_);
		notices.swap(notices_);
		expired = controlling_ && pending_ && pending_->submitted && NowUnixMs() > pending_->deadline_unix_ms;
	}
	if(expired)
		FailCurrent("timeout");
	for(const auto& notice : notices)
		ShowAgentMessage(notice);
	for(auto& item : completed) {
		std::optional<DecisionPrompt> decision;
		std::string session_id;
		std::string duel_id;
		{
			std::lock_guard<std::mutex> lock(mutex_);
			if(!controlling_ || !pending_ || pending_->prompt_id != item.prompt_id)
				continue;
			decision = pending_->decision;
			session_id = session_id_;
			duel_id = duel_id_;
		}
		if(item.result.status != 200 || !item.result.error.empty()) {
			FailCurrent(item.result.error.empty() ? "http_error" : item.result.error);
			continue;
		}
		try {
			const auto reply = nlohmann::json::parse(item.result.body);
			if(!reply.is_object() || reply.value("schema_version", 0) != 1 ||
			   reply.value("session_id", std::string{}) != session_id ||
			   reply.value("duel_id", std::string{}) != duel_id ||
			   reply.value("prompt_id", std::uint64_t{0}) != item.prompt_id ||
			   !reply.contains("action")) {
				FailCurrent("invalid_response_envelope");
				continue;
			}
			auto action = reply.at("action");
			if(action.is_object() && action.value("kind", std::string{}) == "select_places" &&
			   action.contains("places") && action["places"].is_array()) {
				for(auto& place : action["places"])
					if(place.is_object() && place.contains("controller") && place["controller"].is_number_integer())
						place["controller"] = mainGame->LocalPlayer(place["controller"].get<int>());
			}
			const auto encoded = EncodeDecision(*decision, action);
			if(!encoded.response) {
				FailCurrent(encoded.error.code);
				continue;
			}
			{
				std::lock_guard<std::mutex> lock(mutex_);
				if(!controlling_ || !pending_ || pending_->prompt_id != item.prompt_id)
					continue;
				pending_.reset();
			}
			const auto& response = *encoded.response;
			DismissPromptWindows();
			if(response.packet_type == CTOS_RESPONSE) {
				DuelClient::SetResponseB(const_cast<std::uint8_t*>(response.payload.data()), response.payload.size());
				DuelClient::SendResponse();
			} else if(response.packet_type == CTOS_HAND_RESULT && response.payload.size() == 1) {
				CTOS_HandResult packet{};
				packet.res = response.payload[0];
				DuelClient::SendPacketToServer(CTOS_HAND_RESULT, packet);
			} else if(response.packet_type == CTOS_TP_RESULT && response.payload.size() == 1) {
				CTOS_TPResult packet{};
				packet.res = response.payload[0];
				DuelClient::SendPacketToServer(CTOS_TP_RESULT, packet);
			}
			Log({{"kind", "decision_submitted"}, {"prompt_id", item.prompt_id},
				{"reason", reply.value("reason", std::string{})}, {"timestamp_unix_ms", NowUnixMs()}});
			if(reply.contains("reason") && reply["reason"].is_string())
				ShowAgentMessage("Agent：" + reply["reason"].get<std::string>());
		} catch(const nlohmann::json::exception&) {
			FailCurrent("invalid_json_response");
		}
	}
}

} // namespace ygo::agent_client
