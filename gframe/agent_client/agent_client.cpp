#include "agent_client.h"
#include "agent_protocol.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <mutex>
#include <optional>
#include <random>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <event2/buffer.h>
#include <event2/bufferevent.h>
#include <event2/event.h>
#include <event2/util.h>
#include <nlohmann/json.hpp>

#include "../client_card.h"
#include "../data_manager.h"
#include "../duelclient.h"
#include "../game.h"
#include "../network.h"

namespace ygo {
namespace {
using json = nlohmann::json;
namespace protocol = agent_protocol;

inline constexpr int forced_effect_candidate_flag{1 << 8};

bool IsDecision(short msg) {
	switch(msg) {
	case MSG_SELECT_BATTLECMD: case MSG_SELECT_IDLECMD: case MSG_SELECT_EFFECTYN:
	case MSG_SELECT_YESNO: case MSG_SELECT_OPTION: case MSG_SELECT_CARD:
	case MSG_SELECT_UNSELECT_CARD: case MSG_SELECT_CHAIN: case MSG_SELECT_PLACE:
	case MSG_SELECT_DISFIELD: case MSG_SELECT_POSITION: case MSG_SELECT_TRIBUTE:
	case MSG_SELECT_COUNTER: case MSG_SELECT_SUM: case MSG_SORT_CARD:
	case MSG_ANNOUNCE_RACE: case MSG_ANNOUNCE_ATTRIB: case MSG_ANNOUNCE_CARD:
	case MSG_ANNOUNCE_NUMBER: case MSG_ROCK_PAPER_SCISSORS:
		return true;
	default: return false;
	}
}

struct Pending {
	uint64_t id{};
	short msg{};
	std::unordered_set<int> integers;
	std::unordered_map<uint32_t, int> choice_responses;
	std::vector<int> card_sequences;
	int min_cards{};
	int max_cards{};
	bool cancel{};
	std::chrono::steady_clock::time_point deadline;
};

struct PreDuelPending {
	uint64_t id{};
	protocol::Decision decision{protocol::Decision::unknown};
};

struct SubmissionChoice {
	uint32_t id{};
	protocol::Action action{protocol::Action::unknown};
};

struct SubmissionContext {
	uint64_t id{};
	short msg{};
	protocol::Decision decision{protocol::Decision::unknown};
	std::unordered_map<int, SubmissionChoice> choices;
	std::vector<int> card_sequences;
	json card_choices{json::array()};
};

std::string GenerateIdentifier() {
	static std::random_device random_device;
	static std::mt19937_64 random_engine{random_device()};
	std::ostringstream stream;
	stream << std::hex << random_engine() << random_engine();
	return stream.str();
}

struct State {
	std::mutex mutex;
	bool enabled{};
	bool running{};
	bool connected{};
	bool hello_sent{};
	bool handshaken{};
	bool force_snapshot{true};
	bool controlling{};
	bool awaiting_duel_start{};
	std::string host{"127.0.0.1"};
	uint16_t port{7450};
	int timeout_ms{15000};
	std::string log_path{"agent-log.jsonl"};
	std::atomic_uint64_t next_event_id{};
	uint64_t next_request_id{};
	uint64_t state_revision{};
	std::string session_id{GenerateIdentifier()};
	std::string duel_id;
	std::deque<std::string> outgoing;
	std::deque<json> incoming;
	std::string input;
	json last_state;
	uint32_t last_selection_hint{};
	Pending pending;
	PreDuelPending pre_duel_pending;
	SubmissionContext submission;
	int turn_player{-1};
	protocol::Phase phase{protocol::Phase::unknown};
	uint64_t next_attack_id{};
	uint64_t active_attack_id{};
	std::thread worker;
	event_base* base{};
	bufferevent* bev{};
};
State state;
std::mutex log_mutex;

void DiscardStaleIncomingLocked() {
	for(auto iterator = state.incoming.begin(); iterator != state.incoming.end();) {
		const auto type = iterator->value("type", "");
		if(type == agent_protocol::ToString(agent_protocol::MessageType::hello_ack)
			|| iterator->value("duel_id", "") == state.duel_id) {
			++iterator;
		} else {
			iterator = state.incoming.erase(iterator);
		}
	}
}

uint64_t NextEventId() noexcept {
	return state.next_event_id.fetch_add(1, std::memory_order_relaxed) + 1;
}

uint64_t UnixMilliseconds() noexcept {
	const auto now = std::chrono::system_clock::now().time_since_epoch();
	return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(now).count());
}

protocol::Zone ZoneFromLocation(uint32_t location, uint32_t sequence = 0) noexcept {
	switch(location & 0x7f) {
	case LOCATION_HAND: return protocol::Zone::hand;
	case LOCATION_MZONE: return sequence >= 5 ? protocol::Zone::extra_monster : protocol::Zone::main_monster;
	case LOCATION_SZONE: return protocol::Zone::spell_trap;
	case LOCATION_GRAVE: return protocol::Zone::graveyard;
	case LOCATION_REMOVED: return protocol::Zone::banished;
	case LOCATION_EXTRA: return protocol::Zone::extra;
	case LOCATION_DECK: return protocol::Zone::deck;
	default: return protocol::Zone::unknown;
	}
}

std::string DescriptionText(uint32_t description) {
	if(description == 0) return {};
	return BufferIO::EncodeUTF8String(dataManager.GetDesc(description));
}

json Description(uint32_t description) {
	json result = {{"description_id", description}};
	const auto text = DescriptionText(description);
	if(!text.empty()) result["description_text"] = text;
	return result;
}

json EffectDescriptor(uint32_t code, uint32_t description) {
	auto result = Description(description);
	result["description_offset"] = nullptr;
	const uint64_t base = static_cast<uint64_t>(code) * 16;
	if(code != 0 && description >= base && description < base + 16)
		result["description_offset"] = static_cast<uint32_t>(description - base);
	return result;
}

protocol::Position PositionFromEngine(uint32_t location, uint32_t position) noexcept {
	const auto base_location = location & 0x7f;
	if(base_location == LOCATION_HAND || base_location == LOCATION_DECK)
		return protocol::Position::hidden;
	if(base_location == LOCATION_EXTRA)
		return (position & POS_FACEUP) != 0 ? protocol::Position::face_up : protocol::Position::hidden;
	if(base_location == LOCATION_SZONE)
		return (position & POS_FACEDOWN) != 0 ? protocol::Position::face_down : protocol::Position::face_up;
	if((position & POS_FACEUP_ATTACK) != 0) return protocol::Position::face_up_attack;
	if((position & POS_FACEDOWN_ATTACK) != 0) return protocol::Position::face_down_attack;
	if((position & POS_FACEUP_DEFENSE) != 0) return protocol::Position::face_up_defense;
	if((position & POS_FACEDOWN_DEFENSE) != 0) return protocol::Position::face_down_defense;
	return protocol::Position::unknown;
}

json ZoneCoordinates(protocol::Zone zone, uint32_t engine_sequence) {
	const uint32_t slot_index = zone == protocol::Zone::extra_monster ? engine_sequence - 5 : engine_sequence;
	json result = {{"slot_index", slot_index}, {"slot_number", slot_index + 1}};
	if(zone == protocol::Zone::extra_monster) result["engine_sequence"] = engine_sequence;
	return result;
}

json Location(int player, uint32_t location, uint32_t sequence, uint32_t position) {
	const auto zone = ZoneFromLocation(location, sequence);
	json result = {{"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		{"zone", protocol::ToString(zone)},
		{"position", protocol::ToString(PositionFromEngine(location, position))}};
	result.update(ZoneCoordinates(zone, sequence));
	return result;
}

json ObservedCard(const AgentObservedCard& observation) {
	auto location = Location(observation.player, observation.location, observation.sequence, observation.position);
	if((observation.location & LOCATION_OVERLAY) != 0) location["overlay_sequence"] = observation.sub_sequence;
	return {{"card", observation.code == 0 ? json{{"known", false}} : json{{"known", true}, {"id", observation.code}}},
		{"location", std::move(location)}};
}

protocol::HintType HintTypeFromEngine(uint8_t value) noexcept {
	switch(value) {
	case HINT_EVENT: return protocol::HintType::event; case HINT_MESSAGE: return protocol::HintType::message;
	case HINT_SELECTMSG: return protocol::HintType::select_message; case HINT_OPSELECTED: return protocol::HintType::option_selected;
	case HINT_EFFECT: return protocol::HintType::effect; case HINT_RACE: return protocol::HintType::race;
	case HINT_ATTRIB: return protocol::HintType::attribute; case HINT_CODE: return protocol::HintType::code;
	case HINT_NUMBER: return protocol::HintType::number; case HINT_CARD: return protocol::HintType::card;
	case HINT_ZONE: return protocol::HintType::zone; default: return protocol::HintType::unknown;
	}
}

protocol::Phase PhaseFromEngine(uint16_t value) noexcept {
	switch(value) {
	case PHASE_DRAW: return protocol::Phase::draw;
	case PHASE_STANDBY: return protocol::Phase::standby;
	case PHASE_MAIN1: return protocol::Phase::main_1;
	case PHASE_BATTLE_START: return protocol::Phase::battle_start;
	case PHASE_BATTLE_STEP: return protocol::Phase::battle_step;
	case PHASE_DAMAGE: return protocol::Phase::damage;
	case PHASE_DAMAGE_CAL: return protocol::Phase::damage_calculation;
	case PHASE_BATTLE: return protocol::Phase::battle;
	case PHASE_MAIN2: return protocol::Phase::main_2;
	case PHASE_END: return protocol::Phase::end;
	default: return protocol::Phase::unknown;
	}
}

json MoveReasons(uint32_t flags) {
	using ReasonEntry = std::pair<uint32_t, protocol::MoveReason>;
	static constexpr std::array reasons{
		ReasonEntry{REASON_DESTROY, protocol::MoveReason::destroy}, ReasonEntry{REASON_RELEASE, protocol::MoveReason::release},
		ReasonEntry{REASON_TEMPORARY, protocol::MoveReason::temporary}, ReasonEntry{REASON_MATERIAL, protocol::MoveReason::material},
		ReasonEntry{REASON_SUMMON, protocol::MoveReason::summon}, ReasonEntry{REASON_BATTLE, protocol::MoveReason::battle},
		ReasonEntry{REASON_EFFECT, protocol::MoveReason::effect}, ReasonEntry{REASON_COST, protocol::MoveReason::cost},
		ReasonEntry{REASON_ADJUST, protocol::MoveReason::adjust}, ReasonEntry{REASON_LOST_TARGET, protocol::MoveReason::lost_target},
		ReasonEntry{REASON_RULE, protocol::MoveReason::rule}, ReasonEntry{REASON_SPSUMMON, protocol::MoveReason::special_summon},
		ReasonEntry{REASON_DISSUMMON, protocol::MoveReason::disabled_summon}, ReasonEntry{REASON_FLIP, protocol::MoveReason::flip},
		ReasonEntry{REASON_DISCARD, protocol::MoveReason::discard}, ReasonEntry{REASON_RDAMAGE, protocol::MoveReason::reverse_damage},
		ReasonEntry{REASON_RRECOVER, protocol::MoveReason::reverse_recover}, ReasonEntry{REASON_RETURN, protocol::MoveReason::return_to_deck},
		ReasonEntry{REASON_FUSION, protocol::MoveReason::fusion}, ReasonEntry{REASON_SYNCHRO, protocol::MoveReason::synchro},
		ReasonEntry{REASON_RITUAL, protocol::MoveReason::ritual}, ReasonEntry{REASON_XYZ, protocol::MoveReason::xyz},
		ReasonEntry{REASON_REPLACE, protocol::MoveReason::replace}, ReasonEntry{REASON_DRAW, protocol::MoveReason::draw},
		ReasonEntry{REASON_REDIRECT, protocol::MoveReason::redirect}, ReasonEntry{REASON_REVEAL, protocol::MoveReason::reveal},
		ReasonEntry{REASON_LINK, protocol::MoveReason::link}, ReasonEntry{REASON_LOST_OVERLAY, protocol::MoveReason::lost_overlay},
		ReasonEntry{REASON_MAINTENANCE, protocol::MoveReason::maintenance}, ReasonEntry{REASON_ACTION, protocol::MoveReason::action}
	};
	json result = json::array();
	for(const auto& [mask, reason] : reasons)
		if((flags & mask) != 0) result.push_back(protocol::ToString(reason));
	return result;
}

void Log(const json& value) {
	std::lock_guard<std::mutex> lock(log_mutex);
	if(FILE* fp = std::fopen(state.log_path.c_str(), "ab")) {
		auto record = value;
		if(!record.contains("timestamp_unix_ms")) {
			const auto message = record.find("message");
			if(message != record.end() && message->is_object() && message->contains("timestamp_unix_ms"))
				record["timestamp_unix_ms"] = (*message)["timestamp_unix_ms"];
			else
				record["timestamp_unix_ms"] = UnixMilliseconds();
		}
		auto line = record.dump();
		std::fwrite(line.data(), 1, line.size(), fp);
		std::fwrite("\n", 1, 1, fp);
		std::fclose(fp);
	}
}

void LogDuelEvent(protocol::Event event, json payload) {
	std::lock_guard<std::mutex> lock(state.mutex);
	if(!state.enabled || state.duel_id.empty() || !mainGame
		|| mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode)
		return;
	payload["type"] = protocol::ToString(protocol::MessageType::duel_event);
	payload["protocol_version"] = protocol::protocol_version;
	payload["session_id"] = state.session_id;
	payload["duel_id"] = state.duel_id;
	payload["event_id"] = NextEventId();
	payload["timestamp_unix_ms"] = UnixMilliseconds();
	payload["event"] = protocol::ToString(event);
	const bool can_dispatch = state.connected && state.handshaken;
	const bool can_queue = state.running && state.outgoing.size() < 4096;
	const auto direction = can_queue
		? (can_dispatch ? protocol::Direction::outbound : protocol::Direction::queued)
		: protocol::Direction::local;
	Log({{"event_id", payload["event_id"]},
		{"direction", protocol::ToString(direction)},
		{"message", payload}});
	if(!can_queue) return;
	const auto body = payload.dump();
	if(body.size() > 1024 * 1024) return;
	std::string frame(4, '\0');
	uint32_t size = htonl(static_cast<uint32_t>(body.size()));
	std::memcpy(frame.data(), &size, sizeof size);
	frame += body;
	state.outgoing.emplace_back(std::move(frame));
}

void Queue(json value) {
	const auto body = value.dump();
	if(body.size() > 1024 * 1024) return;
	std::string frame(4, '\0');
	uint32_t n = htonl(static_cast<uint32_t>(body.size()));
	std::memcpy(frame.data(), &n, sizeof n);
	frame += body;
	std::lock_guard<std::mutex> lock(state.mutex);
	state.outgoing.emplace_back(std::move(frame));
}

void ReadCallback(bufferevent* bev, void*) {
	auto* input = bufferevent_get_input(bev);
	char temp[4096];
	while(evbuffer_get_length(input)) {
		int count = evbuffer_remove(input, temp, sizeof temp);
		if(count <= 0) break;
		std::lock_guard<std::mutex> lock(state.mutex);
		state.input.append(temp, static_cast<size_t>(count));
		while(state.input.size() >= 4) {
			uint32_t size{};
			std::memcpy(&size, state.input.data(), 4);
			size = ntohl(size);
			if(size > 1024 * 1024) { state.input.clear(); state.connected = false; break; }
			if(state.input.size() < size + 4) break;
			try { state.incoming.push_back(json::parse(state.input.substr(4, size))); } catch(...) {}
			state.input.erase(0, size + 4);
		}
	}
}
void EventCallback(bufferevent*, short events, void*) {
	std::lock_guard<std::mutex> lock(state.mutex);
	if(events & BEV_EVENT_CONNECTED) state.connected = true;
	if(events & (BEV_EVENT_EOF | BEV_EVENT_ERROR)) { state.connected = false; state.hello_sent = false; state.handshaken = false; }
}
void Worker() {
	state.base = event_base_new();
	if(!state.base) return;
	state.bev = bufferevent_socket_new(state.base, -1, BEV_OPT_CLOSE_ON_FREE);
	bufferevent_setcb(state.bev, ReadCallback, nullptr, EventCallback, nullptr);
	bufferevent_enable(state.bev, EV_READ | EV_WRITE);
	if(bufferevent_socket_connect_hostname(state.bev, nullptr, AF_UNSPEC, state.host.c_str(), state.port) < 0) {
		std::lock_guard<std::mutex> lock(state.mutex); state.connected = false;
	}
	while(true) {
		{
			std::lock_guard<std::mutex> lock(state.mutex);
			if(!state.running) break;
			if(state.connected) {
				if(!state.hello_sent) {
					json hello = {{"type", protocol::ToString(protocol::MessageType::hello)}, {"protocol_version", protocol::protocol_version}, {"session_id", state.session_id}, {"duel_id", state.duel_id}, {"language", "zh-CN"}, {"client", "ygopro"}};
					const auto body = hello.dump(); uint32_t n = htonl(static_cast<uint32_t>(body.size()));
					bufferevent_write(state.bev, &n, 4); bufferevent_write(state.bev, body.data(), body.size()); state.hello_sent = true;
				}
				if(state.handshaken)
					while(!state.outgoing.empty()) { bufferevent_write(state.bev, state.outgoing.front().data(), state.outgoing.front().size()); state.outgoing.pop_front(); }
			}
		}
		event_base_loop(state.base, EVLOOP_NONBLOCK);
		std::this_thread::sleep_for(std::chrono::milliseconds(10));
	}
	bufferevent_free(state.bev); state.bev = nullptr; event_base_free(state.base); state.base = nullptr;
}

json Card(ClientCard* card, bool known) {
	const auto card_zone = ZoneFromLocation(card->location, card->sequence);
	const uint32_t engine_sequence = card->sequence;
	json result = {{"zone", protocol::ToString(card_zone)},
		{"position", protocol::ToString(PositionFromEngine(card->location, card->position))}, {"known", known && card->code != 0}};
	result.update(ZoneCoordinates(card_zone, engine_sequence));
	if(known && card->code) result["id"] = card->code;
	return result;
}
json Zone(const std::vector<ClientCard*>& cards, bool known) {
	json result = json::array();
	for(auto* card : cards) if(card) result.push_back(Card(card, known));
	return result;
}
json BuildState() {
	auto& f = mainGame->dField;
	json players = json::array();
	for(int p = 0; p < 2; ++p) {
		bool self = p == 0;
		players.push_back({{"player", protocol::ToString(self ? protocol::Player::self : protocol::Player::opponent)}, {"lp", mainGame->dInfo.lp[p]},
			{"hand", self ? Zone(f.hand[p], true) : json{{"count", f.hand[p].size()}}},
			{"deck_count", f.deck[p].size()}, {"extra_count", f.extra[p].size()},
			{"monster_zone", Zone(f.mzone[p], true)}, {"spell_trap_zone", Zone(f.szone[p], true)},
			{"grave", Zone(f.grave[p], true)}, {"banished", Zone(f.remove[p], true)}});
	}
	json chains = json::array();
	for(const auto& chain : f.chains) {
		chains.push_back({{"id", chain.code}, {"player", protocol::ToString(chain.controler == 0 ? protocol::Player::self : protocol::Player::opponent)},
			{"location", chain.location}, {"sequence", chain.sequence}, {"solved", chain.solved}});
	}
	json result = {{"turn", mainGame->dInfo.turn}, {"engine_message", mainGame->dInfo.curMsg},
		{"phase", protocol::ToString(state.phase)}, {"players", players}, {"chains", chains}};
	result["turn_player"] = state.turn_player < 0 ? json(nullptr)
		: json(protocol::ToString(state.turn_player == 0 ? protocol::Player::self : protocol::Player::opponent));
	return result;
}
json InspectZone(const json& arguments) {
	const auto player_name = arguments.value("player", "");
	const auto zone_name = arguments.value("zone", "");
	if(player_name != "self" && player_name != "opponent") return {{"ok", false}, {"error", "invalid_player"}};
	const int player = player_name == "self" ? 0 : 1;
	auto& field = mainGame->dField;
	if(zone_name == "graveyard") return {{"ok", true}, {"player", player_name}, {"zone", zone_name}, {"cards", Zone(field.grave[player], true)}};
	if(zone_name == "banished") return {{"ok", true}, {"player", player_name}, {"zone", zone_name}, {"cards", Zone(field.remove[player], true)}};
	if(zone_name == "extra" && player == 0) return {{"ok", true}, {"player", player_name}, {"zone", zone_name}, {"cards", Zone(field.extra[player], true)}};
	if(zone_name == "deck" && player == 0) return {{"ok", true}, {"player", player_name}, {"zone", zone_name}, {"cards", Zone(field.deck[player], true)}};
	return {{"ok", false}, {"error", "zone_not_inspectable"}};
}
void AddCardChoices(json& choices, const std::vector<ClientCard*>& cards) {
	for(size_t i = 0; i < cards.size(); ++i) if(cards[i]) choices.push_back({{"index", i}, {"card", Card(cards[i], true)}, {"selection_sequence", cards[i]->select_seq}});
}
protocol::Decision DecisionFromMessage(short message) {
	switch(message) {
	case MSG_SELECT_IDLECMD: return protocol::Decision::idle_command; case MSG_SELECT_BATTLECMD: return protocol::Decision::battle_command;
	case MSG_SELECT_EFFECTYN: return protocol::Decision::effect_yes_no; case MSG_SELECT_YESNO: return protocol::Decision::yes_no;
	case MSG_SELECT_OPTION: return protocol::Decision::option; case MSG_SELECT_CARD: return protocol::Decision::card;
	case MSG_SELECT_UNSELECT_CARD: return protocol::Decision::unselect_card; case MSG_SELECT_CHAIN: return protocol::Decision::chain;
	case MSG_SELECT_PLACE: case MSG_SELECT_DISFIELD: return protocol::Decision::place; case MSG_SELECT_POSITION: return protocol::Decision::position;
	case MSG_SELECT_TRIBUTE: return protocol::Decision::tribute; case MSG_SELECT_COUNTER: return protocol::Decision::counter;
	case MSG_SELECT_SUM: return protocol::Decision::sum; case MSG_SORT_CARD: return protocol::Decision::sort_card;
	case MSG_ANNOUNCE_RACE: return protocol::Decision::announce_race; case MSG_ANNOUNCE_ATTRIB: return protocol::Decision::announce_attribute;
	case MSG_ANNOUNCE_CARD: return protocol::Decision::announce_card; case MSG_ANNOUNCE_NUMBER: return protocol::Decision::announce_number;
	case MSG_ROCK_PAPER_SCISSORS: return protocol::Decision::rock_paper_scissors;
	default: return protocol::Decision::unknown;
	}
}

protocol::PreDuelHand PreDuelHandFromWire(uint8_t value) noexcept {
	switch(value) {
	case 1: return protocol::PreDuelHand::scissors;
	case 2: return protocol::PreDuelHand::rock;
	case 3: return protocol::PreDuelHand::paper;
	default: return protocol::PreDuelHand::unknown;
	}
}

protocol::PreDuelHandOutcome PreDuelHandResult(protocol::PreDuelHand self, protocol::PreDuelHand opponent) noexcept {
	if(self == protocol::PreDuelHand::unknown || opponent == protocol::PreDuelHand::unknown)
		return protocol::PreDuelHandOutcome::unknown;
	if(self == opponent) return protocol::PreDuelHandOutcome::draw;
	const bool won = (self == protocol::PreDuelHand::rock && opponent == protocol::PreDuelHand::scissors)
		|| (self == protocol::PreDuelHand::scissors && opponent == protocol::PreDuelHand::paper)
		|| (self == protocol::PreDuelHand::paper && opponent == protocol::PreDuelHand::rock);
	return won ? protocol::PreDuelHandOutcome::win : protocol::PreDuelHandOutcome::loss;
}
}

AgentClient& AgentClient::Instance() { static AgentClient instance; return instance; }
void AgentClient::Configure(bool enabled, std::string host, uint16_t port, int timeout_ms, std::string log_path) {
	std::lock_guard<std::mutex> lock(state.mutex);
	state.enabled = enabled; state.host = std::move(host); state.port = port; state.timeout_ms = timeout_ms; state.log_path = std::move(log_path);
}
void AgentClient::Start() {
	std::lock_guard<std::mutex> lock(state.mutex);
	if(!state.enabled || state.running) return;
	state.running = true; state.worker = std::thread(Worker);
}
void AgentClient::Stop() {
	{ std::lock_guard<std::mutex> lock(state.mutex); if(!state.running) return; state.running = false; state.controlling = false; }
	if(state.worker.joinable()) state.worker.join();
}
void AgentClient::BeginDuel() {
	if(!mainGame) return;
	Configure(mainGame->gameConf.agent_enabled, mainGame->gameConf.agent_host, mainGame->gameConf.agent_port,
		mainGame->gameConf.agent_timeout_ms, mainGame->gameConf.agent_log_path);
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		if(!state.awaiting_duel_start) {
			state.duel_id = GenerateIdentifier();
			state.state_revision = 0;
		}
		state.awaiting_duel_start = false;
		state.last_state = nullptr;
		state.force_snapshot = true;
		state.pending = {};
		state.pre_duel_pending = {};
		state.submission = {};
		state.last_selection_hint = 0;
		state.turn_player = -1;
		state.phase = protocol::Phase::unknown;
		state.next_attack_id = 0;
		state.active_attack_id = 0;
		state.controlling = false;
		DiscardStaleIncomingLocked();
	}
	Start();
}
bool AgentClient::IsControlling() const { std::lock_guard<std::mutex> lock(state.mutex); return state.controlling; }

