#include "agent_client.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <mutex>
#include <thread>
#include <unordered_set>
#include <vector>

#include <event2/buffer.h>
#include <event2/bufferevent.h>
#include <event2/event.h>
#include <event2/util.h>
#include <nlohmann/json.hpp>

#include "../client_card.h"
#include "../duelclient.h"
#include "../game.h"
#include "../network.h"

namespace ygo {
namespace {
using json = nlohmann::json;

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
	std::vector<int> card_sequences;
	int min_cards{};
	int max_cards{};
	bool cancel{};
	std::chrono::steady_clock::time_point deadline;
};

struct State {
	std::mutex mutex;
	bool enabled{};
	bool running{};
	bool connected{};
	bool hello_sent{};
	bool handshaken{};
	bool controlling{};
	std::string host{"127.0.0.1"};
	uint16_t port{7450};
	int timeout_ms{15000};
	std::string log_path{"agent-log.jsonl"};
	uint64_t revision{};
	uint64_t next_request{};
	std::deque<std::string> outgoing;
	std::deque<json> incoming;
	std::string input;
	json last_state;
	Pending pending;
	std::thread worker;
	event_base* base{};
	bufferevent* bev{};
};
State state;
std::mutex log_mutex;

void Log(const json& value) {
	std::lock_guard<std::mutex> lock(log_mutex);
	if(FILE* fp = std::fopen(state.log_path.c_str(), "ab")) {
		auto line = value.dump();
		std::fwrite(line.data(), 1, line.size(), fp);
		std::fwrite("\n", 1, 1, fp);
		std::fclose(fp);
	}
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
					json hello = {{"type", "hello"}, {"protocol", 1}, {"language", "zh-CN"}, {"client", "ygopro"}};
					const auto body = hello.dump(); uint32_t n = htonl(static_cast<uint32_t>(body.size()));
					bufferevent_write(state.bev, &n, 4); bufferevent_write(state.bev, body.data(), body.size()); state.hello_sent = true;
				}
				while(!state.outgoing.empty()) { bufferevent_write(state.bev, state.outgoing.front().data(), state.outgoing.front().size()); state.outgoing.pop_front(); }
			}
		}
		event_base_loop(state.base, EVLOOP_NONBLOCK);
		std::this_thread::sleep_for(std::chrono::milliseconds(10));
	}
	bufferevent_free(state.bev); state.bev = nullptr; event_base_free(state.base); state.base = nullptr;
}

