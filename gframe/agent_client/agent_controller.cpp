#include "agent_controller.h"

#include "sha256_file.h"
#include "game_event_codec.h"
#include "../client_card.h"
#include "../data_manager.h"
#include "../bufferio.h"
#include "../duelclient.h"
#include "../game.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <limits>
#include <map>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace ygo::agent_client {
namespace {

constexpr std::size_t max_log_size = 10 * 1024 * 1024;
constexpr std::size_t max_e2e_log_size = 100 * 1024 * 1024;
constexpr std::string_view log_truncated_marker = "{\"kind\":\"diagnostic_log_truncated\"}\n";
constexpr std::size_t max_pending_events = 512;
// Numeric values already exposed by SerializeCard. A single comparison path
// handles changes to attributes, races, levels, combat values, and scales.
constexpr std::array<const char*, 13> comparable_card_values = {
	"attack", "defense", "level", "rank", "link", "link_marker", "type",
	"attribute", "race", "base_attack", "base_defense", "left_scale", "right_scale"
};

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

std::string ResponseFailureCode(const agent::HttpResult& result) {
	if(result.status >= 400 && !result.body.empty()) {
		const auto body = nlohmann::json::parse(result.body, nullptr, false);
		if(body.is_object() && body.contains("schema_version") && body["schema_version"].is_number_integer() &&
		   body["schema_version"] == 3 && body.contains("error") && body["error"].is_object()) {
			const auto& error = body["error"];
			if(error.contains("code") && error["code"].is_string()) {
				const auto code = error["code"].get<std::string>();
				if(!code.empty() && code.size() <= 64 &&
				   std::all_of(code.begin(), code.end(), [](unsigned char ch) {
					   return (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_';
				   }))
					return code;
			}
		}
	}
	return result.error.empty() ? "http_error" : result.error;
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
	case POS_FACEUP: return "face_up";
	case POS_FACEDOWN: return "face_down";
	default: return "unknown";
	}
}

std::uint32_t ReadU32(const std::uint8_t* bytes) {
	return std::uint32_t(bytes[0]) | (std::uint32_t(bytes[1]) << 8) |
		(std::uint32_t(bytes[2]) << 16) | (std::uint32_t(bytes[3]) << 24);
}

bool PositionInspectable(int player, std::uint8_t location, bool graveyard_inspection_allowed) {
	if(location == LOCATION_DECK || (location == LOCATION_HAND && player != 0))
		return false;
	if(location == LOCATION_GRAVE && !graveyard_inspection_allowed)
		return false;
	return true;
}

bool NonessentialMessage(std::uint8_t type) {
	switch(type) {
	case MSG_WAITING: case MSG_START: case MSG_UPDATE_DATA: case MSG_UPDATE_CARD:
	case MSG_REQUEST_DECK: case MSG_REFRESH_DECK: case MSG_RETRY:
	case MSG_SELECT_BATTLECMD: case MSG_SELECT_IDLECMD: case MSG_SELECT_EFFECTYN:
	case MSG_SELECT_YESNO: case MSG_SELECT_OPTION: case MSG_SELECT_CARD:
	case MSG_SELECT_CHAIN: case MSG_SELECT_PLACE: case MSG_SELECT_POSITION:
	case MSG_SELECT_TRIBUTE: case MSG_SELECT_COUNTER: case MSG_SELECT_SUM:
	case MSG_SELECT_DISFIELD: case MSG_SORT_CARD: case MSG_SELECT_UNSELECT_CARD:
	case MSG_ROCK_PAPER_SCISSORS: case MSG_ANNOUNCE_RACE:
	case MSG_ANNOUNCE_ATTRIB: case MSG_ANNOUNCE_CARD: case MSG_ANNOUNCE_NUMBER:
	case MSG_CARD_SELECTED: case MSG_AI_NAME: case MSG_SHOW_HINT:
		return true;
	default: return false;
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
	return (card.position & POS_FACEUP) != 0;
}

bool Observed(const ClientCard& card, std::uint32_t flag) {
	return card.observed_query_location == card.location && (card.observed_query_flags & flag) != 0;
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
		if(card.cHint || card.chValue) {
			data["hint_type"] = card.cHint;
			data["hint_value"] = card.chValue;
		}
		for(const auto& [description_id, count] : card.desc_hints) {
			if(count > 0)
				data["description_hints"].push_back({{"description_id", description_id}, {"count", count}});
		}
		if(card.position & POS_FACEUP) {
			if(Observed(card, QUERY_ATTACK)) data["attack"] = card.attack >= 0 ? nlohmann::json(card.attack) : nlohmann::json(nullptr);
			if(Observed(card, QUERY_DEFENSE)) data["defense"] = card.defense >= 0 ? nlohmann::json(card.defense) : nlohmann::json(nullptr);
			if(Observed(card, QUERY_LEVEL)) data["level"] = card.level;
			if(Observed(card, QUERY_RANK)) data["rank"] = card.rank;
			if(Observed(card, QUERY_LINK)) {
				data["link"] = card.link;
				data["link_marker"] = card.link_marker;
			}
			if(Observed(card, QUERY_TYPE)) data["type"] = card.type;
			if(Observed(card, QUERY_ATTRIBUTE)) data["attribute"] = card.attribute;
			if(Observed(card, QUERY_RACE)) data["race"] = card.race;
			if(Observed(card, QUERY_BASE_ATTACK)) data["base_attack"] = card.base_attack;
			if(Observed(card, QUERY_BASE_DEFENSE)) data["base_defense"] = card.base_defense;
			if(Observed(card, QUERY_LSCALE)) data["left_scale"] = card.lscale;
			if(Observed(card, QUERY_RSCALE)) data["right_scale"] = card.rscale;
		}
		if(Observed(card, QUERY_OWNER) && card.owner <= 1)
			data["owner"] = mainGame->LocalPlayer(card.owner);
		if(!card.counters.empty()) {
			auto counters = nlohmann::json::object();
			for(const auto& [counter_type, amount] : card.counters)
				counters[std::to_string(counter_type)] = amount;
			data["counters"] = std::move(counters);
		}
	}
	if(!card.overlayed.empty() && (card.position & POS_FACEUP)) {
		data["overlay_count"] = card.overlayed.size();
		data["overlay_cards"] = nlohmann::json::array();
		for(std::size_t i = 0; i < card.overlayed.size(); ++i) {
			const auto* material = card.overlayed[i];
			if(!material) continue;
			nlohmann::json overlay{{"instance_id", data["instance_id"].get<std::string>() + ":overlay:" + std::to_string(i)}};
			if(material->code) overlay["card_id"] = material->code;
			data["overlay_cards"].push_back(std::move(overlay));
		}
	}
	if(card.equipTarget && (card.position & POS_FACEUP))
		data["equipped_to"] = std::to_string(card.equipTarget->controler) + ":" +
			std::to_string(card.equipTarget->location) + ":" + std::to_string(card.equipTarget->sequence);
	if(!card.cardTarget.empty() && (card.position & POS_FACEUP)) {
		data["targets"] = nlohmann::json::array();
		for(const auto* target : card.cardTarget)
			data["targets"].push_back(std::to_string(target->controler) + ":" +
				std::to_string(target->location) + ":" + std::to_string(target->sequence));
	}
	return data;
}

void AppendZone(nlohmann::json& zones, int player, const char* name,
	std::uint32_t location, const std::vector<ClientCard*>& cards,
	bool hide_contents, bool hide_unknown = false) {
	const auto count = std::count_if(cards.begin(), cards.end(), [](const auto* card) { return card != nullptr; });
	nlohmann::json zone{{"player", player}, {"name", name}, {"count", count}, {"cards", nlohmann::json::array()}};
	if(!hide_contents) {
		for(std::size_t i = 0; i < cards.size(); ++i) {
			if(cards[i] && (!hide_unknown || CardKnown(*cards[i], player, location)))
				zone["cards"].push_back(SerializeCard(*cards[i], player, name, location, i));
		}
	}
	zone["hidden_count"] = count - zone["cards"].size();
	zones.push_back(std::move(zone));
}

void ShowAgentMessage(const std::string& message) {
	wchar_t converted[512]{};
	BufferIO::DecodeUTF8(message.c_str(), converted);
	mainGame->AddChatMsg(converted, 9);
}

void DismissPromptWindows() {
	std::lock_guard<std::mutex> ui_lock(mainGame->gMutex);
	const auto prompt_windows = {mainGame->wQuery, mainGame->wOptions,
		mainGame->wPosSelect, mainGame->wCardSelect, mainGame->wANCard,
		mainGame->wANNumber, mainGame->wANAttribute, mainGame->wANRace,
		mainGame->wHand, mainGame->wFTSelect};
	// DrawGUI reopens windows with pending fade-in frames. Remove their animations
	// before hiding them, including fades that do not carry a response signal.
	for(auto it = mainGame->fadingList.begin(); it != mainGame->fadingList.end();) {
		if(std::find(prompt_windows.begin(), prompt_windows.end(), it->guiFading) == prompt_windows.end()) {
			++it;
			continue;
		}
		it->guiFading->setRelativePosition(it->fadingSize);
		it = mainGame->fadingList.erase(it);
	}
	for(irr::gui::IGUIElement* window : prompt_windows) {
		mainGame->SetImageButtonDrawing(window, false);
		window->setVisible(false);
	}
	if(mainGame->dField.highlighting_card) {
		mainGame->dField.highlighting_card->is_highlighting = false;
		mainGame->dField.highlighting_card = nullptr;
	}
	mainGame->stCardListTip->setVisible(false);
	mainGame->dField.ShowCancelOrFinishButton(0);
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
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(initialized_)
			return;
		initialized_ = true;
	}
	if(!EnabledByEnvironment())
		return;
	const char *protocol = std::getenv("YGOPRO_AGENT_PROTOCOL");
	const char *e2e_role = std::getenv("YGOPRO_AGENT_E2E_ROLE");
	v3_ = (protocol && std::string(protocol) == "v3") ||
		(!(protocol && std::string(protocol) == "v2") && !(e2e_role && *e2e_role));
	if(v3_) {
		if(const char *profile = std::getenv("YGOPRO_AGENT_CONFIG"); profile && *profile)
			profile_ = profile;
		if(const char *executable = std::getenv("YGOPRO_AGENT_SERVER_EXECUTABLE"); executable && *executable)
			server_executable_ = executable;
		host_ = "127.0.0.1";
		token_ = NewId() + NewId();
		boot_nonce_ = NewId();
	} else {
		if(const char *value = std::getenv("YGOPRO_AGENT_HOST"))
			host_ = value;
		if(const char *value = std::getenv("YGOPRO_AGENT_TOKEN"))
			token_ = value;
		if(const auto value = EnvInt("YGOPRO_AGENT_PORT", 1, 65535))
			port_ = static_cast<std::uint16_t>(*value);
		if(const auto value = EnvInt("YGOPRO_AGENT_TIMEOUT_MS", 100, 120000))
			timeout_ms_ = *value;
		if(host_ != "127.0.0.1" && host_ != "localhost" && host_ != "::1" && token_.empty())
			return;
	}
	const char *database_path = std::getenv("YGOPRO_AGENT_DB_PATH");
	const auto digest = agent::ComputeFileSha256(database_path && *database_path ? database_path : "cards.cdb");
	if(!digest)
		return;
	database_sha256_ = digest.hex;
	if(const char *path = std::getenv("YGOPRO_AGENT_LOG_PATH"); path && *path)
		log_file_.open(path, std::ios::binary | std::ios::app);
	session_id_ = NewId();
	if(!StartService()) {
		std::lock_guard<std::mutex> lock(mutex_);
		notices_.push_back("Agent 服务启动失败，请检查 .agents 配置和端口");
	}
}