void AgentClient::OnCardMoved(uint32_t engine_code, uint32_t observed_code, protocol::CardIdProvenance id_provenance,
	int previous_player, uint32_t previous_location, uint32_t previous_sequence,
	uint32_t previous_position, int player, uint32_t location, uint32_t sequence, uint32_t position, uint32_t reason) {
	auto card = observed_code == 0 ? json{{"known", false}} : json{{"known", true}, {"id", observed_code}};
	card["id_provenance"] = protocol::ToString(id_provenance);
	LogDuelEvent(protocol::Event::card_moved, {{"card", card},
		{"engine_code", engine_code},
		{"from", Location(previous_player, previous_location, previous_sequence, previous_position)},
		{"to", Location(player, location, sequence, position)},
		{"reason_flags", reason}, {"reason_flags_authoritative", false},
		{"reasons", MoveReasons(reason)}, {"reasons_authoritative", false},
		{"engine_evidence", {{"message", "MSG_MOVE"}}}});
}

void AgentClient::OnChainAdded(uint32_t code, int player, uint32_t location, uint32_t sequence, uint32_t description, uint32_t chain_index) {
	LogDuelEvent(protocol::Event::chain_added, {{"card", code == 0 ? json{{"known", false}} : json{{"known", true}, {"id", code}}},
		{"source", Location(player, location, sequence, 0)},
		{"effect", EffectDescriptor(code, description)}, {"chain_index", chain_index},
		{"engine_evidence", {{"messages", json::array({"MSG_CHAINING", "MSG_CHAINED"})}}}});
}