json Card(ClientCard* card, bool known) {
	auto zone = [](unsigned char location) {
		switch(location) {
		case LOCATION_HAND: return "手牌"; case LOCATION_MZONE: return "怪兽区";
		case LOCATION_SZONE: return "魔法陷阱区"; case LOCATION_GRAVE: return "墓地";
		case LOCATION_REMOVED: return "除外区"; case LOCATION_EXTRA: return "额外卡组";
		case LOCATION_DECK: return "卡组"; default: return "未知区域";
		}
	};
	auto position = [card](unsigned char value) {
		if(card->location == LOCATION_HAND || card->location == LOCATION_DECK || card->location == LOCATION_EXTRA)
			return "不公开";
		if(card->location == LOCATION_SZONE)
			return (value & POS_FACEDOWN) ? "里侧" : "表侧";
		if(value & POS_FACEUP_ATTACK) return "表侧攻击表示";
		if(value & POS_FACEDOWN_ATTACK) return "里侧攻击表示";
		if(value & POS_FACEUP_DEFENSE) return "表侧守备表示";
		if(value & POS_FACEDOWN_DEFENSE) return "里侧守备表示";
		return "不适用";
	};
	json result = {{"zone", zone(card->location)}, {"sequence", card->sequence}, {"position", position(card->position)}, {"known", known && card->code != 0}};
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
		players.push_back({{"player", self ? "我方" : "对方"}, {"lp", mainGame->dInfo.lp[p]},
			{"hand", self ? Zone(f.hand[p], true) : json{{"count", f.hand[p].size()}}},
			{"deck_count", f.deck[p].size()}, {"extra_count", f.extra[p].size()},
			{"monster_zone", Zone(f.mzone[p], true)}, {"spell_trap_zone", Zone(f.szone[p], true)},
			{"grave", Zone(f.grave[p], self)}, {"banished", Zone(f.remove[p], self)}});
	}
	json chains = json::array();
	for(const auto& chain : f.chains) {
		chains.push_back({{"id", chain.code}, {"player", chain.controler == 0 ? "我方" : "对方"},
			{"location", chain.location}, {"sequence", chain.sequence}, {"solved", chain.solved}});
	}
	return {{"turn", mainGame->dInfo.turn}, {"phase_message", mainGame->dInfo.curMsg}, {"players", players}, {"chains", chains}};
}
void AddCardChoices(json& choices, const std::vector<ClientCard*>& cards) {
	for(size_t i = 0; i < cards.size(); ++i) if(cards[i]) choices.push_back({{"index", i}, {"card", Card(cards[i], true)}, {"selection_sequence", cards[i]->select_seq}});
}
const char* MessageName(short message) {
	switch(message) {
	case MSG_SELECT_IDLECMD: return "主要阶段行动"; case MSG_SELECT_BATTLECMD: return "战斗阶段行动";
	case MSG_SELECT_EFFECTYN: return "是否发动效果"; case MSG_SELECT_YESNO: return "是或否";
	case MSG_SELECT_OPTION: return "效果选项"; case MSG_SELECT_CARD: return "选择卡片";
	case MSG_SELECT_CHAIN: return "连锁选择"; case MSG_SELECT_PLACE: return "选择放置区域";
	case MSG_SELECT_POSITION: return "选择表示形式"; case MSG_SELECT_TRIBUTE: return "选择祭品";
	case MSG_SELECT_SUM: return "选择素材"; case MSG_ROCK_PAPER_SCISSORS: return "猜拳出拳";
	default: return "游戏操作";
	}
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
bool AgentClient::IsControlling() const { std::lock_guard<std::mutex> lock(state.mutex); return state.controlling; }

void AgentClient::CapturePreDuelDecision(const char* kind) {
	if(!mainGame) return;
	Configure(mainGame->gameConf.agent_enabled, mainGame->gameConf.agent_host, mainGame->gameConf.agent_port,
		mainGame->gameConf.agent_timeout_ms, mainGame->gameConf.agent_log_path);
	std::lock_guard<std::mutex> lock(state.mutex);
	if(!state.enabled) return;
	json choices = kind == std::string("猜拳出拳")
		? json::array({{{"value", 1}, {"label", "石头"}}, {{"value", 2}, {"label", "剪刀"}}, {{"value", 3}, {"label", "布"}}})
		: json::array({{{"value", 1}, {"label", "先攻"}}, {{"value", 0}, {"label", "后攻"}}});
	json request = {{"type", "decision_request"}, {"request_id", ++state.next_request}, {"revision", ++state.revision},
		{"summary", std::string("请为我方") + kind + "。"}, {"state_delta", {{"mode", "snapshot"}, {"data", {{"stage", "开局"}}}}},
		{"decision", {{"kind", kind}, {"integer_choices", choices}}}};
	Log({{"direction", "local"}, {"message", request}});
}

void AgentClient::OnDecisionAvailable(const unsigned char* message, size_t length) {
	if(!mainGame || mainGame->dInfo.isReplay || !IsDecision(mainGame->dInfo.curMsg)) return;
	Configure(mainGame->gameConf.agent_enabled, mainGame->gameConf.agent_host, mainGame->gameConf.agent_port,
		mainGame->gameConf.agent_timeout_ms, mainGame->gameConf.agent_log_path);
	Start();
	std::lock_guard<std::mutex> lock(state.mutex);
	if(!state.enabled || state.pending.id) return;
	const bool can_dispatch = state.connected && state.handshaken;
	json decision = {{"message", mainGame->dInfo.curMsg}, {"min", mainGame->dField.select_min}, {"max", mainGame->dField.select_max}};
	json integers = json::array();
	auto add = [&](int v, const char* name, ClientCard* card = nullptr) {
		state.pending.integers.insert(v);
		json choice = {{"value", v}, {"label", name}};
		if(card) choice["card"] = Card(card, true);
		integers.push_back(std::move(choice));
	};
	switch(mainGame->dInfo.curMsg) {
	case MSG_SELECT_YESNO: case MSG_SELECT_EFFECTYN: add(0, "否"); add(1, "是"); break;
	case MSG_SELECT_OPTION: for(size_t i = 0; i < mainGame->dField.select_options.size(); ++i) add(static_cast<int>(i), "选项"); break;
	case MSG_SELECT_POSITION: {
		// Wire format is message, player, card code, allowed-position bit mask.
		unsigned char positions = length > 6 ? message[6] : 0;
		if(positions & 1) add(1, "表侧攻击"); if(positions & 2) add(2, "里侧攻击");
		if(positions & 4) add(4, "表侧守备"); if(positions & 8) add(8, "里侧守备"); break;
	}
	case MSG_SELECT_PLACE:
	case MSG_SELECT_DISFIELD: {
		json zones = json::array();
		const uint32_t mask = mainGame->dField.selectable_field;
		for(int player = 0; player < 2; ++player) {
			const int base = player ? 16 : 0;
			for(int sequence = 0; sequence < 7; ++sequence)
				if(mask & (uint32_t(1) << (base + sequence))) zones.push_back({{"player", player == 0 ? "我方" : "对方"}, {"zone", "怪兽区"}, {"sequence", sequence}});
			for(int sequence = 0; sequence < 8; ++sequence)
				if(mask & (uint32_t(1) << (base + 8 + sequence))) zones.push_back({{"player", player == 0 ? "我方" : "对方"}, {"zone", "魔法陷阱区"}, {"sequence", sequence}});
		}
		decision["zone_choices"] = std::move(zones);
		break;
	}
	case MSG_SELECT_IDLECMD:
		for(size_t i=0;i<mainGame->dField.summonable_cards.size();++i) add(int(i)<<16,"通常召唤",mainGame->dField.summonable_cards[i]);
		for(size_t i=0;i<mainGame->dField.spsummonable_cards.size();++i) add((int(i)<<16)+1,"特殊召唤",mainGame->dField.spsummonable_cards[i]);
		for(size_t i=0;i<mainGame->dField.reposable_cards.size();++i) add((int(i)<<16)+2,"改变表示形式",mainGame->dField.reposable_cards[i]);
		for(size_t i=0;i<mainGame->dField.msetable_cards.size();++i) add((int(i)<<16)+3,"盖放怪兽",mainGame->dField.msetable_cards[i]);
		for(size_t i=0;i<mainGame->dField.ssetable_cards.size();++i) add((int(i)<<16)+4,"盖放魔陷",mainGame->dField.ssetable_cards[i]);
		for(size_t i=0;i<mainGame->dField.activatable_cards.size();++i) add((int(i)<<16)+5,"发动",mainGame->dField.activatable_cards[i]); add(6,"进入战斗阶段"); add(7,"结束回合"); break;
	case MSG_SELECT_BATTLECMD:
		for(size_t i=0;i<mainGame->dField.activatable_cards.size();++i) add(int(i)<<16,"发动",mainGame->dField.activatable_cards[i]);
		for(size_t i=0;i<mainGame->dField.attackable_cards.size();++i) add((int(i)<<16)+1,"攻击",mainGame->dField.attackable_cards[i]); add(2,"主要阶段2"); add(3,"结束回合"); break;
	case MSG_SELECT_CHAIN:
		for(size_t i=0;i<mainGame->dField.activatable_cards.size();++i) add(static_cast<int>(i), "发动连锁", mainGame->dField.activatable_cards[i]);
		if(!mainGame->dField.chain_forced) { add(-1, "不连锁"); state.pending.cancel = true; }
		break;
	case MSG_ROCK_PAPER_SCISSORS: add(1, "石头"); add(2, "剪刀"); add(3, "布"); break;
	default: break;
	}
	decision["integer_choices"] = integers;
	if(mainGame->dInfo.curMsg == MSG_SELECT_CARD || mainGame->dInfo.curMsg == MSG_SELECT_TRIBUTE || mainGame->dInfo.curMsg == MSG_SELECT_SUM || mainGame->dInfo.curMsg == MSG_SELECT_UNSELECT_CARD) {
		decision["card_choices"] = json::array(); AddCardChoices(decision["card_choices"], mainGame->dField.selectable_cards);
		for(auto* card : mainGame->dField.selectable_cards) state.pending.card_sequences.push_back(card->select_seq);
		state.pending.min_cards = mainGame->dField.select_min; state.pending.max_cards = mainGame->dField.select_max; state.pending.cancel = mainGame->dField.select_cancelable;
	}
	state.pending.id = ++state.next_request; state.pending.msg = mainGame->dInfo.curMsg;
	state.pending.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(state.timeout_ms);
	state.controlling = can_dispatch;
	json snapshot = BuildState();
	json delta = state.last_state.is_null()
		? json{{"mode", "snapshot"}, {"data", snapshot}}
		: json{{"mode", "json_patch"}, {"data", json::diff(state.last_state, snapshot)}};
	json request = {{"type", "decision_request"}, {"request_id", state.pending.id}, {"revision", ++state.revision},
		{"summary", std::string("请为我方") + MessageName(mainGame->dInfo.curMsg) + "，只能从下列合法选项中选择。"}, {"state_delta", delta}, {"decision", decision}};
	state.last_state = std::move(snapshot);
	Log({{"direction", can_dispatch ? "out" : "local"}, {"message", request}});
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
	{
		std::lock_guard<std::mutex> lock(state.mutex);
		if(state.pending.id && std::chrono::steady_clock::now() > state.pending.deadline) { Log({{"event","timeout"},{"request_id",state.pending.id}}); state.pending = {}; state.controlling = false; }
		if(state.incoming.empty()) return;
		reply = std::move(state.incoming.front()); state.incoming.pop_front(); pending = state.pending;
		if(reply.value("type", "") == "hello_ack") { state.handshaken = true; return; }
	}
	Log({{"direction", "in"}, {"message", reply}});
	if(reply.value("type", "") != "action" || reply.value("request_id", uint64_t{}) != pending.id || pending.id == 0 || mainGame->dInfo.curMsg != pending.msg) return;
	auto action = reply.value("action", json::object()); auto kind = action.value("kind", "");
	bool valid = false;
	if(kind == "integer") { int value = action.value("value", INT32_MIN); valid = pending.integers.count(value) != 0; if(valid) DuelClient::SetResponseI(value); }
	else if(kind == "cancel" && pending.cancel) { valid = true; DuelClient::SetResponseI(-1); }
	else if(kind == "cards" && action.contains("indices") && action["indices"].is_array()) {
		auto indices = action["indices"].get<std::vector<int>>(); std::unordered_set<int> unique(indices.begin(), indices.end());
		valid = indices.size() == unique.size() && int(indices.size()) >= pending.min_cards && int(indices.size()) <= pending.max_cards;
		for(int index : indices) valid = valid && index >= 0 && index < int(pending.card_sequences.size());
		if(valid) { std::vector<unsigned char> buffer{static_cast<unsigned char>(indices.size())}; for(int index : indices) buffer.push_back(static_cast<unsigned char>(pending.card_sequences[index])); DuelClient::SetResponseB(buffer.data(), buffer.size()); }
	}
	{
		std::lock_guard<std::mutex> lock(state.mutex); state.pending = {}; state.controlling = false;
	}
	if(valid) DuelClient::SendResponse(); else Log({{"event", "invalid_action"}, {"reply", reply}});
}
}