bool AgentController::StartService() {
	if(v3_) {
		AgentProcessReady startup;
		std::string error;
		if(!process_.Start(server_executable_, profile_, token_, boot_nonce_, startup, error)) {
			Log({{"kind", "agent_error"},
				 {"code", "process_start_failed"},
				 {"message", error},
				 {"timestamp_unix_ms", NowUnixMs()}});
			return false;
		}
		port_ = startup.port;
		timeout_ms_ = startup.decision_timeout_ms;
	}
	const bool started = http_.Start(host_, port_, token_, timeout_ms_,
									 [this](agent::HttpResult result) { OnHttpResult(std::move(result)); });
	if(!started) {
		process_.Stop();
		return false;
	}
	{
		std::lock_guard<std::mutex> lock(mutex_);
		available_ = true;
		ready_ = !v3_;
		controlling_ = !v3_;
		if(v3_) {
			in_flight_prompt_id_ = std::numeric_limits<std::uint64_t>::max();
			in_flight_ready_ = true;
		}
	}
	if(v3_ && !http_.Get("/v3/ready", 3000)) {
		http_.Stop();
		process_.Stop();
		std::lock_guard<std::mutex> lock(mutex_);
		available_ = false;
		in_flight_prompt_id_ = 0;
		in_flight_ready_ = false;
		return false;
	}
	return true;
}

void AgentController::Stop() {
	{
		std::lock_guard<std::mutex> lock(mutex_);
		controlling_ = false;
		available_ = false;
		pending_.reset();
		action_result_queued_ = false;
	}
	http_.Stop();
	process_.Stop();
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

void AgentController::OnDeckSubmitted(const Deck &deck) {
	const auto section = [](const std::vector<const CardDataC *> &cards) {
		std::map<std::uint32_t, std::size_t> counts;
		for(const auto *card : cards)
			++counts[card->code];
		auto entries = nlohmann::json::array();
		for(const auto &[card_id, count] : counts)
			entries.push_back({{"card_id", card_id}, {"count", count}});
		return entries;
	};
	nlohmann::json manifest{{"main", section(deck.main)}, {"extra", section(deck.extra)},
							{"side", section(deck.side)}};
	std::lock_guard<std::mutex> lock(mutex_);
	submitted_deck_manifest_ = std::move(manifest);
}

void AgentController::Log(const nlohmann::json& record) {
	std::lock_guard<std::mutex> lock(log_mutex_);
	if(!log_file_ || log_truncated_)
		return;
	const std::string line = record.dump() + '\n';
	const char* role = std::getenv("YGOPRO_AGENT_E2E_ROLE");
	const std::size_t limit = role && *role ? max_e2e_log_size : max_log_size;
	if(log_size_ + log_truncated_marker.size() > limit
	   || line.size() > limit - log_size_ - log_truncated_marker.size()) {
		log_file_ << log_truncated_marker;
		log_file_.flush();
		log_size_ += log_truncated_marker.size();
		log_truncated_ = true;
		return;
	}
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
	if(duel_id_.empty()) {
		duel_id_ = NewId();
		next_event_id_ = 0;
		next_state_version_ = 0;
		acknowledged_event_id_ = 0;
		acknowledged_state_version_ = 0;
		history_complete_ = true;
		needs_status_ = false;
		events_.clear();
	}
	phase_ = "unknown";
	turn_player_ = -1;
	last_visible_cards_.clear();
}

void AgentController::OnDuelEnd() {
	nlohmann::json terminal_events;
	std::string duel_id;
	bool cancel_in_flight = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		terminal_events = events_;
		duel_id = duel_id_;
		cancel_in_flight = !duel_id.empty() && available_ && in_flight_prompt_id_ && !in_flight_terminal_;
		if(!duel_id.empty() && !events_.empty())
			terminal_ = TerminalPending{duel_id, events_, acknowledged_event_id_, history_complete_};
		pending_.reset();
		action_receipt_.reset();
		action_result_queued_ = false;
		needs_status_ = false;
		duel_id_.clear();
		submitted_deck_manifest_.reset();
		duel_deck_manifest_.reset();
		deck_manifest_acknowledged_ = false;
		events_.clear();
		last_visible_cards_.clear();
	}
	if(!duel_id.empty())
		Log({{"kind", "duel_finished"}, {"duel_id", duel_id},
			{"events", std::move(terminal_events)}, {"timestamp_unix_ms", NowUnixMs()}});
	if(cancel_in_flight && !RestartTransport())
		Log({{"kind", "terminal_transport_restart_failed"}, {"duel_id", duel_id},
			{"timestamp_unix_ms", NowUnixMs()}});
	SubmitTerminalSync();
}