void AgentClient::OnChainSolving(uint32_t chain_index) { LogDuelEvent(protocol::Event::chain_solving, {{"chain_index", chain_index}, {"engine_evidence", {{"message", "MSG_CHAIN_SOLVING"}}}}); }
void AgentClient::OnChainResolved(uint32_t chain_index) { LogDuelEvent(protocol::Event::chain_resolved, {{"chain_index", chain_index}, {"engine_evidence", {{"message", "MSG_CHAIN_SOLVED"}}}}); }
void AgentClient::OnChainEnded() { LogDuelEvent(protocol::Event::chain_ended, {{"engine_evidence", {{"message", "MSG_CHAIN_END"}}}}); }
void AgentClient::OnChainStatus(uint32_t chain_index, bool disabled) { LogDuelEvent(disabled ? protocol::Event::chain_disabled : protocol::Event::chain_negated, {{"chain_index", chain_index}, {"engine_evidence", {{"message", disabled ? "MSG_CHAIN_DISABLED" : "MSG_CHAIN_NEGATED"}}}}); }

void AgentClient::OnSummonAttempted(uint32_t code, int player, uint32_t location, uint32_t sequence,
	uint32_t position, protocol::SummonType summon_type) {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode) return;
	const auto evidence = summon_type == protocol::SummonType::normal ? "MSG_SUMMONING"
		: summon_type == protocol::SummonType::special ? "MSG_SPSUMMONING" : "MSG_FLIPSUMMONING";
	LogDuelEvent(protocol::Event::summon_attempted,
		{{"card", {{"id", code}, {"known", code != 0}}}, {"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		 {"summon_type", protocol::ToString(summon_type)}, {"destination", Location(player, location, sequence, position)},
		 {"engine_evidence", {{"message", evidence}}}});
}