void AgentController::RecordEvent(const std::uint8_t* bytes, std::size_t length, bool card_hint_visible) {
	if(!bytes || length == 0)
		return;
	const std::uint8_t type = bytes[0];
	if(NonessentialMessage(type))
		return;
	// A card hint can refer to a hidden card. Only retain its value when the
	// referenced card is currently known from this client's perspective.
	if(type == MSG_CARD_HINT && length >= 10 && !card_hint_visible)
		return;
	nlohmann::json event{{"event_id", ++next_event_id_}, {"kind", "game_message"},
		{"message_type", type}};
	bool parsed = true;
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
		event["to_player"] = mainGame->LocalPlayer(bytes[9]);
		event["to_location"] = bytes[10];
		const bool inspect_grave = !mainGame->dField.cant_check_grave;
		if(PositionInspectable(event["from_player"].get<int>(), bytes[6], inspect_grave))
			event["from_sequence"] = bytes[7];
		if(PositionInspectable(event["to_player"].get<int>(), bytes[10], inspect_grave))
			event["to_sequence"] = bytes[11];
		event["reason_flags"] = ReadU32(bytes + 13);
	} else if(type == MSG_WIN && length >= 3) {
		event["kind"] = "duel_ended";
		event["winner"] = bytes[1] < 2 ? mainGame->LocalPlayer(bytes[1]) : bytes[1];
		event["reason"] = bytes[2];
	} else if(type == MSG_HINT && length >= 7) {
		event["kind"] = "hint_observed";
		event["hint_type"] = bytes[1];
		event["player"] = mainGame->LocalPlayer(bytes[2]);
		event["value"] = ReadU32(bytes + 3);
		if(bytes[1] == HINT_OPSELECTED) {
			if(const auto* face = CoinFaceForSelectedOption(ReadU32(bytes + 3)))
				event["option"] = face;
		}
	} else if(GameEventMessage(type)) {
		const auto decoded = ParseGameEvent(bytes, length,
			mainGame->dInfo.isFirst, !mainGame->dField.cant_check_grave,
			mainGame->dField.deck_reversed);
		if(decoded) {
			event.update(*decoded);
		} else {
			parsed = false;
			event["kind"] = "unparsed_game_message";
		}
	} else if(type == MSG_CARD_HINT && length >= 10) {
		event["kind"] = "card_hint_observed";
		event["player"] = mainGame->LocalPlayer(bytes[1]);
		event["location"] = bytes[2] & 0x7f;
		event["sequence"] = bytes[3];
		event["hint_type"] = bytes[5];
		event["value"] = ReadU32(bytes + 6);
	} else if(type == MSG_PLAYER_HINT && length >= 7) {
		event["kind"] = "player_hint_observed";
		event["player"] = mainGame->LocalPlayer(bytes[1]);
		event["hint_type"] = bytes[2];
		event["value"] = ReadU32(bytes + 3);
	} else if(type == MSG_CONFIRM_CARDS && length >= 4 &&
	          length >= 4 + std::size_t(bytes[3]) * 7) {
		event["kind"] = "cards_revealed";
		event["cards"] = nlohmann::json::array();
		const bool inspect_grave = !mainGame->dField.cant_check_grave;
		for(std::size_t i = 0; i < bytes[3]; ++i) {
			const auto* card = bytes + 4 + i * 7;
			const int player = mainGame->LocalPlayer(card[4]);
			nlohmann::json item{{"player", player}, {"location", card[5]}};
			const auto code = ReadU32(card);
			if(code) item["card_id"] = code & 0x7fffffffU;
			if(PositionInspectable(player, card[5], inspect_grave)) item["sequence"] = card[6];
			event["cards"].push_back(std::move(item));
		}
	} else if(type == MSG_CHAINING && length >= 17) {
		event["kind"] = "effect_activated";
		event["controller"] = mainGame->LocalPlayer(bytes[9]);
		event["location"] = bytes[10];
		if(bytes[10] == LOCATION_MZONE) event["sequence"] = bytes[11];
		event["chain_index"] = bytes[16];
		const auto code = ReadU32(bytes + 1) & 0x7fffffffU;
		if(code) event["card_id"] = code;
		event["description_id"] = ReadU32(bytes + 12);
	} else if((type == MSG_CHAINED || type == MSG_CHAIN_SOLVING || type == MSG_CHAIN_SOLVED ||
	           type == MSG_CHAIN_NEGATED || type == MSG_CHAIN_DISABLED) && length >= 2) {
		event["kind"] = type == MSG_CHAINED ? "chain_link_added" :
			type == MSG_CHAIN_SOLVING ? "chain_link_solving" :
			type == MSG_CHAIN_SOLVED ? "chain_link_solved" :
			type == MSG_CHAIN_NEGATED ? "chain_link_negated" : "chain_link_disabled";
		event["chain_index"] = bytes[1];
	} else if(type == MSG_CHAIN_END && length == 1) {
		event["kind"] = "chain_ended";
	} else if((type == MSG_DAMAGE || type == MSG_RECOVER || type == MSG_PAY_LPCOST ||
	           type == MSG_LPUPDATE) && length >= 6) {
		event["kind"] = type == MSG_DAMAGE ? "life_points_damaged" :
			type == MSG_RECOVER ? "life_points_recovered" :
			type == MSG_PAY_LPCOST ? "life_points_paid" : "life_points_updated";
		event["player"] = mainGame->LocalPlayer(bytes[1]);
		event["value"] = ReadU32(bytes + 2);
	} else if(type == MSG_ATTACK && length >= 9) {
		event["kind"] = "attack_declared";
		event["attacker_player"] = mainGame->LocalPlayer(bytes[1]);
		event["attacker_location"] = bytes[2];
		event["attacker_sequence"] = bytes[3];
		event["target_player"] = mainGame->LocalPlayer(bytes[5]);
		event["target_location"] = bytes[6];
		if(bytes[6]) event["target_sequence"] = bytes[7];
	} else if(type == MSG_POS_CHANGE && length >= 10) {
		event["kind"] = "position_changed";
		event["player"] = mainGame->LocalPlayer(bytes[5]);
		event["location"] = bytes[6];
		event["sequence"] = bytes[7];
		event["from_position"] = PositionName(bytes[8]);
		event["to_position"] = PositionName(bytes[9]);
	} else if(type == MSG_SET && length >= 9) {
		event["kind"] = "card_set";
		event["player"] = mainGame->LocalPlayer(bytes[5]);
		event["location"] = bytes[6];
		event["sequence"] = bytes[7];
	} else if(type == MSG_BECOME_TARGET && length >= 2 &&
	          length >= 2 + std::size_t(bytes[1]) * 4) {
		event["kind"] = "cards_targeted";
		event["targets"] = nlohmann::json::array();
		for(std::size_t i = 0; i < bytes[1]; ++i) {
			const auto* target = bytes + 2 + i * 4;
			const int player = mainGame->LocalPlayer(target[0]);
			nlohmann::json item{{"player", player}, {"location", target[1]}};
			if(PositionInspectable(player, target[1], !mainGame->dField.cant_check_grave))
				item["sequence"] = target[2];
			event["targets"].push_back(std::move(item));
		}
	} else if(type == MSG_BATTLE && length >= 27) {
		event["kind"] = "battle_values_observed";
		event["attacker_player"] = mainGame->LocalPlayer(bytes[1]);
		event["attacker_location"] = bytes[2];
		event["attacker_sequence"] = bytes[3];
		event["attacker_attack"] = static_cast<std::int32_t>(ReadU32(bytes + 5));
		event["attacker_defense"] = static_cast<std::int32_t>(ReadU32(bytes + 9));
		event["target_player"] = mainGame->LocalPlayer(bytes[14]);
		event["target_location"] = bytes[15];
		if(bytes[15]) event["target_sequence"] = bytes[16];
		event["target_attack"] = static_cast<std::int32_t>(ReadU32(bytes + 18));
		event["target_defense"] = static_cast<std::int32_t>(ReadU32(bytes + 22));
	} else if(type == MSG_DAMAGE_STEP_START || type == MSG_DAMAGE_STEP_END) {
		event["kind"] = type == MSG_DAMAGE_STEP_START ? "damage_step_started" : "damage_step_ended";
	} else if(type == MSG_ATTACK_DISABLED) {
		event["kind"] = "attack_disabled";
	} else if((type == MSG_SUMMONING || type == MSG_SPSUMMONING || type == MSG_FLIPSUMMONING) && length >= 9) {
		event["kind"] = type == MSG_SUMMONING ? "normal_summon_started" :
			type == MSG_SPSUMMONING ? "special_summon_started" : "flip_summon_started";
		event["player"] = mainGame->LocalPlayer(bytes[5]);
		event["location"] = bytes[6];
		event["sequence"] = bytes[7];
		const auto code = ReadU32(bytes + 1) & 0x7fffffffU;
		if(code) event["card_id"] = code;
	} else if(type == MSG_SUMMONED || type == MSG_SPSUMMONED || type == MSG_FLIPSUMMONED) {
		event["kind"] = type == MSG_SUMMONED ? "normal_summon_finished" :
			type == MSG_SPSUMMONED ? "special_summon_finished" : "flip_summon_finished";
	} else if(type == MSG_SHUFFLE_DECK || type == MSG_SHUFFLE_HAND || type == MSG_SHUFFLE_EXTRA) {
		event["kind"] = "shuffle_message_observed";
		if(length >= 2) event["player"] = mainGame->LocalPlayer(bytes[1]);
		event["zone"] = type == MSG_SHUFFLE_DECK ? "deck" :
			type == MSG_SHUFFLE_HAND ? "hand" : "extra";
	} else {
		parsed = false;
		event["kind"] = "unparsed_game_message";
	}
	if(!parsed) {
		history_complete_ = false;
		Log({{"kind", "event_decode_incomplete"}, {"message_type", type},
			 {"message_length", length}, {"timestamp_unix_ms", NowUnixMs()}});
	}
	if(events_.size() >= max_pending_events) {
		history_complete_ = false;
		Log({{"kind", "event_queue_overflow"}, {"message_type", type},
			 {"event_limit", max_pending_events}, {"timestamp_unix_ms", NowUnixMs()}});
		return;
	}
	events_.push_back(std::move(event));
}