void AgentClient::OnSummonSucceeded(protocol::SummonType summon_type) {
	const auto evidence = summon_type == protocol::SummonType::normal ? "MSG_SUMMONED"
		: summon_type == protocol::SummonType::special ? "MSG_SPSUMMONED" : "MSG_FLIPSUMMONED";
	LogDuelEvent(protocol::Event::summon_succeeded,
		{{"summon_type", protocol::ToString(summon_type)}, {"engine_evidence", {{"message", evidence}}}});
}

void AgentClient::OnLifePointsChanged(int player, int before, int after, protocol::LifePointChange change_kind) {
	const auto evidence = change_kind == protocol::LifePointChange::damage ? "MSG_DAMAGE"
		: change_kind == protocol::LifePointChange::recover ? "MSG_RECOVER"
		: change_kind == protocol::LifePointChange::cost ? "MSG_PAY_LPCOST" : "MSG_LPUPDATE";
	LogDuelEvent(protocol::Event::life_points_changed, {{"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		{"before", before}, {"after", after}, {"change_kind", protocol::ToString(change_kind)},
		{"engine_evidence", {{"message", evidence}}}});
}

void AgentClient::OnCardsDrawn(int player, const uint32_t* codes, size_t count) {
	json cards = json::array();
	for(size_t index = 0; index < count; ++index) cards.push_back(codes[index] == 0 ? json{{"known", false}} : json{{"known", true}, {"id", codes[index] & 0x7fffffff}});
	LogDuelEvent(protocol::Event::cards_drawn, {{"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		{"cards", std::move(cards)}, {"engine_evidence", {{"message", "MSG_DRAW"}}}});
}
void AgentClient::OnHiddenZoneShuffled(int player, protocol::Zone zone) {
	LogDuelEvent(protocol::Event::hidden_zone_shuffled, {{"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		{"zone", protocol::ToString(zone)}, {"engine_evidence", {{"message", zone == protocol::Zone::deck ? "MSG_SHUFFLE_DECK" : "MSG_SHUFFLE_HAND"}}}});
}

void AgentClient::OnEngineHint(uint8_t hint_type, int player, uint32_t data) {
	const auto kind = HintTypeFromEngine(hint_type);
	if(kind == protocol::HintType::select_message) {
		std::lock_guard<std::mutex> lock(state.mutex);
		state.last_selection_hint = data;
	}
	json payload = {{"hint_type", protocol::ToString(kind)}, {"protocol_player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		{"raw_value", data}, {"engine_evidence", {{"message", "MSG_HINT"}}}};
	if(kind == protocol::HintType::event || kind == protocol::HintType::message || kind == protocol::HintType::option_selected)
		payload["description"] = Description(data);
	else if(kind == protocol::HintType::effect || kind == protocol::HintType::code || kind == protocol::HintType::card)
		payload["card"] = data == 0 ? json{{"known", false}} : json{{"known", true}, {"id", data}};
	LogDuelEvent(protocol::Event::engine_hint, std::move(payload));
}

void AgentClient::OnCardsConfirmed(protocol::CardObservationKind kind, int context_player, bool skip_panel,
	const std::vector<AgentObservedCard>& cards) {
	json observations = json::array();
	for(const auto& card : cards) observations.push_back(ObservedCard(card));
	const auto evidence = kind == protocol::CardObservationKind::confirm_cards ? "MSG_CONFIRM_CARDS"
		: kind == protocol::CardObservationKind::confirm_deck_top ? "MSG_CONFIRM_DECKTOP"
		: kind == protocol::CardObservationKind::confirm_extra_top ? "MSG_CONFIRM_EXTRATOP" : "MSG_DECK_TOP";
	LogDuelEvent(protocol::Event::cards_confirmed,
		{{"observation_kind", protocol::ToString(kind)},
		 {"context_player", protocol::ToString(context_player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		 {"skip_panel", skip_panel}, {"cards", std::move(observations)}, {"engine_evidence", {{"message", evidence}}}});
}

void AgentClient::OnCardsIndicated(const std::vector<AgentObservedCard>& cards) {
	json observations = json::array();
	for(const auto& card : cards) observations.push_back(ObservedCard(card));
	LogDuelEvent(protocol::Event::cards_indicated,
		{{"cards", std::move(observations)}, {"engine_evidence", {{"message", "MSG_BECOME_TARGET"}}}});
}

void AgentClient::OnCardRelationChanged(protocol::CardRelation relation, const AgentObservedCard& source,
	const AgentObservedCard& target, bool added) {
	LogDuelEvent(added ? protocol::Event::card_relation_added : protocol::Event::card_relation_removed,
		{{"relation", protocol::ToString(relation)}, {"source", ObservedCard(source)}, {"target", ObservedCard(target)},
			 {"engine_evidence", {{"message", relation == protocol::CardRelation::equip ? (added ? "MSG_EQUIP" : "MSG_UNEQUIP") : (added ? "MSG_CARD_TARGET" : "MSG_CANCEL_TARGET")}}}});
}

void AgentClient::OnTurnStarted(int player, uint32_t turn) {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode) return;
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		state.turn_player = player;
		state.phase = protocol::Phase::unknown;
		state.active_attack_id = 0;
	}
	LogDuelEvent(protocol::Event::turn_started,
		{{"turn", turn}, {"turn_player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
		 {"engine_evidence", {{"message", "MSG_NEW_TURN"}}}});
}

void AgentClient::OnPhaseChanged(uint16_t raw_phase) {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode) return;
	const auto phase = PhaseFromEngine(raw_phase);
	int turn_player{};
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		state.phase = phase;
		state.active_attack_id = 0;
		turn_player = state.turn_player;
	}
	json payload = {{"phase", protocol::ToString(phase)}, {"raw_phase", raw_phase},
		{"engine_evidence", {{"message", "MSG_NEW_PHASE"}}}};
	payload["turn_player"] = turn_player < 0 ? json(nullptr)
		: json(protocol::ToString(turn_player == 0 ? protocol::Player::self : protocol::Player::opponent));
	LogDuelEvent(protocol::Event::phase_changed, std::move(payload));
}

void AgentClient::OnAttackDeclared(const AgentObservedCard& attacker, const AgentObservedCard* target) {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode) return;
	uint64_t attack_id{};
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		attack_id = ++state.next_attack_id;
		state.active_attack_id = attack_id;
	}
	LogDuelEvent(protocol::Event::attack_declared,
		{{"attack_id", attack_id}, {"attacker", ObservedCard(attacker)},
		 {"target", target ? ObservedCard(*target) : json(nullptr)}, {"direct_attack", target == nullptr},
		 {"engine_evidence", {{"message", "MSG_ATTACK"}}}});
}

void AgentClient::OnBattleSnapshot(const AgentObservedCard& attacker, int attack, int defense, bool destroyed,
	const AgentObservedCard* defender, int defender_attack, int defender_defense, bool defender_destroyed) {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode) return;
	uint64_t attack_id{};
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		attack_id = state.active_attack_id;
		state.active_attack_id = 0;
	}
	json attacker_snapshot = {{"observation", ObservedCard(attacker)}, {"attack", attack}, {"defense", defense},
		{"destroyed_by_battle", destroyed}};
	json defender_snapshot = nullptr;
	if(defender) {
		defender_snapshot = {{"observation", ObservedCard(*defender)}, {"attack", defender_attack},
			{"defense", defender_defense}, {"destroyed_by_battle", defender_destroyed}};
	}
	json payload = {{"attacker", std::move(attacker_snapshot)}, {"defender", std::move(defender_snapshot)},
		{"direct_attack", defender == nullptr}, {"engine_evidence", {{"message", "MSG_BATTLE"}}}};
	payload["attack_id"] = attack_id == 0 ? json(nullptr) : json(attack_id);
	LogDuelEvent(protocol::Event::battle_snapshot, std::move(payload));
}

void AgentClient::OnAttackDisabled() {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode) return;
	uint64_t attack_id{};
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		attack_id = state.active_attack_id;
		state.active_attack_id = 0;
	}
	json payload = {{"engine_evidence", {{"message", "MSG_ATTACK_DISABLED"}}}};
	payload["attack_id"] = attack_id == 0 ? json(nullptr) : json(attack_id);
	LogDuelEvent(protocol::Event::attack_disabled, std::move(payload));
}

void AgentClient::OnDecisionSubmitted(const uint8_t* response, size_t length) {
	const short engine_message = mainGame ? mainGame->dInfo.curMsg : 0;
	SubmissionContext submission;
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		if(state.submission.id != 0 && state.submission.msg == engine_message)
			submission = std::move(state.submission);
		state.submission = {};
	}
	json bytes = json::array();
	for(size_t index = 0; index < length; ++index) bytes.push_back(response[index]);
	const bool matched = submission.id != 0;
	json payload = {{"engine_message", engine_message}, {"decision_kind", protocol::ToString(matched
		? submission.decision : DecisionFromMessage(engine_message))}, {"matched", matched},
		{"response_bytes", std::move(bytes)}, {"engine_evidence", {{"message", "CTOS_RESPONSE"}}}};
	if(matched) {
		payload["request_id"] = submission.id;
		if(length >= sizeof(int32_t)) {
			int32_t integer_response{};
			std::memcpy(&integer_response, response, sizeof integer_response);
			const auto choice = submission.choices.find(integer_response);
			if(choice != submission.choices.end()) {
				payload["choice_id"] = choice->second.id;
				payload["action"] = protocol::ToString(choice->second.action);
			}
		}
		if(!submission.card_sequences.empty() && length >= 1
			&& length == static_cast<size_t>(response[0]) + 1) {
			json selected_indices = json::array();
			json selected_cards = json::array();
			bool decoded = true;
			for(size_t response_index = 1; response_index < length; ++response_index) {
				const auto selected = std::find(submission.card_sequences.begin(), submission.card_sequences.end(), response[response_index]);
				if(selected == submission.card_sequences.end()) {
					decoded = false;
					break;
				}
				const auto choice_index = static_cast<size_t>(std::distance(submission.card_sequences.begin(), selected));
				selected_indices.push_back(choice_index);
				const auto card_choice = std::find_if(submission.card_choices.begin(), submission.card_choices.end(),
					[choice_index](const json& value) { return value.value("index", SIZE_MAX) == choice_index; });
				if(card_choice == submission.card_choices.end() || !card_choice->contains("card")) {
					decoded = false;
					break;
				}
				selected_cards.push_back((*card_choice)["card"]);
			}
			if(decoded) {
				payload["selected_indices"] = std::move(selected_indices);
				payload["selected_cards"] = std::move(selected_cards);
			}
		}
	}
	LogDuelEvent(protocol::Event::decision_submitted, std::move(payload));
}

void AgentClient::OnSurrenderRequested() { LogDuelEvent(protocol::Event::surrender_requested, {{"actor", protocol::ToString(protocol::Player::self)}, {"engine_evidence", {{"message", "CTOS_SURRENDER"}}}}); }
void AgentClient::OnDuelEnded(protocol::DuelWinner winner, uint8_t raw_winner, uint8_t reason) {
	LogDuelEvent(protocol::Event::duel_ended,
		{{"winner", protocol::ToString(winner)}, {"raw_winner", raw_winner}, {"reason", reason},
		 {"engine_evidence", {{"message", "MSG_WIN"}}}});
}

void AgentClient::CapturePreDuelDecision(protocol::Decision decision) {
	if(!mainGame) return;
	Configure(mainGame->gameConf.agent_enabled, mainGame->gameConf.agent_host, mainGame->gameConf.agent_port,
		mainGame->gameConf.agent_timeout_ms, mainGame->gameConf.agent_log_path);
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		if(!state.enabled) return;
		if(!state.awaiting_duel_start) {
			state.duel_id = GenerateIdentifier();
			state.awaiting_duel_start = true;
			state.state_revision = 0;
			state.last_state = nullptr;
			state.force_snapshot = true;
			state.pending = {};
			state.pre_duel_pending = {};
			state.submission = {};
			state.turn_player = -1;
			state.phase = protocol::Phase::unknown;
			state.next_attack_id = 0;
			state.active_attack_id = 0;
			state.controlling = false;
			DiscardStaleIncomingLocked();
		}
	}
	Start();
	std::lock_guard<std::mutex> lock(state.mutex);
	const json choices = decision == protocol::Decision::pre_duel_hand
		? json::array({{{"id", 0}, {"action", protocol::ToString(protocol::Action::scissors)}, {"raw_value", 1}},
			{{"id", 1}, {"action", protocol::ToString(protocol::Action::rock)}, {"raw_value", 2}},
			{{"id", 2}, {"action", protocol::ToString(protocol::Action::paper)}, {"raw_value", 3}}})
		: json::array({{{"id", 0}, {"action", protocol::ToString(protocol::Action::go_first)}, {"raw_value", 1}},
			{{"id", 1}, {"action", protocol::ToString(protocol::Action::go_second)}, {"raw_value", 0}}});
	const uint64_t event_id = NextEventId();
	const uint64_t state_revision = ++state.state_revision;
	const uint64_t request_id = ++state.next_request_id;
	state.pre_duel_pending = {request_id, decision};
	json request = {{"type", protocol::ToString(protocol::MessageType::decision_request)}, {"protocol_version", protocol::protocol_version}, {"session_id", state.session_id}, {"duel_id", state.duel_id}, {"event_id", event_id}, {"timestamp_unix_ms", UnixMilliseconds()}, {"request_id", request_id}, {"state_revision", state_revision},
		{"state_delta", {{"mode", protocol::ToString(protocol::DeltaMode::snapshot)}, {"data", {{"stage", "pre_duel"}}}}},
		{"decision", {{"kind", protocol::ToString(decision)}, {"choices", choices}}}};
	Log({{"event_id", event_id}, {"direction", protocol::ToString(protocol::Direction::local)}, {"message", request}});
}

void AgentClient::OnPreDuelDecisionSubmitted(protocol::Decision decision, protocol::Action action, uint8_t raw_value) {
	uint64_t request_id{};
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		if(state.pre_duel_pending.decision == decision) {
			request_id = state.pre_duel_pending.id;
			state.pre_duel_pending = {};
		}
	}
	json payload = {{"decision_kind", protocol::ToString(decision)}, {"action", protocol::ToString(action)},
		{"raw_value", raw_value}, {"matched", request_id != 0},
		{"engine_evidence", {{"message", decision == protocol::Decision::pre_duel_hand ? "CTOS_HAND_RESULT" : "CTOS_TP_RESULT"}}}};
	if(request_id != 0) {
		payload["request_id"] = request_id;
		if(decision == protocol::Decision::pre_duel_hand)
			payload["choice_id"] = raw_value == 1 ? 0 : raw_value == 2 ? 1 : 2;
		else
			payload["choice_id"] = raw_value != 0 ? 0 : 1;
	}
	LogDuelEvent(protocol::Event::decision_submitted, std::move(payload));
}

void AgentClient::OnPreDuelHandResult(uint8_t self_hand, uint8_t opponent_hand) {
	const auto self = PreDuelHandFromWire(self_hand);
	const auto opponent = PreDuelHandFromWire(opponent_hand);
	LogDuelEvent(protocol::Event::pre_duel_hand_result,
		{{"self_hand", protocol::ToString(self)}, {"opponent_hand", protocol::ToString(opponent)},
		 {"outcome", protocol::ToString(PreDuelHandResult(self, opponent))},
		 {"raw_self_hand", self_hand}, {"raw_opponent_hand", opponent_hand},
		 {"engine_evidence", {{"message", "STOC_HAND_RESULT"}}}});
}