AgentController::VisibleCards AgentController::CaptureVisibleCardValues() const {
	VisibleCards current;
	std::lock_guard<std::mutex> lock(mainGame->gMutex);
	const auto capture_zone = [&](int player, std::uint32_t location, const char* name,
		const std::vector<ClientCard*>& cards) {
		for(std::size_t sequence = 0; sequence < cards.size(); ++sequence) {
			const auto* source = cards[sequence];
			if(!source || !(source->position & POS_FACEUP) || !CardKnown(*source, player, location))
				continue;
			const auto card = SerializeCard(*source, player, name, location, sequence);
			nlohmann::json values = nlohmann::json::object();
			for(const auto* field : comparable_card_values) {
				if(card.contains(field))
					values[field] = card[field];
			}
			current.emplace(card["instance_id"].get<std::string>(),
				VisibleCardValues{card["card_id"].get<std::uint32_t>(),
					player, location, static_cast<int>(sequence), std::move(values)});
		}
	};
	for(int player = 0; player < 2; ++player) {
		const auto& field = mainGame->dField;
		capture_zone(player, LOCATION_MZONE, "monster", field.mzone[player]);
		capture_zone(player, LOCATION_SZONE, "spell", field.szone[player]);
		capture_zone(player, LOCATION_GRAVE, "graveyard", field.grave[player]);
		capture_zone(player, LOCATION_REMOVED, "banished", field.remove[player]);
		capture_zone(player, LOCATION_EXTRA, "extra", field.extra[player]);
	}
	return current;
}

void AgentController::RecordVisibleValueChanges(const VisibleCards& current, std::uint8_t message_type) {
	const bool update_message = message_type == MSG_UPDATE_CARD || message_type == MSG_UPDATE_DATA;
	if(update_message) {
		for(const auto& [instance_id, after] : current) {
			const auto previous = last_visible_cards_.find(instance_id);
			if(previous == last_visible_cards_.end() || previous->second.card_id != after.card_id)
				continue;
			for(const auto* field : comparable_card_values) {
				if(!previous->second.values.contains(field) || !after.values.contains(field) ||
				   previous->second.values[field] == after.values[field])
					continue;
				if(events_.size() >= max_pending_events) {
					history_complete_ = false;
					Log({{"kind", "event_queue_overflow"}, {"message_type", message_type},
						 {"event_limit", max_pending_events}, {"timestamp_unix_ms", NowUnixMs()}});
					break;
				}
			events_.push_back({{"event_id", ++next_event_id_}, {"kind", "card_value_changed"},
				{"message_type", message_type}, {"player", after.player}, {"location", after.location},
				{"sequence", after.sequence}, {"field", field},
				{"from_value", previous->second.values[field]}, {"to_value", after.values[field]}});
			}
		}
	}
	last_visible_cards_ = current;
}

nlohmann::json AgentController::BuildObservation() const {
	nlohmann::json snapshot;
	std::lock_guard<std::mutex> lock(mainGame->gMutex);
	snapshot["self_player"] = 0;
	snapshot["turn"] = mainGame->dInfo.turn;
	snapshot["life_points"] = {mainGame->dInfo.lp[0], mainGame->dInfo.lp[1]};
	snapshot["disabled_field"] = mainGame->dField.disabled_field;
	snapshot["deck_reversed"] = mainGame->dField.deck_reversed;
	snapshot["graveyard_inspection_allowed"] = !mainGame->dField.cant_check_grave;
	snapshot["chain_depth"] = mainGame->dField.chains.size();
	snapshot["zones"] = nlohmann::json::array();
	for(int player = 0; player < 2; ++player) {
		const auto& field = mainGame->dField;
		AppendZone(snapshot["zones"], player, "deck", LOCATION_DECK, field.deck[player], true);
		AppendZone(snapshot["zones"], player, "hand", LOCATION_HAND, field.hand[player], player != 0);
		AppendZone(snapshot["zones"], player, "monster", LOCATION_MZONE, field.mzone[player], false);
		AppendZone(snapshot["zones"], player, "spell", LOCATION_SZONE, field.szone[player], false);
		AppendZone(snapshot["zones"], player, "graveyard", LOCATION_GRAVE, field.grave[player], field.cant_check_grave);
		AppendZone(snapshot["zones"], player, "banished", LOCATION_REMOVED, field.remove[player], false, player != 0);
		AppendZone(snapshot["zones"], player, "extra", LOCATION_EXTRA, field.extra[player], false, player != 0);
	}
	return snapshot;
}

void AgentController::OnGameMessage(const std::uint8_t* bytes, std::size_t length, bool already_answered) {
	std::string phase;
	int turn_player = -1;
	bool automatic_empty_chain = false;
	bool background_sync = false;
	bool card_hint_visible = false;
	const char* e2e_sync_type = std::getenv("YGOPRO_AGENT_E2E_SYNC_MESSAGE_TYPE");
	const bool e2e_sync_target = e2e_sync_type && bytes && length &&
		std::to_string(bytes[0]) == e2e_sync_type;
	if(bytes && length >= 10 && bytes[0] == MSG_CARD_HINT) {
		std::lock_guard<std::mutex> field_lock(mainGame->gMutex);
		const int player = mainGame->LocalPlayer(bytes[1]);
		const auto location = static_cast<std::uint8_t>(bytes[2] & 0x7f);
		const auto* card = mainGame->dField.GetCard(player, bytes[2], bytes[3]);
		card_hint_visible = card && PositionInspectable(player, location, !mainGame->dField.cant_check_grave)
			&& CardKnown(*card, player, location);
	}
	const auto visible_cards = CaptureVisibleCardValues();
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!initialized_ || (!available_ && !v3_) || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode)
			return;
		automatic_empty_chain = controlling_ && already_answered && bytes && length >= 3
			&& bytes[0] == MSG_SELECT_CHAIN && bytes[2] == 0;
		if(!automatic_empty_chain)
			RecordEvent(bytes, length, card_hint_visible);
		RecordVisibleValueChanges(visible_cards, bytes && length ? bytes[0] : 0);
		background_sync = (events_.size() >= max_pending_events / 2 || e2e_sync_target) &&
			!pending_ && !in_flight_prompt_id_ && history_complete_;
		phase = phase_;
		turn_player = turn_player_;
	}
	if(background_sync) SubmitBackgroundSync();
	if(const char* role = std::getenv("YGOPRO_AGENT_E2E_ROLE"); role && *role && bytes && length) {
		auto observation = BuildObservation();
		observation["phase"] = phase;
		observation["turn_player"] = turn_player < 0 ? 0 : turn_player;
		observation["test_role"] = role;
		Log({{"kind", "visible_snapshot"}, {"role", role}, {"message_type", bytes[0]},
			{"observation", std::move(observation)}, {"timestamp_unix_ms", NowUnixMs()}});
	}
	if(already_answered) {
		if(automatic_empty_chain)
			Log({{"kind", "automatic_pass"}, {"message_type", MSG_SELECT_CHAIN}, {"timestamp_unix_ms", NowUnixMs()}});
		return;
	}
	std::vector<std::uint32_t> allowed_card_ids;
	if(bytes && length && bytes[0] == MSG_ANNOUNCE_CARD) {
		std::lock_guard<std::mutex> lock(mainGame->gMutex);
		for(const auto id : mainGame->dField.ancard) {
			if(id > 0)
				allowed_card_ids.push_back(static_cast<std::uint32_t>(id));
		}
	}
	auto parsed = ParseDecision(bytes, length, DecisionSource::game_message,
		bytes && length && bytes[0] == MSG_ANNOUNCE_CARD ? &allowed_card_ids : nullptr,
		[](std::uint32_t description_id) {
			return BufferIO::EncodeUTF8String(std::wstring(dataManager.GetDesc(description_id)));
		});
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
		// The LAN duel-start notification precedes the opening choices. Bind
		// only the most recent actual submission to this duel, even if the
		// service is not yet available or control remains with the human.
		if(!duel_deck_manifest_ && submitted_deck_manifest_) {
			duel_deck_manifest_ = std::move(submitted_deck_manifest_);
			submitted_deck_manifest_.reset();
			deck_manifest_acknowledged_ = false;
		}
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
		cancel_previous = in_flight_prompt_id_ != 0 && !in_flight_ready_;
		if(duel_id_.empty()) {
			duel_id_ = NewId();
			next_event_id_ = 0;
			next_state_version_ = 0;
			acknowledged_event_id_ = 0;
			acknowledged_state_version_ = 0;
			history_complete_ = true;
			needs_status_ = false;
			events_.clear();
		}
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
	in_flight_ready_ = false;
	in_flight_query_result_ = false;
	in_flight_action_result_ = false;
	action_result_queued_ = false;
	completed_.clear();
	return started;
}

void AgentController::SubmitBackgroundSync() {
	nlohmann::json request;
	std::uint64_t event_id = 0;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_ || !history_complete_ || duel_id_.empty() || in_flight_prompt_id_ || events_.empty())
			return;
		request = {{"schema_version", v3_ ? 3 : 2}, {"session_id", session_id_},
				   {"duel_id", duel_id_},			{"database_sha256", database_sha256_},
				   {"history_complete", true},		{"events", nlohmann::json::array()}};
		for(const auto &event : events_) {
			request["events"].push_back(event);
			if(request.dump().size() > agent::HttpClient::max_json_size / 2) {
				request["events"].erase(request["events"].size() - 1);
				break;
			}
		}
		if(request["events"].empty()) {
			history_complete_ = false;
			return;
		}
		event_id = request["events"].back().at("event_id").get<std::uint64_t>();
		in_flight_prompt_id_ = std::numeric_limits<std::uint64_t>::max();
		in_flight_event_id_ = event_id;
		in_flight_state_version_ = 0;
		in_flight_sync_ = true;
		in_flight_status_ = false;
		in_flight_background_ = true;
		in_flight_terminal_ = false;
		in_flight_duel_id_ = duel_id_;
	}
	Log({{"kind", "state_sync_request"}, {"message", request}, {"timestamp_unix_ms", NowUnixMs()}});
	if(!http_.Submit(request.dump(), v3_ ? "/v3/sync" : "/v2/sync")) {
		std::lock_guard<std::mutex> lock(mutex_);
		if(in_flight_background_ && in_flight_event_id_ == event_id)
			in_flight_prompt_id_ = 0;
	}
}

void AgentController::SubmitTerminalSync() {
	nlohmann::json request;
	std::uint64_t event_id = 0;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_ || !terminal_ || !terminal_->history_complete || terminal_->attempts >= 3 ||
		   in_flight_prompt_id_)
			return;
		request = {{"schema_version", v3_ ? 3 : 2},
				   {"session_id", session_id_},
				   {"duel_id", terminal_->duel_id},
				   {"database_sha256", database_sha256_},
				   {"history_complete", terminal_->history_complete},
				   {"events", nlohmann::json::array()}};
		for(const auto &event : terminal_->events) {
			if(event.at("event_id").get<std::uint64_t>() <= terminal_->acknowledged_event_id)
				continue;
			request["events"].push_back(event);
			if(request.dump().size() > agent::HttpClient::max_json_size / 2) {
				request["events"].erase(request["events"].size() - 1);
				break;
			}
		}
		if(request["events"].empty())
			return;
		event_id = request["events"].back().at("event_id").get<std::uint64_t>();
		in_flight_prompt_id_ = std::numeric_limits<std::uint64_t>::max();
		in_flight_event_id_ = event_id;
		in_flight_state_version_ = 0;
		in_flight_sync_ = true;
		in_flight_status_ = false;
		in_flight_background_ = true;
		in_flight_terminal_ = true;
		in_flight_duel_id_ = terminal_->duel_id;
		++terminal_->attempts;
	}
	Log({{"kind", "terminal_sync_request"}, {"message", request}, {"timestamp_unix_ms", NowUnixMs()}});
	if(!http_.Submit(request.dump(), v3_ ? "/v3/sync" : "/v2/sync")) {
		std::lock_guard<std::mutex> lock(mutex_);
		if(in_flight_terminal_ && in_flight_event_id_ == event_id)
			in_flight_prompt_id_ = 0;
	}
}