void AgentClient::OnDecisionAvailable(const unsigned char* message, size_t length) {
	if(!mainGame || mainGame->dInfo.isReplay || mainGame->dInfo.isSingleMode || !IsDecision(mainGame->dInfo.curMsg)) return;
	Configure(mainGame->gameConf.agent_enabled, mainGame->gameConf.agent_host, mainGame->gameConf.agent_port,
		mainGame->gameConf.agent_timeout_ms, mainGame->gameConf.agent_log_path);
	Start();
	std::lock_guard<std::mutex> lock(state.mutex);
	if(!state.enabled || state.pending.id) return;
	if(state.duel_id.empty()) {
		state.duel_id = GenerateIdentifier();
		state.state_revision = 0;
		state.last_state = nullptr;
		state.force_snapshot = true;
	}
	const bool can_dispatch = state.connected && state.handshaken;
	const auto decision_kind = DecisionFromMessage(mainGame->dInfo.curMsg);
	state.pending = {};
	state.pending.id = ++state.next_request_id;
	state.pending.msg = mainGame->dInfo.curMsg;
	state.submission = {};
	state.submission.id = state.pending.id;
	state.submission.msg = mainGame->dInfo.curMsg;
	state.submission.decision = decision_kind;
	json decision = {{"kind", protocol::ToString(decision_kind)}, {"engine_message", mainGame->dInfo.curMsg}, {"min", mainGame->dField.select_min}, {"max", mainGame->dField.select_max}};
	if(state.last_selection_hint != 0) {
		decision["selection_hint"] = {{"raw_value", state.last_selection_hint}};
		state.last_selection_hint = 0;
	}
	json choices = json::array();
	uint32_t next_choice_id{};
	auto add = [&](int v, protocol::Action action, ClientCard* card = nullptr,
		std::optional<size_t> effect_candidate = std::nullopt, std::optional<uint32_t> option_description = std::nullopt) {
		const uint32_t choice_id = next_choice_id++;
		state.pending.integers.insert(v);
		state.pending.choice_responses.emplace(choice_id, v);
		json choice = {{"id", choice_id}, {"action", protocol::ToString(action)}};
		if(card) choice["card"] = Card(card, true);
		if(effect_candidate && *effect_candidate < mainGame->dField.activatable_descs.size()) {
			const auto [description, flags] = mainGame->dField.activatable_descs[*effect_candidate];
			auto effect = EffectDescriptor(card ? card->code : 0, static_cast<uint32_t>(description));
			effect["engine_candidate_index"] = *effect_candidate;
			effect["raw_flags"] = flags;
			effect["operation"] = (flags & EDESC_OPERATION) != 0;
			effect["reset"] = (flags & EDESC_RESET) != 0;
			effect["forced"] = (flags & forced_effect_candidate_flag) != 0;
			choice["effect_candidate"] = std::move(effect);
		}
		if(option_description) choice["option"] = Description(*option_description);
		state.submission.choices.emplace(v, SubmissionChoice{choice_id, action});
		choices.push_back(std::move(choice));
	};
	switch(mainGame->dInfo.curMsg) {
	case MSG_SELECT_YESNO: case MSG_SELECT_EFFECTYN: add(0, protocol::Action::decline); add(1, protocol::Action::accept); break;
	case MSG_SELECT_OPTION: for(size_t i = 0; i < mainGame->dField.select_options.size(); ++i)
		add(static_cast<int>(i), protocol::Action::select_option, nullptr, std::nullopt, static_cast<uint32_t>(mainGame->dField.select_options[i])); break;
	case MSG_SELECT_POSITION: {
		// Wire format is message, player, card code, allowed-position bit mask.
		unsigned char positions = length > 6 ? message[6] : 0;
		if(positions & 1) add(1, protocol::Action::face_up_attack); if(positions & 2) add(2, protocol::Action::face_down_attack);
		if(positions & 4) add(4, protocol::Action::face_up_defense); if(positions & 8) add(8, protocol::Action::face_down_defense); break;
	}
	case MSG_SELECT_PLACE:
	case MSG_SELECT_DISFIELD: {
		json zones = json::array();
		const uint32_t mask = mainGame->dField.selectable_field;
		for(int player = 0; player < 2; ++player) {
			const int base = player ? 16 : 0;
			for(int sequence = 0; sequence < 7; ++sequence) {
				if((mask & (uint32_t(1) << (base + sequence))) == 0) continue;
				const auto zone = ZoneFromLocation(LOCATION_MZONE, sequence);
				json choice = {{"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
					{"zone", protocol::ToString(zone)}};
				choice.update(ZoneCoordinates(zone, static_cast<uint32_t>(sequence)));
				zones.push_back(std::move(choice));
			}
			for(int sequence = 0; sequence < 8; ++sequence) {
				if((mask & (uint32_t(1) << (base + 8 + sequence))) == 0) continue;
				json choice = {{"player", protocol::ToString(player == 0 ? protocol::Player::self : protocol::Player::opponent)},
					{"zone", protocol::ToString(protocol::Zone::spell_trap)}};
				choice.update(ZoneCoordinates(protocol::Zone::spell_trap, static_cast<uint32_t>(sequence)));
				zones.push_back(std::move(choice));
			}
		}
		decision["zone_choices"] = std::move(zones);
		break;
	}
	case MSG_SELECT_IDLECMD:
		for(size_t i=0;i<mainGame->dField.summonable_cards.size();++i) add(int(i)<<16,protocol::Action::normal_summon,mainGame->dField.summonable_cards[i]);
		for(size_t i=0;i<mainGame->dField.spsummonable_cards.size();++i) add((int(i)<<16)+1,protocol::Action::special_summon,mainGame->dField.spsummonable_cards[i]);
		for(size_t i=0;i<mainGame->dField.reposable_cards.size();++i) add((int(i)<<16)+2,protocol::Action::change_position,mainGame->dField.reposable_cards[i]);
		for(size_t i=0;i<mainGame->dField.msetable_cards.size();++i) add((int(i)<<16)+3,protocol::Action::set_monster,mainGame->dField.msetable_cards[i]);
		for(size_t i=0;i<mainGame->dField.ssetable_cards.size();++i) add((int(i)<<16)+4,protocol::Action::set_spell_trap,mainGame->dField.ssetable_cards[i]);
		for(size_t i=0;i<mainGame->dField.activatable_cards.size();++i) add((int(i)<<16)+5,protocol::Action::activate,mainGame->dField.activatable_cards[i], i); add(6,protocol::Action::enter_battle_phase); add(7,protocol::Action::end_phase); break;
	case MSG_SELECT_BATTLECMD:
		for(size_t i=0;i<mainGame->dField.activatable_cards.size();++i) add(int(i)<<16,protocol::Action::activate,mainGame->dField.activatable_cards[i], i);
		for(size_t i=0;i<mainGame->dField.attackable_cards.size();++i) add((int(i)<<16)+1,protocol::Action::attack,mainGame->dField.attackable_cards[i]); add(2,protocol::Action::enter_main_phase_2); add(3,protocol::Action::end_phase); break;
	case MSG_SELECT_CHAIN:
		for(size_t i=0;i<mainGame->dField.activatable_cards.size();++i) add(static_cast<int>(i), protocol::Action::activate, mainGame->dField.activatable_cards[i], i);
		if(!mainGame->dField.chain_forced) { add(-1, protocol::Action::pass_chain); state.pending.cancel = true; }
		break;
	case MSG_ROCK_PAPER_SCISSORS: add(1, protocol::Action::scissors); add(2, protocol::Action::rock); add(3, protocol::Action::paper); break;
	default: break;
	}
	if(mainGame->dInfo.curMsg == MSG_SELECT_EFFECTYN && length >= 14) {
		uint32_t code{};
		uint32_t description{};
		std::memcpy(&code, message + 2, sizeof code);
		std::memcpy(&description, message + 10, sizeof description);
		const int player = mainGame->LocalPlayer(message[6]);
		decision["effect_prompt"] = {{"card", code == 0 ? json{{"known", false}} : json{{"known", true}, {"id", code}}},
			{"source", Location(player, message[7], message[8], message[9])}, {"effect", EffectDescriptor(code, description)}};
	} else if(mainGame->dInfo.curMsg == MSG_SELECT_YESNO && length >= 6) {
		uint32_t description{};
		std::memcpy(&description, message + 2, sizeof description);
		decision["prompt"] = Description(description);
	}
	decision["choices"] = choices;
	if(mainGame->dInfo.curMsg == MSG_SELECT_CARD || mainGame->dInfo.curMsg == MSG_SELECT_TRIBUTE || mainGame->dInfo.curMsg == MSG_SELECT_SUM || mainGame->dInfo.curMsg == MSG_SELECT_UNSELECT_CARD) {
		decision["card_choices"] = json::array(); AddCardChoices(decision["card_choices"], mainGame->dField.selectable_cards);
		for(auto* card : mainGame->dField.selectable_cards) {
			state.pending.card_sequences.push_back(card->select_seq);
			state.submission.card_sequences.push_back(card->select_seq);
		}
		state.submission.card_choices = decision["card_choices"];
		state.pending.min_cards = mainGame->dField.select_min; state.pending.max_cards = mainGame->dField.select_max; state.pending.cancel = mainGame->dField.select_cancelable;
	}
	state.pending.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(state.timeout_ms);
	state.controlling = can_dispatch;
	const json snapshot = BuildState();
	const bool has_snapshot = state.force_snapshot || state.last_state.is_null();
	const json patch = has_snapshot ? json::array() : json::diff(state.last_state, snapshot);
	const bool state_changed = has_snapshot || !patch.empty();
	json delta;
	if(has_snapshot) {
		++state.state_revision;
		delta = {{"mode", protocol::ToString(protocol::DeltaMode::snapshot)}, {"data", snapshot}};
	} else if(state_changed) {
		++state.state_revision;
		delta = {{"mode", protocol::ToString(protocol::DeltaMode::json_patch)}, {"data", patch}};
	} else {
		delta = {{"mode", protocol::ToString(protocol::DeltaMode::none)}};
	}
	const uint64_t event_id = NextEventId();
	json request = {{"type", protocol::ToString(protocol::MessageType::decision_request)}, {"protocol_version", protocol::protocol_version}, {"session_id", state.session_id}, {"duel_id", state.duel_id}, {"event_id", event_id}, {"timestamp_unix_ms", UnixMilliseconds()}, {"request_id", state.pending.id}, {"state_revision", state.state_revision},
		{"state_delta", delta}, {"decision", decision}};
	if(state_changed && !has_snapshot) request["base_state_revision"] = state.state_revision - 1;
	if(state_changed) { state.last_state = snapshot; state.force_snapshot = false; }
	Log({{"event_id", event_id}, {"direction", protocol::ToString(can_dispatch ? protocol::Direction::outbound : protocol::Direction::local)}, {"message", request}});
	if(!can_dispatch) {
		// Capture-only mode: do not leave a pending request that would suppress
		// the next prompt while no agent is available.
		state.pending = {};
		state.controlling = false;
		return;
	}
	// Queue directly while holding the same mutex to keep request and snapshot atomic.
	const auto body = request.dump(); std::string frame(4, '\0'); uint32_t n = htonl(static_cast<uint32_t>(body.size())); std::memcpy(frame.data(), &n, 4); frame += body; state.outgoing.emplace_back(std::move(frame));
}

void AgentClient::Poll() {
	json reply;
	Pending pending;
	std::string session_id;
	std::string duel_id;
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		if(state.pending.id && std::chrono::steady_clock::now() > state.pending.deadline) { Log({{"event_id", NextEventId()}, {"event",protocol::ToString(protocol::Event::timeout)},{"request_id",state.pending.id}}); state.pending = {}; state.controlling = false; }
		if(state.incoming.empty()) return;
		reply = std::move(state.incoming.front()); state.incoming.pop_front(); pending = state.pending;
		session_id = state.session_id;
		duel_id = state.duel_id;
		if(reply.value("type", "") == protocol::ToString(protocol::MessageType::hello_ack)) {
			state.handshaken = true;
			state.force_snapshot = true;
			state.pending = {};
			state.controlling = false;
			return;
		}
	}
	Log({{"event_id", NextEventId()}, {"direction", protocol::ToString(protocol::Direction::inbound)}, {"message", reply}});
	if(reply.value("type", "") == protocol::ToString(protocol::MessageType::tool_call) && reply.value("tool", "") == "inspect_zone") {
		if(reply.value("duel_id", "") != duel_id) {
			Log({{"event_id", NextEventId()}, {"event", protocol::ToString(protocol::Event::invalid_action)},
				{"reply", reply}});
			return;
		}
		const auto result = InspectZone(reply.value("arguments", json::object()));
		const auto event_id = NextEventId();
		const json message = {{"type", protocol::ToString(protocol::MessageType::tool_result)},
			{"protocol_version", protocol::protocol_version}, {"session_id", session_id}, {"duel_id", duel_id},
			{"event_id", event_id}, {"timestamp_unix_ms", UnixMilliseconds()},
			{"tool_call_id", reply.value("tool_call_id", "")}, {"result", result}};
		Queue(message);
		Log({{"event_id", event_id}, {"direction", protocol::ToString(protocol::Direction::outbound)}, {"message", message}});
		return;
	}
	if(reply.value("type", "") != protocol::ToString(protocol::MessageType::action)
		|| reply.value("duel_id", duel_id) != duel_id || reply.value("request_id", uint64_t{}) != pending.id
		|| pending.id == 0 || mainGame->dInfo.curMsg != pending.msg)
		return;
	auto action = reply.value("action", json::object()); auto kind = action.value("kind", "");
	bool valid = false;
	if(kind == protocol::ToString(protocol::ResponseKind::choice)) { const auto choice_id = action.value("choice_id", UINT32_MAX); const auto choice = pending.choice_responses.find(choice_id); valid = choice != pending.choice_responses.end(); if(valid) DuelClient::SetResponseI(choice->second); }
	else if(kind == protocol::ToString(protocol::ResponseKind::integer)) { int value = action.value("value", INT32_MIN); valid = pending.integers.count(value) != 0; if(valid) DuelClient::SetResponseI(value); }
	else if(kind == protocol::ToString(protocol::ResponseKind::cancel) && pending.cancel) { valid = true; DuelClient::SetResponseI(-1); }
	else if(kind == protocol::ToString(protocol::ResponseKind::cards) && action.contains("indices") && action["indices"].is_array()) {
		auto indices = action["indices"].get<std::vector<int>>(); std::unordered_set<int> unique(indices.begin(), indices.end());
		valid = indices.size() == unique.size() && int(indices.size()) >= pending.min_cards && int(indices.size()) <= pending.max_cards;
		for(int index : indices) valid = valid && index >= 0 && index < int(pending.card_sequences.size());
		if(valid) { std::vector<unsigned char> buffer{static_cast<unsigned char>(indices.size())}; for(int index : indices) buffer.push_back(static_cast<unsigned char>(pending.card_sequences[index])); DuelClient::SetResponseB(buffer.data(), buffer.size()); }
	}
	{
		std::lock_guard<std::mutex> lock(state.mutex); state.pending = {}; state.controlling = false;
	}
	if(valid) DuelClient::SendResponse(); else Log({{"event_id", NextEventId()}, {"event", protocol::ToString(protocol::Event::invalid_action)}, {"reply", reply}});
}
}