void AgentController::SubmitPending() {
	if(v3_) {
		bool receipt_pending = false;
		{
			std::lock_guard<std::mutex> lock(mutex_);
			receipt_pending = action_receipt_.has_value();
		}
		if(receipt_pending) {
			SubmitActionResult();
			return;
		}
	}
	std::optional<nlohmann::json> status_request;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_ || !controlling_ || !pending_ || pending_->submitted || in_flight_prompt_id_)
			return;
		if(needs_status_) {
			status_request = nlohmann::json{{"schema_version", v3_ ? 3 : 2},
											{"session_id", session_id_},
											{"duel_id", duel_id_},
											{"database_sha256", database_sha256_}};
			in_flight_prompt_id_ = pending_->prompt_id;
			in_flight_state_version_ = 0;
			in_flight_event_id_ = 0;
			in_flight_sync_ = false;
			in_flight_status_ = true;
			in_flight_background_ = false;
			in_flight_terminal_ = false;
			in_flight_duel_id_ = duel_id_;
			pending_->submitted = true;
		}
	}
	if(status_request) {
		Log({{"kind", "state_status_request"}, {"message", *status_request}, {"timestamp_unix_ms", NowUnixMs()}});
		if(!http_.Submit(status_request->dump(), v3_ ? "/v3/status" : "/v2/status"))
			FailCurrent("transport_busy");
		return;
	}
	const auto snapshot = BuildObservation();
	nlohmann::json request;
	std::uint64_t prompt_id = 0;
	std::int64_t deadline_unix_ms = 0;
	std::string path = v3_ ? "/v3/decision" : "/v2/decision";
	std::string failure;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_ || !controlling_ || !pending_ || pending_->submitted || in_flight_prompt_id_)
			return;
		if(!history_complete_) {
			failure = "history_incomplete";
		} else if(v3_ && !duel_deck_manifest_) {
			failure = "deck_manifest_missing";
		} else {
			if(!pending_->frozen) {
				pending_->frozen_snapshot = snapshot;
				pending_->frozen_snapshot["turn_player"] = turn_player_ < 0 ? 0 : turn_player_;
				pending_->frozen_snapshot["phase"] = phase_;
				if(const char *role = std::getenv("YGOPRO_AGENT_E2E_ROLE"); role && *role)
					pending_->frozen_snapshot["test_role"] = role;
				pending_->frozen_events = events_;
				pending_->state_version = ++next_state_version_;
				pending_->frozen = true;
			}
			prompt_id = pending_->prompt_id;
			deadline_unix_ms = pending_->deadline_unix_ms;
			auto prompt = pending_->decision.prompt();
			for(auto &candidate : prompt["candidates"]) {
				if(candidate.contains("card") && candidate["card"].contains("controller")) {
					auto &card = candidate["card"];
					const int controller = mainGame->LocalPlayer(card["controller"].get<int>());
					card["controller"] = controller;
					if(card.contains("location") && card.contains("sequence") && card["location"].is_string()) {
						const auto location = card["location"].get<std::string>();
						std::uint32_t mask = 0;
						if(location == "hand")
							mask = LOCATION_HAND;
						else if(location == "monster")
							mask = LOCATION_MZONE;
						else if(location == "spell")
							mask = LOCATION_SZONE;
						else if(location == "graveyard")
							mask = LOCATION_GRAVE;
						else if(location == "banished")
							mask = LOCATION_REMOVED;
						else if(location == "extra")
							mask = LOCATION_EXTRA;
						if(mask)
							card["instance_id"] = std::to_string(controller) + ":" + std::to_string(mask) + ":" +
												  std::to_string(card["sequence"].get<std::size_t>());
						if(location == "graveyard" && mainGame->dField.cant_check_grave) {
							card["instance_id"] = "candidate-" + candidate["id"].get<std::string>();
							card.erase("sequence");
						}
					}
				}
				if(candidate.contains("controller"))
					candidate["controller"] = mainGame->LocalPlayer(candidate["controller"].get<int>());
			}
			request = {{"schema_version", v3_ ? 3 : 2},
					   {"session_id", session_id_},
					   {"duel_id", duel_id_},
					   {"prompt_id", prompt_id},
					   {"database_sha256", database_sha256_},
					   {"state_version", pending_->state_version},
					   {"history_complete", true},
					   {"deadline_unix_ms", pending_->deadline_unix_ms},
					   {"observation", pending_->frozen_snapshot},
					   {"prompt", std::move(prompt)}};
			request["observation"]["events"] = nlohmann::json::array();
			if(v3_ && !deck_manifest_acknowledged_)
				request["deck_manifest"] = *duel_deck_manifest_;
			for(const auto &event : pending_->frozen_events)
				if(event.at("event_id").get<std::uint64_t>() > acknowledged_event_id_)
					request["observation"]["events"].push_back(event);
			if(request.dump().size() > agent::HttpClient::max_json_size) {
				if(request["observation"]["events"].empty()) {
					failure = "snapshot_too_large";
				} else {
					path = v3_ ? "/v3/sync" : "/v2/sync";
					nlohmann::json sync{{"schema_version", v3_ ? 3 : 2}, {"session_id", session_id_},
										{"duel_id", duel_id_},			 {"database_sha256", database_sha256_},
										{"history_complete", true},		 {"events", nlohmann::json::array()}};
					for(const auto &event : request["observation"]["events"]) {
						sync["events"].push_back(event);
						if(sync.dump().size() > agent::HttpClient::max_json_size / 2) {
							sync["events"].erase(sync["events"].size() - 1);
							break;
						}
					}
					if(sync["events"].empty())
						failure = "event_too_large";
					else
						request = std::move(sync);
				}
			}
			if(failure.empty()) {
				in_flight_prompt_id_ = prompt_id;
				in_flight_state_version_ = pending_->state_version;
				in_flight_sync_ = path == "/v2/sync" || path == "/v3/sync";
				in_flight_status_ = false;
				in_flight_background_ = false;
				in_flight_terminal_ = false;
				in_flight_duel_id_ = duel_id_;
				const auto &outbound_events = in_flight_sync_ ? request["events"] : request["observation"]["events"];
				in_flight_event_id_ = outbound_events.empty()
										  ? acknowledged_event_id_
										  : outbound_events.back().at("event_id").get<std::uint64_t>();
				pending_->submitted = true;
			}
		}
	}
	if(!failure.empty()) {
		FailCurrent(failure);
		return;
	}
	Log({{"kind", path == "/v2/sync" || path == "/v3/sync" ? "state_sync_request" : "decision_request"},
		 {"message", request},
		 {"timestamp_unix_ms", NowUnixMs()}});
	const int remaining_ms = static_cast<int>(std::max<std::int64_t>(1, deadline_unix_ms - NowUnixMs()));
	if(!http_.Submit(request.dump(), path, remaining_ms)) {
		FailCurrent("transport_busy");
		return;
	}
}

void AgentController::SubmitActionResult() {
	nlohmann::json request;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!v3_ || !available_ || !action_receipt_ || in_flight_prompt_id_ || action_result_queued_)
			return;
		if(action_receipt_->attempts >= 3) {
			controlling_ = false;
			notices_.push_back("Agent 已交还人工操作：action_result_failed");
			return;
		}
		request = {{"schema_version", 3},
				   {"session_id", session_id_},
				   {"duel_id", action_receipt_->duel_id},
				   {"prompt_id", action_receipt_->prompt_id},
				   {"state_version", action_receipt_->state_version},
				   {"action_id", action_receipt_->action_id},
				   {"status", action_receipt_->status}};
		in_flight_prompt_id_ = action_receipt_->prompt_id;
		in_flight_state_version_ = action_receipt_->state_version;
		in_flight_event_id_ = acknowledged_event_id_;
		in_flight_sync_ = false;
		in_flight_status_ = false;
		in_flight_background_ = false;
		in_flight_terminal_ = false;
		in_flight_action_result_ = true;
		in_flight_duel_id_ = action_receipt_->duel_id;
		++action_receipt_->attempts;
	}
	Log({{"kind", "action_result_request"}, {"message", request}, {"timestamp_unix_ms", NowUnixMs()}});
	if(!http_.Submit(request.dump(), "/v3/action-result", 3000)) {
		std::lock_guard<std::mutex> lock(mutex_);
		in_flight_prompt_id_ = 0;
		in_flight_action_result_ = false;
	}
}

void AgentController::HandleQuery(const nlohmann::json &reply, std::uint64_t prompt_id, std::uint64_t state_version) {
	std::string duel_id;
	nlohmann::json frozen;
	std::int64_t deadline = 0;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!controlling_ || !pending_ || pending_->prompt_id != prompt_id || pending_->state_version != state_version ||
		   !pending_->frozen)
			return;
		duel_id = duel_id_;
		frozen = pending_->frozen_snapshot;
		deadline = pending_->deadline_unix_ms;
	}
	const std::string query_id = reply.value("query_id", std::string{});
	if(query_id.empty() || query_id.size() > 128 || !reply.contains("query") || !reply["query"].is_object()) {
		FailCurrent("invalid_query_response");
		return;
	}
	nlohmann::json request{{"schema_version", 3},	 {"session_id", session_id_},	   {"duel_id", duel_id},
						   {"prompt_id", prompt_id}, {"state_version", state_version}, {"query_id", query_id}};
	std::string error;
	if(NowUnixMs() >= deadline)
		error = "stale_prompt";
	nlohmann::json current;
	if(error.empty()) {
		current = BuildObservation();
		frozen.erase("phase");
		frozen.erase("turn_player");
		frozen.erase("test_role");
		if(current != frozen)
			error = "stale_prompt";
	}
	if(error.empty()) {
		const auto &query = reply["query"];
		const auto kind = query.value("kind", std::string{});
		if(kind == "inspect_zone") {
			if(!query.contains("player") || !query["player"].is_number_integer() || !query.contains("zone") ||
			   !query["zone"].is_string()) {
				error = "unavailable";
			} else {
				const int player = query["player"].get<int>();
				const std::string zone = query["zone"].get<std::string>();
				if(player < 0 || player > 1)
					error = "unavailable";
				else {
					bool found = false;
					for(const auto &entry : current["zones"]) {
						if(entry.value("player", -1) == player && entry.value("name", std::string{}) == zone) {
							request["result"] = {{"kind", "inspect_zone"}, {"zone", entry}};
							found = true;
							break;
						}
					}
					if(!found)
						error = "unavailable";
				}
			}
		} else if(kind == "inspect_card") {
			if(!query.contains("instance_id") || !query["instance_id"].is_string()) {
				error = "unavailable";
			} else {
				const auto instance_id = query["instance_id"].get<std::string>();
				bool found = false;
				for(const auto &zone : current["zones"]) {
					for(const auto &card : zone["cards"]) {
						if(card.value("instance_id", std::string{}) == instance_id) {
							request["result"] = {{"kind", "inspect_card"}, {"card", card}};
							found = true;
							break;
						}
					}
					if(found)
						break;
				}
				if(!found)
					error = "not_visible";
			}
		} else
			error = "unavailable";
	}
	if(!error.empty())
		request["error"] = {{"code", error}, {"message", error}};
	const int remaining_ms = static_cast<int>(std::max<std::int64_t>(1, deadline - NowUnixMs()));
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!controlling_ || !pending_ || pending_->prompt_id != prompt_id || pending_->state_version != state_version)
			return;
		in_flight_prompt_id_ = prompt_id;
		in_flight_state_version_ = state_version;
		in_flight_event_id_ = acknowledged_event_id_;
		in_flight_sync_ = false;
		in_flight_status_ = false;
		in_flight_background_ = false;
		in_flight_terminal_ = false;
		in_flight_query_result_ = true;
		in_flight_duel_id_ = duel_id;
	}
	Log({{"kind", "client_query_result"}, {"message", request}, {"timestamp_unix_ms", NowUnixMs()}});
	if(!http_.Submit(request.dump(), "/v3/query-result", remaining_ms)) {
		FailCurrent("query_result_transport_busy");
		return;
	}
	if(!error.empty())
		FailCurrent(error);
}

void AgentController::OnHttpResult(agent::HttpResult result) {
	std::lock_guard<std::mutex> lock(mutex_);
	if(in_flight_action_result_)
		action_result_queued_ = true;
	completed_.push_back(Completed{in_flight_prompt_id_, in_flight_state_version_, in_flight_event_id_, in_flight_sync_,
								   in_flight_status_, in_flight_background_, in_flight_terminal_, in_flight_ready_,
								   in_flight_query_result_, in_flight_action_result_, in_flight_duel_id_,
								   std::move(result)});
	in_flight_prompt_id_ = 0;
	in_flight_ready_ = false;
	in_flight_query_result_ = false;
	in_flight_action_result_ = false;
}

void AgentController::FailCurrent(const std::string &code) {
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
	bool restart_service = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		restart_service = v3_ && !available_;
	}
	if(restart_service) {
		http_.Stop();
		process_.Stop();
		boot_nonce_ = NewId();
		token_ = NewId() + NewId();
		if(!StartService()) {
			ShowAgentMessage("Agent 服务重启失败，请检查 .agents 配置和端口");
			return;
		}
		{
			std::lock_guard<std::mutex> lock(mutex_);
			needs_status_ = !duel_id_.empty();
		}
		ShowAgentMessage("Agent 服务正在启动，准备恢复接管");
		return;
	}
	bool next = false;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!available_ || (v3_ && !ready_)) {
			ShowAgentMessage("Agent 未就绪，请检查连接和卡片数据库配置");
			return;
		}
		controlling_ = !controlling_;
		next = controlling_;
		if(next && !duel_id_.empty())
			needs_status_ = true;
		if(!duel_id_.empty()) {
			if(events_.size() >= max_pending_events)
				history_complete_ = false;
			else
				events_.push_back({{"event_id", ++next_event_id_},
								   {"kind", "control_changed"},
								   {"source", "client_control"},
								   {"agent", next}});
		}
		if(pending_) {
			pending_->prompt_id = ++next_prompt_id_;
			pending_->submitted = false;
			pending_->state_version = 0;
			pending_->frozen = false;
			pending_->frozen_events.clear();
			pending_->frozen_snapshot = nullptr;
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
	if(v3_ && !process_.Running()) {
		bool was_available = false;
		{
			std::lock_guard<std::mutex> lock(mutex_);
			was_available = available_;
			available_ = false;
			ready_ = false;
			pending_.reset();
		}
		if(was_available) {
			FailCurrent("agent_process_exited");
			http_.Stop();
		}
	}
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
	for(const auto &notice : notices)
		ShowAgentMessage(notice);
	for(auto &item : completed) {
		if(item.ready) {
			bool valid = item.result.status == 200 && item.result.error.empty();
			if(valid) {
				try {
					const auto reply = nlohmann::json::parse(item.result.body);
					valid = reply.is_object() && reply.value("schema_version", 0) == 3 &&
							reply.value("nonce", std::string{}) == boot_nonce_ &&
							reply.value("profile", std::string{}) == profile_ && reply.value("port", 0) == port_ &&
							reply.value("decision_timeout_ms", 0) == timeout_ms_;
				} catch(const nlohmann::json::exception &) {
					valid = false;
				}
			}
			if(!valid) {
				FailCurrent("agent_ready_mismatch");
				{
					std::lock_guard<std::mutex> lock(mutex_);
					available_ = false;
				}
				http_.Stop();
				process_.Stop();
				continue;
			}
			{
				std::lock_guard<std::mutex> lock(mutex_);
				ready_ = true;
				controlling_ = true;
			}
			SubmitPending();
			continue;
		}
		if(item.action_result) {
			if(item.result.status != 200 || !item.result.error.empty()) {
				{
					std::lock_guard<std::mutex> lock(mutex_);
					action_result_queued_ = false;
				}
				Log({{"kind", "action_result_error"},
					 {"error", item.result.error},
					 {"timestamp_unix_ms", NowUnixMs()}});
				SubmitActionResult();
				continue;
			}
			{
				std::lock_guard<std::mutex> lock(mutex_);
				action_result_queued_ = false;
				if(action_receipt_ && action_receipt_->duel_id == item.duel_id &&
				   action_receipt_->prompt_id == item.prompt_id)
					action_receipt_.reset();
			}
			SubmitPending();
			continue;
		}
		if(item.background) {
			if(item.result.status != 200 || !item.result.error.empty()) {
				Log({{"kind", "state_sync_error"},
					 {"duel_id", item.duel_id},
					 {"error", item.result.error},
					 {"timestamp_unix_ms", NowUnixMs()}});
				continue;
			}
			try {
				const auto reply = nlohmann::json::parse(item.result.body);
				if(!reply.is_object() || reply.value("schema_version", 0) != (v3_ ? 3 : 2) ||
				   reply.value("session_id", std::string{}) != session_id_ ||
				   reply.value("duel_id", std::string{}) != item.duel_id || !reply.contains("ack_event_id") ||
				   !reply["ack_event_id"].is_number_unsigned() ||
				   reply["ack_event_id"].get<std::uint64_t>() != item.event_id)
					throw std::runtime_error("invalid sync acknowledgment");
				std::lock_guard<std::mutex> lock(mutex_);
				if(item.terminal) {
					if(terminal_ && terminal_->duel_id == item.duel_id) {
						terminal_->acknowledged_event_id = item.event_id;
						terminal_->attempts = 0;
						if(!terminal_->events.empty() &&
						   terminal_->events.back().at("event_id").get<std::uint64_t>() <= item.event_id)
							terminal_.reset();
					}
				} else if(duel_id_ == item.duel_id) {
					acknowledged_event_id_ = item.event_id;
					events_.erase(std::remove_if(events_.begin(), events_.end(),
												 [this](const auto &event) {
													 return event.at("event_id").template get<std::uint64_t>() <=
															acknowledged_event_id_;
												 }),
								  events_.end());
				}
			} catch(const std::exception &error) {
				std::lock_guard<std::mutex> lock(mutex_);
				if(!item.terminal)
					history_complete_ = false;
				Log({{"kind", "state_sync_error"},
					 {"duel_id", item.duel_id},
					 {"error", error.what()},
					 {"timestamp_unix_ms", NowUnixMs()}});
			}
			continue;
		}
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
			FailCurrent(ResponseFailureCode(item.result));
			continue;
		}
		try {
			const auto reply = nlohmann::json::parse(item.result.body);
			if(item.status) {
				if(!reply.is_object() || reply.value("schema_version", 0) != (v3_ ? 3 : 2) ||
				   reply.value("session_id", std::string{}) != session_id ||
				   reply.value("duel_id", std::string{}) != duel_id || !reply.contains("ack_event_id") ||
				   !reply["ack_event_id"].is_number_unsigned() || !reply.contains("state_version") ||
				   !reply["state_version"].is_number_unsigned()) {
					FailCurrent("invalid_status_response");
					continue;
				}
				const auto ack = reply["ack_event_id"].get<std::uint64_t>();
				const auto version = reply["state_version"].get<std::uint64_t>();
				bool conflict = false;
				{
					std::lock_guard<std::mutex> lock(mutex_);
					conflict = ack < acknowledged_event_id_ || ack > next_event_id_ ||
							   version < acknowledged_state_version_ || version > next_state_version_;
					if(!conflict) {
						acknowledged_event_id_ = ack;
						acknowledged_state_version_ = version;
						next_state_version_ = version;
						events_.erase(std::remove_if(events_.begin(), events_.end(),
													 [this](const auto &event) {
														 return event.at("event_id").template get<std::uint64_t>() <=
																acknowledged_event_id_;
													 }),
									  events_.end());
						needs_status_ = false;
						if(pending_ && pending_->prompt_id == item.prompt_id) {
							pending_->submitted = false;
							pending_->frozen = false;
							pending_->frozen_events.clear();
							pending_->frozen_snapshot = nullptr;
						}
					}
				}
				if(conflict) {
					FailCurrent("state_status_conflict");
					continue;
				}
				SubmitPending();
				continue;
			}
			if(!reply.is_object() || reply.value("schema_version", 0) != (v3_ ? 3 : 2) ||
			   reply.value("session_id", std::string{}) != session_id ||
			   reply.value("duel_id", std::string{}) != duel_id || !reply.contains("ack_event_id") ||
			   !reply["ack_event_id"].is_number_unsigned() ||
			   reply["ack_event_id"].get<std::uint64_t>() != item.event_id) {
				FailCurrent("invalid_response_envelope");
				continue;
			}
			if(!item.sync && (reply.value("prompt_id", std::uint64_t{0}) != item.prompt_id ||
							  reply.value("state_version", std::uint64_t{0}) != item.state_version ||
							  (v3_ ? !reply.contains("kind") : !reply.contains("action")))) {
				FailCurrent("invalid_response_envelope");
				continue;
			}
			{
				std::lock_guard<std::mutex> lock(mutex_);
				acknowledged_event_id_ = item.event_id;
				events_.erase(std::remove_if(events_.begin(), events_.end(),
											 [this](const auto &event) {
												 return event.at("event_id").template get<std::uint64_t>() <=
														acknowledged_event_id_;
											 }),
							  events_.end());
			}
			if(item.sync) {
				{
					std::lock_guard<std::mutex> lock(mutex_);
					if(pending_ && pending_->prompt_id == item.prompt_id)
						pending_->submitted = false;
				}
				SubmitPending();
				continue;
			}
			{
				std::lock_guard<std::mutex> lock(mutex_);
				acknowledged_state_version_ = item.state_version;
				if(v3_)
					deck_manifest_acknowledged_ = true;
			}
			if(v3_ && reply.value("kind", std::string{}) == "query") {
				HandleQuery(reply, item.prompt_id, item.state_version);
				continue;
			}
			if(v3_ && (reply.value("kind", std::string{}) != "action" || !reply.contains("action_id") ||
					   !reply["action_id"].is_string() || reply["action_id"].get<std::string>().empty() ||
					   reply["action_id"].get<std::string>().size() > 128 || !reply.contains("action"))) {
				FailCurrent("invalid_action_response");
				continue;
			}
			auto action = reply.at("action");
			if(action.is_object() && action.value("kind", std::string{}) == "select_places" &&
			   action.contains("places") && action["places"].is_array()) {
				for(auto &place : action["places"])
					if(place.is_object() && place.contains("controller") && place["controller"].is_number_integer())
						place["controller"] = mainGame->LocalPlayer(place["controller"].get<int>());
			}
			const auto encoded = EncodeDecision(*decision, action);
			if(!encoded.response) {
				if(v3_) {
					{
						std::lock_guard<std::mutex> lock(mutex_);
						action_receipt_ = ActionReceipt{duel_id, item.prompt_id, item.state_version,
														reply["action_id"].get<std::string>(), "rejected"};
					}
					SubmitActionResult();
				}
				FailCurrent(encoded.error.code);
				continue;
			}
			bool stale = false;
			{
				std::lock_guard<std::mutex> lock(mutex_);
				stale = !controlling_ || !pending_ || pending_->prompt_id != item.prompt_id ||
						pending_->state_version != item.state_version || NowUnixMs() >= pending_->deadline_unix_ms;
				if(!stale)
					pending_.reset();
			}
			if(stale) {
				if(v3_) {
					{
						std::lock_guard<std::mutex> lock(mutex_);
						action_receipt_ = ActionReceipt{duel_id, item.prompt_id, item.state_version,
														reply["action_id"].get<std::string>(), "stale_prompt"};
					}
					SubmitActionResult();
				}
				continue;
			}
			const auto &response = *encoded.response;
			DismissPromptWindows();
			if(response.packet_type == CTOS_RESPONSE) {
				DuelClient::SetResponseB(const_cast<std::uint8_t *>(response.payload.data()), response.payload.size());
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
			if(v3_) {
				{
					std::lock_guard<std::mutex> lock(mutex_);
					action_receipt_ = ActionReceipt{duel_id, item.prompt_id, item.state_version,
													reply["action_id"].get<std::string>(), "submitted"};
				}
				SubmitActionResult();
			}
			Log({{"kind", "decision_submitted"},
				 {"prompt_id", item.prompt_id},
				 {"reason", reply.value("reason", std::string{})},
				 {"timestamp_unix_ms", NowUnixMs()}});
			if(reply.contains("reason") && reply["reason"].is_string())
				ShowAgentMessage("Agent：" + reply["reason"].get<std::string>());
		} catch(const nlohmann::json::exception &) {
			FailCurrent("invalid_json_response");
		}
	}
	SubmitTerminalSync();
}

} // namespace ygo::agent_client
