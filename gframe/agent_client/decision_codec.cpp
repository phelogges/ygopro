#include "decision_codec.h"
#include "../network.h"
#include "../../ocgcore/common.h"

#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>
#include <utility>

namespace ygo::agent_client {
using Json = nlohmann::json;

struct Candidate {
	std::string id;
	std::string kind;
	std::uint32_t value{};
	std::uint32_t parameter{};
	std::uint8_t controller{}, location{}, sequence{};
	bool mandatory{};
};
struct DecisionData {
	Json prompt;
	std::vector<Candidate> candidates;
	std::set<std::uint32_t> allowed_card_ids;
	DecisionSource source{};
	std::uint8_t message{};
	std::optional<std::uint8_t> player;
	std::uint32_t minimum{}, maximum{}, target{}, mode{}, mandatory_count{};
	bool cancelable{}, finishable{};
};

namespace {
class CodecFailure : public std::runtime_error {
public:
	CodecFailure(std::string code, const std::string& message)
		: std::runtime_error(message), code_(std::move(code)) {}
	const std::string& code() const { return code_; }
private:
	std::string code_;
};
[[noreturn]] void malformed(const std::string& message) { throw CodecFailure("malformed_prompt", message); }
[[noreturn]] void invalid(const std::string& message) { throw CodecFailure("invalid_action", message); }
[[noreturn]] void unsupported(const std::string& message) { throw CodecFailure("unsupported_prompt", message); }
class Reader {
public:
	Reader(const std::uint8_t* bytes, std::size_t length) : bytes_(bytes), length_(length) {}
	std::uint32_t read(std::size_t width) {
		if(width > length_ - offset_) malformed("决策消息被截断");
		std::uint32_t value{};
		for(std::size_t i = 0; i < width; ++i) value |= std::uint32_t(bytes_[offset_++]) << (8 * i);
		return value;
	}
	std::uint8_t u8() { return static_cast<std::uint8_t>(read(1)); }
	std::uint16_t u16() { return static_cast<std::uint16_t>(read(2)); }
	std::uint32_t u32() { return read(4); }
	bool flag() { return u8() != 0; }
	void finish() const { if(offset_ != length_) malformed("决策消息包含尾随字节"); }
private:
	const std::uint8_t* bytes_;
	std::size_t length_{}, offset_{};
};
std::string location_name(std::uint8_t location) {
	switch(location & ~LOCATION_OVERLAY) {
	case LOCATION_DECK: return "deck";
	case LOCATION_HAND: return "hand";
	case LOCATION_MZONE: return "monster";
	case LOCATION_SZONE: return "spell";
	case LOCATION_GRAVE: return "graveyard";
	case LOCATION_REMOVED: return "banished";
	case LOCATION_EXTRA: return "extra";
	case 0: if(location == LOCATION_OVERLAY) return "overlay"; break;
	}
	malformed("未知卡片区域");
}
void init(DecisionData& data, const std::string& kind, const std::string& description) {
	data.prompt = {{"kind", kind}, {"description", description}, {"candidates", Json::array()}, {"constraints", Json::object()}};
}
void add(DecisionData& data, Candidate candidate, const std::string& description, Json extra = Json::object()) {
	candidate.id = "c" + std::to_string(data.candidates.size());
	extra["id"] = candidate.id;
	extra["kind"] = candidate.kind;
	extra["description"] = description;
	data.prompt["candidates"].push_back(std::move(extra));
	data.candidates.push_back(std::move(candidate));
}
void simple(DecisionData& data, const std::string& kind, std::uint32_t value, const std::string& description) {
	Candidate candidate;
	candidate.kind = kind;
	candidate.value = value;
	add(data, candidate, description);
}
void card(Reader& reader, DecisionData& data, const std::string& kind, std::uint32_t value,
	bool fourth_byte, bool description, bool tribute, bool sum, bool counter, bool mandatory = false) {
	const auto code = reader.u32();
	Candidate candidate;
	candidate.kind = kind;
	candidate.value = value;
	candidate.controller = reader.u8();
	candidate.location = reader.u8();
	candidate.sequence = reader.u8();
	candidate.mandatory = mandatory;
	if(candidate.controller > 1) malformed("卡片控制者越界");
	Json info = {{"instance_id", "candidate-" + std::to_string(data.candidates.size())},
		{"controller", candidate.controller}, {"location", location_name(candidate.location)}, {"sequence", candidate.sequence}};
	if(code & 0x7fffffffU) info["card_id"] = code & 0x7fffffffU;
	if(fourth_byte) {
		const auto sub = reader.u8();
		if(candidate.location & LOCATION_OVERLAY) { info["location"] = "overlay"; info["overlay_sequence"] = sub; }
		else if(sub != 0) info["position"] = sub;
	}
	Json extra = {{"card", std::move(info)}};
	if(description) extra["description_id"] = reader.u32();
	if(tribute) { candidate.parameter = reader.u8(); extra["weight"] = candidate.parameter; }
	if(sum) {
		candidate.parameter = reader.u32();
		std::uint32_t low = candidate.parameter & 0xffffU, high = candidate.parameter >> 16;
		if(high & 0x8000U) { low = candidate.parameter & 0x7fffffffU; high = 0; }
		extra["value_options"] = Json::array({low});
		if(high != 0 && high != low) extra["value_options"].push_back(high);
		extra["mandatory"] = mandatory;
	}
	if(counter) { candidate.parameter = reader.u16(); extra["max_count"] = candidate.parameter; }
	add(data, candidate, mandatory ? "必选素材" : "选择候选卡片", std::move(extra));
}
void read_cards(Reader& reader, DecisionData& data, const std::string& kind, std::uint32_t command,
	bool fourth = false, bool description = false, bool tribute = false, bool sum = false, bool counter = false, bool mandatory = false) {
	const auto count = reader.u8();
	for(std::uint32_t i = 0; i < count; ++i) {
		const auto value = command == UINT32_MAX ? i : ((i << 16) | command);
		card(reader, data, kind, value, fourth, description, tribute, sum, counter, mandatory);
	}
}
void player(Reader& reader, DecisionData& data) {
	const auto value = reader.u8();
	if(value > 1) malformed("选择玩家越界");
	data.player = value;
}
void rps(DecisionData& data) {
	init(data, "rock_paper_scissors", "请选择石头、剪刀或布");
	simple(data, "rock", 2, "石头"); simple(data, "scissors", 1, "剪刀"); simple(data, "paper", 3, "布");
}
std::shared_ptr<DecisionData> parse(const std::uint8_t* bytes, std::size_t length, DecisionSource source,
	const std::vector<std::uint32_t>* allowed_card_ids) {
	if(length > SIZE_NETWORK_BUFFER || (length != 0 && bytes == nullptr)) malformed("决策消息大小或指针无效");
	auto data = std::make_shared<DecisionData>();
	data->source = source;
	if(source != DecisionSource::game_message) {
		if(length != 0) malformed("赛前决策应无载荷");
		if(source == DecisionSource::select_hand) rps(*data);
		else if(source == DecisionSource::select_turn_player) {
			init(*data, "first_player", "请选择先攻或后攻");
			simple(*data, "go_first", 1, "先攻"); simple(*data, "go_second", 0, "后攻");
		} else unsupported("未知决策来源");
		return data;
	}
	Reader reader(bytes, length);
	data->message = reader.u8();
	auto& d = *data;
	switch(d.message) {
	case MSG_SELECT_IDLECMD: {
		init(d, "idle_command", "请选择当前操作"); player(reader, d);
		const char* kinds[] = {"normal_summon", "special_summon", "change_position", "set_monster", "set_spell_trap", "activate"};
		for(std::uint32_t i = 0; i < 6; ++i) read_cards(reader, d, kinds[i], i, false, i == 5);
		if(reader.flag()) simple(d, "battle_phase", 6, "进入战斗阶段");
		if(reader.flag()) simple(d, "end_turn", 7, "结束回合");
		if(reader.flag()) simple(d, "shuffle_hand", 8, "洗切手牌");
		break;
	}
	case MSG_SELECT_BATTLECMD: {
		init(d, "battle_command", "请选择战斗阶段操作"); player(reader, d);
		read_cards(reader, d, "activate", 0, false, true);
		const auto count = reader.u8();
		for(std::uint32_t i = 0; i < count; ++i) {
			card(reader, d, "attack", (i << 16) | 1, false, false, false, false, false);
			d.prompt["candidates"].back()["direct_attackable"] = reader.flag();
		}
		if(reader.flag()) simple(d, "main_phase_2", 2, "进入主要阶段二");
		if(reader.flag()) simple(d, "end_turn", 3, "结束回合");
		break;
	}
	case MSG_SELECT_EFFECTYN:
	case MSG_SELECT_YESNO: {
		init(d, d.message == MSG_SELECT_EFFECTYN ? "effect_yes_no" : "yes_no", "请选择是否接受"); player(reader, d);
		if(d.message == MSG_SELECT_EFFECTYN) {
			card(reader, d, "accept", 1, true, true, false, false, false);
			d.prompt["candidates"].back()["description"] = "接受";
		} else { d.prompt["description_id"] = reader.u32(); simple(d, "accept", 1, "接受"); }
		simple(d, "decline", 0, "拒绝");
		break;
	}
	case MSG_SELECT_OPTION:
	case MSG_ANNOUNCE_NUMBER: {
		init(d, d.message == MSG_SELECT_OPTION ? "option" : "announce_number", "请选择选项"); player(reader, d);
		const auto count = reader.u8();
		for(std::uint32_t i = 0; i < count; ++i) {
			const auto value = reader.u32();
			simple(d, "option", i, d.message == MSG_SELECT_OPTION ? "选择选项" : "宣言数字 " + std::to_string(value));
			d.prompt["candidates"].back()[d.message == MSG_SELECT_OPTION ? "description_id" : "number"] = value;
		}
		break;
	}
	case MSG_SELECT_CARD:
	case MSG_SELECT_TRIBUTE: {
		const bool tribute = d.message == MSG_SELECT_TRIBUTE;
		init(d, tribute ? "tribute" : "select_cards", tribute ? "请选择解放卡片" : "请选择卡片"); player(reader, d);
		d.cancelable = reader.flag(); d.minimum = reader.u8(); d.maximum = reader.u8();
		read_cards(reader, d, "card", UINT32_MAX, !tribute, false, tribute);
		if(d.minimum > d.maximum || (!tribute && d.maximum > d.candidates.size())) malformed("选卡数量约束无效");
		d.prompt["constraints"] = {{"min_count", tribute ? 0 : d.minimum}, {"max_count", d.maximum}, {"cancelable", d.cancelable}};
		if(tribute) {
			std::uint32_t weight{}; for(const auto& c : d.candidates) weight += c.parameter;
			d.prompt["constraints"]["min_weight"] = d.minimum;
			d.prompt["constraints"]["max_weight"] = weight;
		}
		if(d.cancelable) simple(d, "cancel", UINT32_MAX, "取消选择");
		break;
	}
	case MSG_SELECT_UNSELECT_CARD: {
		init(d, "select_unselect_card", "请选择或撤销一张卡片"); player(reader, d);
		d.finishable = reader.flag(); d.cancelable = reader.flag(); d.minimum = reader.u8(); d.maximum = reader.u8();
		read_cards(reader, d, "select", UINT32_MAX, true);
		const auto offset = d.candidates.size(); read_cards(reader, d, "unselect", UINT32_MAX, true);
		for(std::size_t i = offset; i < d.candidates.size(); ++i) d.candidates[i].value += static_cast<std::uint32_t>(offset);
		if(d.candidates.size() > 256 || d.minimum > d.maximum) malformed("单步选卡约束无效");
		d.prompt["constraints"] = {{"cancelable", d.cancelable || d.finishable}};
		d.prompt["finishable"] = d.finishable; d.prompt["min_count"] = d.minimum; d.prompt["max_count"] = d.maximum;
		if(d.finishable) simple(d, "finish", UINT32_MAX, "完成选择");
		if(d.cancelable) simple(d, "cancel", UINT32_MAX, "取消选择");
		break;
	}
	case MSG_SELECT_CHAIN: {
		init(d, "chain", "请选择发动效果或放弃连锁"); player(reader, d);
		const auto count = reader.u8(); d.prompt["special_count"] = reader.u8();
		d.prompt["hint_timing"] = Json::array({reader.u32(), reader.u32()});
		bool forced = false;
		for(std::uint32_t i = 0; i < count; ++i) {
			const auto flag = reader.u8(); const auto mandatory = reader.flag(); forced = forced || mandatory;
			card(reader, d, "activate", i, true, true, false, false, false);
			d.prompt["candidates"].back()["effect_flag"] = flag;
			d.prompt["candidates"].back()["forced"] = mandatory;
		}
		d.cancelable = !forced; d.prompt["forced"] = forced; d.prompt["constraints"]["cancelable"] = !forced;
		if(!forced) simple(d, "pass", UINT32_MAX, "放弃连锁");
		break;
	}
	case MSG_SELECT_PLACE:
	case MSG_SELECT_DISFIELD: {
		init(d, d.message == MSG_SELECT_PLACE ? "select_place" : "disfield", "请选择区域"); player(reader, d);
		d.target = reader.u8(); const auto forbidden = reader.u32();
		if(d.target == 0) d.prompt["constraints"] = {{"min_count", 0}, {"max_count", 1}, {"cancelable", true}};
		else d.prompt["constraints"] = {{"count", d.target}, {"cancelable", false}};
		for(unsigned bit = 0; bit < 32; ++bit) {
			const unsigned local = bit % 16, sequence = local % 8;
			const bool monster = local < 8;
			if((forbidden & (std::uint32_t{1} << bit)) || (monster && sequence > 6)) continue;
			Candidate candidate; candidate.kind = "place"; candidate.value = bit;
			candidate.controller = static_cast<std::uint8_t>(*d.player ^ (bit >= 16 ? 1 : 0));
			candidate.location = monster ? LOCATION_MZONE : LOCATION_SZONE;
			candidate.sequence = static_cast<std::uint8_t>(sequence);
			add(d, candidate, "选择区域", {{"controller", candidate.controller}, {"location", location_name(candidate.location)}, {"sequence", sequence}});
		}
		if(d.target > d.candidates.size()) malformed("区域选择数量超过候选数量");
		break;
	}
	case MSG_SELECT_POSITION: {
		init(d, "position", "请选择表示形式"); player(reader, d);
		const auto code = reader.u32(); const auto allowed = reader.u8();
		if(allowed == 0 || (allowed & ~0xfU)) malformed("表示形式掩码无效");
		const char* kinds[] = {"face_up_attack", "face_down_attack", "face_up_defense", "face_down_defense"};
		const char* descriptions[] = {"表侧攻击", "里侧攻击", "表侧守备", "里侧守备"};
		for(unsigned i = 0; i < 4; ++i) if(allowed & (1U << i)) simple(d, kinds[i], 1U << i, descriptions[i]);
		if(code) d.prompt["card_id"] = code;
		break;
	}
	case MSG_SELECT_COUNTER: {
		init(d, "select_counter", "请分配移除的指示物数量"); player(reader, d);
		d.prompt["counter_type"] = reader.u16(); d.target = reader.u16();
		read_cards(reader, d, "card", UINT32_MAX, false, false, false, false, true);
		d.prompt["constraints"]["total_count"] = d.target;
		if(d.candidates.size() * 2 > SIZE_RETURN_VALUE) unsupported("指示物响应超过引擎缓冲区");
		break;
	}
	case MSG_SELECT_SUM: {
		init(d, "sum", "请选择合计素材"); d.mode = reader.u8(); player(reader, d);
		if(d.mode > 1) malformed("SUM 模式无效");
		d.target = reader.u32(); d.minimum = reader.u8(); d.maximum = reader.u8();
		if(d.target > INT32_MAX || d.minimum > d.maximum) malformed("SUM 目标或数量无效");
		read_cards(reader, d, "card", UINT32_MAX, false, false, false, true, false, true);
		d.mandatory_count = static_cast<std::uint32_t>(d.candidates.size());
		read_cards(reader, d, "card", UINT32_MAX, false, false, false, true);
		d.prompt["constraints"] = {{"mode", d.mode == 0 ? "exact" : "at_least"}, {"target", d.target}, {"min_count", d.minimum + d.mandatory_count}, {"max_count", d.mode == 0 ? d.maximum + d.mandatory_count : 255}};
		break;
	}
	case MSG_SORT_CARD: {
		init(d, "sort", "请排列卡片顺序"); player(reader, d); read_cards(reader, d, "card", UINT32_MAX);
		d.prompt["constraints"]["count"] = d.candidates.size();
		simple(d, "default", UINT32_MAX, "使用默认顺序");
		break;
	}
	case MSG_ROCK_PAPER_SCISSORS: rps(d); player(reader, d); break;
	case MSG_ANNOUNCE_RACE:
	case MSG_ANNOUNCE_ATTRIB: {
		const bool race = d.message == MSG_ANNOUNCE_RACE;
		init(d, race ? "announce_race" : "announce_attribute", race ? "请选择宣言种族" : "请选择宣言属性"); player(reader, d);
		d.target = reader.u8(); const auto allowed = reader.u32();
		const unsigned bits = race ? RACES_COUNT : 7;
		if((allowed >> bits) != 0) malformed("宣言掩码含未知位");
		for(unsigned i = 0; i < bits; ++i) if(allowed & (1U << i)) {
			simple(d, race ? "race" : "attribute", 1U << i, "选择宣言项");
			d.prompt["candidates"].back()["bit"] = 1U << i;
		}
		if(d.target > d.candidates.size()) malformed("宣言数量超过允许位数");
		d.prompt["constraints"]["min_count"] = d.target;
		d.prompt["constraints"]["max_count"] = d.target;
		break;
	}
	case MSG_ANNOUNCE_CARD: {
		init(d, "announce_card", "请宣言卡片密码");
		player(reader, d); const auto count = reader.u8();
		for(unsigned i = 0; i < count; ++i) reader.u32();
		reader.finish();
		if(allowed_card_ids == nullptr || allowed_card_ids->empty())
			unsupported("卡片宣言需要当前卡库与 opcode 解析后的合法密码集合");
		if(allowed_card_ids->size() > 100000) unsupported("卡片宣言允许集合超过安全上限");
		Json ids = Json::array();
		for(const auto code : *allowed_card_ids) {
			if(code == 0) malformed("卡片宣言允许集合含无效密码");
			if(d.allowed_card_ids.insert(code).second) ids.push_back(code);
		}
		d.prompt["constraints"]["allowed_card_ids"] = std::move(ids);
		break;
	}
	default: throw CodecFailure("not_decision", "此消息不是决策提示");
	}
	reader.finish();
	return data;
}
std::uint32_t number(const Json& value, std::uint32_t maximum) {
	if(!value.is_number_integer()) invalid("动作数量必须是整数");
	if(value.is_number_unsigned()) { const auto n = value.get<std::uint64_t>(); if(n > maximum) invalid("动作数量越界"); return static_cast<std::uint32_t>(n); }
	const auto n = value.get<std::int64_t>(); if(n < 0 || static_cast<std::uint64_t>(n) > maximum) invalid("动作数量越界");
	return static_cast<std::uint32_t>(n);
}
const Candidate& candidate(const DecisionData& d, const Json& id) {
	if(!id.is_string()) invalid("候选 ID 必须是字符串");
	const auto value = id.get<std::string>();
	const auto found = std::find_if(d.candidates.begin(), d.candidates.end(), [&](const auto& c) { return c.id == value; });
	if(found == d.candidates.end()) invalid("候选 ID 不属于当前提示");
	return *found;
}
void fields(const Json& action, std::initializer_list<const char*> allowed) {
	if(!action.is_object()) invalid("动作必须是对象");
	for(auto it = action.begin(); it != action.end(); ++it) {
		if(std::find(allowed.begin(), allowed.end(), it.key()) == allowed.end()) invalid("动作含未定义字段");
	}
}
std::vector<const Candidate*> selected(const DecisionData& d, const Json& ids) {
	if(!ids.is_array() || ids.size() > 255) invalid("候选 ID 数组大小无效");
	std::set<std::string> unique;
	std::vector<const Candidate*> result;
	for(const auto& id : ids) {
		const auto& c = candidate(d, id);
		if(!unique.insert(c.id).second) invalid("候选 ID 重复");
		result.push_back(&c);
	}
	return result;
}
std::pair<std::uint32_t, std::uint32_t> sum_values(const Candidate& c) {
	if(c.parameter & 0x80000000U) return {c.parameter & 0x7fffffffU, 0};
	return {c.parameter & 0xffffU, c.parameter >> 16};
}
void validate_sum(const DecisionData& d, const std::vector<const Candidate*>& cards) {
	std::vector<const Candidate*> all;
	for(std::size_t i = 0; i < d.mandatory_count; ++i) all.push_back(&d.candidates[i]);
	std::set<std::string> mandatory;
	for(const auto* c : cards) {
		if(c->mandatory) mandatory.insert(c->id);
		else all.push_back(c);
	}
	if(mandatory.size() != d.mandatory_count) invalid("SUM 缺少必选素材");
	const auto optional_count = cards.size() - mandatory.size();
	if(all.empty() || all.size() > 255 || optional_count < d.minimum || (d.mode == 0 && optional_count > d.maximum)) invalid("SUM 素材数量无效");
	if(d.mode == 1) {
		std::uint64_t low_sum{}, high_sum{}, minimum = UINT32_MAX;
		for(const auto* c : all) {
			const auto values = sum_values(*c); const auto low = values.second ? std::min(values.first, values.second) : values.first;
			low_sum += low; high_sum += std::max(values.first, values.second); minimum = std::min<std::uint64_t>(minimum, low);
		}
		if(high_sum < d.target || low_sum - minimum >= d.target) invalid("SUM 至少和或最少素材约束不成立");
		return;
	}
	// Sparse bounded DP avoids exponential dual-value recursion and integer overflow.
	std::set<std::uint32_t> sums{0};
	std::size_t work{};
	for(const auto* c : all) {
		const auto values = sum_values(*c); std::set<std::uint32_t> next;
		for(const auto total : sums) {
			for(const auto value : {values.first, values.second}) {
				if(++work > 1000000) unsupported("SUM 校验复杂度超过安全上限");
				if(value == 0) continue;
				if(value <= d.target && total <= d.target - value) next.insert(total + value);
			}
		}
		sums = std::move(next);
	}
	if(sums.count(d.target) == 0) invalid("SUM 素材不能达到精确目标");
}
EncodedResponse integer(std::uint32_t value) {
	EncodedResponse response{CTOS_RESPONSE, {}};
	for(unsigned i = 0; i < 4; ++i) response.payload.push_back(static_cast<std::uint8_t>(value >> (i * 8)));
	return response;
}
EncodedResponse encode(const DecisionData& d, const Json& action) {
	if(!action.is_object() || !action.contains("kind") || !action["kind"].is_string()) invalid("动作缺少 kind");
	const auto kind = action["kind"].get<std::string>();
	if(kind == "announce_card") {
		fields(action, {"kind", "card_id"});
		if(d.message != MSG_ANNOUNCE_CARD) invalid("此提示不接受卡片宣言");
		const auto code = number(action.at("card_id"), UINT32_MAX);
		if(d.allowed_card_ids.count(code) == 0) invalid("宣言卡片不属于当前提示允许集合");
		return integer(code);
	}
	if(kind == "choice" || kind == "select_step") {
		fields(action, {"kind", "candidate_id"}); const auto& c = candidate(d, action.at("candidate_id"));
		const bool step = d.message == MSG_SELECT_UNSELECT_CARD;
		if(step != (kind == "select_step") && !(step && kind == "choice" && (c.kind == "finish" || c.kind == "cancel"))) invalid("动作类型不适用于当前提示");
		if(d.source == DecisionSource::select_hand) return {CTOS_HAND_RESULT, {static_cast<std::uint8_t>(c.value)}};
		if(d.source == DecisionSource::select_turn_player) return {CTOS_TP_RESULT, {static_cast<std::uint8_t>(c.value)}};
		if(step) {
			if(c.kind == "finish" || c.kind == "cancel") return integer(UINT32_MAX);
			return {CTOS_RESPONSE, {1, static_cast<std::uint8_t>(c.value)}};
		}
		switch(d.message) {
		case MSG_SELECT_CARD: case MSG_SELECT_TRIBUTE: case MSG_SORT_CARD:
			if(c.kind != "cancel" && c.kind != "default") invalid("当前提示需要组合选择动作"); break;
		case MSG_SELECT_SUM: case MSG_SELECT_COUNTER: case MSG_SELECT_PLACE: case MSG_SELECT_DISFIELD:
		case MSG_ANNOUNCE_RACE: case MSG_ANNOUNCE_ATTRIB: invalid("当前提示需要组合选择动作");
		default: break;
		}
		return integer(c.value);
	}
	if(kind == "select_cards") {
		fields(action, {"kind", "candidate_ids"}); const auto cards = selected(d, action.at("candidate_ids"));
		if(d.message == MSG_ANNOUNCE_RACE || d.message == MSG_ANNOUNCE_ATTRIB) {
			if(cards.size() != d.target) invalid("宣言选择数不正确");
			std::uint32_t mask{}; for(const auto* c : cards) mask |= c->value;
			return integer(mask);
		}
		for(const auto* c : cards) if(c->kind != "card") invalid("组合选择中包含非卡片候选");
		if(d.message == MSG_SORT_CARD) {
			const auto count = d.candidates.size() - 1;
			if(cards.size() != count) invalid("排序必须覆盖全部卡片");
			EncodedResponse response{CTOS_RESPONSE, std::vector<std::uint8_t>(count)};
			for(std::size_t i = 0; i < cards.size(); ++i) response.payload[cards[i]->value] = static_cast<std::uint8_t>(i);
			return response;
		}
		if(d.message == MSG_SELECT_CARD) {
			if(cards.size() < d.minimum || cards.size() > d.maximum) invalid("选卡数量不符合约束");
		} else if(d.message == MSG_SELECT_TRIBUTE) {
			std::uint32_t weight{}; for(const auto* c : cards) weight += c->parameter;
			if(cards.size() > d.maximum || weight < d.minimum) invalid("解放数量或权重不符合约束");
		} else if(d.message == MSG_SELECT_SUM) validate_sum(d, cards);
		else invalid("此提示不接受 select_cards");
		const auto mandatory = d.message == MSG_SELECT_SUM ? d.mandatory_count : 0;
		const auto count = cards.size();
		if(count > 255) invalid("响应数量超过协议范围");
		EncodedResponse response{CTOS_RESPONSE, {static_cast<std::uint8_t>(count)}};
		for(std::uint32_t i = 0; i < mandatory; ++i) response.payload.push_back(0);
		for(const auto* c : cards) if(!c->mandatory) response.payload.push_back(static_cast<std::uint8_t>(c->value));
		return response;
	}
	if(kind == "distribute_counters") {
		fields(action, {"kind", "allocations"});
		if(d.message != MSG_SELECT_COUNTER) invalid("此提示不接受指示物分配");
		const auto& entries = action.at("allocations");
		if(!entries.is_array() || entries.size() > d.candidates.size()) invalid("指示物分配数组无效");
		std::vector<std::uint16_t> values(d.candidates.size()); std::set<std::string> seen; std::uint32_t total{};
		for(const auto& entry : entries) {
			fields(entry, {"candidate_id", "count"}); const auto& c = candidate(d, entry.at("candidate_id"));
			if(!seen.insert(c.id).second) invalid("指示物分配候选重复");
			const auto count = number(entry.at("count"), c.parameter); values[c.value] = static_cast<std::uint16_t>(count); total += count;
		}
		if(total != d.target) invalid("指示物总数不符合约束");
		EncodedResponse response{CTOS_RESPONSE, {}};
		for(const auto value : values) { response.payload.push_back(static_cast<std::uint8_t>(value)); response.payload.push_back(static_cast<std::uint8_t>(value >> 8)); }
		return response;
	}
	if(kind == "select_places") {
		fields(action, {"kind", "places"});
		if(d.message != MSG_SELECT_PLACE && d.message != MSG_SELECT_DISFIELD) invalid("此提示不接受区域选择");
		const auto& places = action.at("places");
		if(!places.is_array() || (d.target != 0 && places.size() != d.target) || (d.target == 0 && places.size() > 1)) invalid("区域选择数量不正确");
		if(d.target == 0 && places.empty()) return {CTOS_RESPONSE, {*d.player, 0, 0}};
		std::uint32_t used{}; EncodedResponse response{CTOS_RESPONSE, {}};
		for(const auto& place : places) {
			fields(place, {"controller", "location", "sequence"});
			const auto control = number(place.at("controller"), 1), sequence = number(place.at("sequence"), 7);
			if(!place.at("location").is_string()) invalid("区域名称无效");
			const auto location = place.at("location").get<std::string>();
			const auto found = std::find_if(d.candidates.begin(), d.candidates.end(), [&](const auto& c) {
				return c.controller == control && c.sequence == sequence && location_name(c.location) == location;
			});
			if(found == d.candidates.end()) invalid("区域不属于允许候选");
			std::uint32_t bit = std::uint32_t{1} << found->value;
			// Both representations address the same physical Extra Monster Zone.
			if(bit & (1U << 22)) bit |= 1U << 5;
			if(bit & (1U << 21)) bit |= 1U << 6;
			if(bit & (1U << 5)) bit |= 1U << 22;
			if(bit & (1U << 6)) bit |= 1U << 21;
			if(used & bit) invalid("区域重复或共享额外怪兽区域冲突");
			used |= bit;
			response.payload.insert(response.payload.end(), {found->controller, found->location, found->sequence});
		}
		return response;
	}
	invalid("未知语义动作类型");
}

Json decode(const DecisionData& d, std::uint8_t packet_type, const std::uint8_t* payload, std::size_t length) {
	if(length > UINT8_MAX || (length != 0 && payload == nullptr))
		invalid("响应大小或指针无效");
	const auto matches = [&](const Json& action) {
		try {
			const auto response = encode(d, action);
			return response.packet_type == packet_type && response.payload.size() == length &&
			       std::equal(response.payload.begin(), response.payload.end(), payload);
		} catch(const CodecFailure&) {
			return false;
		}
	};
	std::optional<Json> found;
	const auto accept = [&](Json action) {
		if(!matches(action))
			return;
		if(found && *found != action)
			throw CodecFailure("ambiguous_response", "响应对应多个合法动作");
		found = std::move(action);
	};
	for(const auto& c : d.candidates) {
		const auto kind = d.message == MSG_SELECT_UNSELECT_CARD && c.kind != "finish" && c.kind != "cancel"
		                      ? "select_step"
		                      : "choice";
		accept({{"kind", kind}, {"candidate_id", c.id}});
	}
	if(packet_type == CTOS_RESPONSE && d.message == MSG_ANNOUNCE_CARD && length == 4) {
		std::uint32_t code{};
		for(unsigned i = 0; i < 4; ++i)
			code |= std::uint32_t(payload[i]) << (8 * i);
		accept({{"kind", "announce_card"}, {"card_id", code}});
	}
	if(packet_type == CTOS_RESPONSE &&
	   (d.message == MSG_SELECT_CARD || d.message == MSG_SELECT_TRIBUTE || d.message == MSG_SELECT_SUM) && length > 0) {
		const auto count = payload[0];
		if(length == std::size_t(count) + 1) {
			Json ids = Json::array();
			std::size_t start = 1;
			if(d.message == MSG_SELECT_SUM && count >= d.mandatory_count && length > d.mandatory_count) {
				bool placeholders = true;
				for(std::size_t i = 0; i < d.mandatory_count; ++i)
					placeholders &= payload[1 + i] == 0;
				if(placeholders) {
					for(std::size_t i = 0; i < d.mandatory_count; ++i)
						ids.push_back(d.candidates[i].id);
					start += d.mandatory_count;
				}
			}
			for(std::size_t i = start; i < length; ++i) {
				const auto index = std::size_t(payload[i]) + (d.message == MSG_SELECT_SUM ? d.mandatory_count : 0);
				if(index >= d.candidates.size()) {
					ids = nullptr;
					break;
				}
				ids.push_back(d.candidates[index].id);
			}
			if(ids.is_array())
				accept({{"kind", "select_cards"}, {"candidate_ids", std::move(ids)}});
		}
	}
	if(packet_type == CTOS_RESPONSE && d.message == MSG_SORT_CARD && length + 1 == d.candidates.size()) {
		Json ids = Json::array();
		std::vector<bool> used(length);
		for(std::size_t rank = 0; rank < length; ++rank) {
			std::size_t index{};
			for(; index < length && payload[index] != rank; ++index) {
			}
			if(index == length || used[index]) {
				ids = nullptr;
				break;
			}
			used[index] = true;
			ids.push_back(d.candidates[index].id);
		}
		if(ids.is_array())
			accept({{"kind", "select_cards"}, {"candidate_ids", std::move(ids)}});
	}
	if(packet_type == CTOS_RESPONSE && (d.message == MSG_ANNOUNCE_RACE || d.message == MSG_ANNOUNCE_ATTRIB) &&
	   length == 4) {
		std::uint32_t mask{};
		for(unsigned i = 0; i < 4; ++i)
			mask |= std::uint32_t(payload[i]) << (8 * i);
		Json ids = Json::array();
		for(const auto& c : d.candidates)
			if(mask & c.value)
				ids.push_back(c.id);
		accept({{"kind", "select_cards"}, {"candidate_ids", std::move(ids)}});
	}
	if(packet_type == CTOS_RESPONSE && d.message == MSG_SELECT_COUNTER && length == d.candidates.size() * 2) {
		Json allocations = Json::array();
		for(std::size_t i = 0; i < d.candidates.size(); ++i) {
			const auto count = std::uint32_t(payload[2 * i]) | (std::uint32_t(payload[2 * i + 1]) << 8);
			if(count)
				allocations.push_back({{"candidate_id", d.candidates[i].id}, {"count", count}});
		}
		accept({{"kind", "distribute_counters"}, {"allocations", std::move(allocations)}});
	}
	if(packet_type == CTOS_RESPONSE && (d.message == MSG_SELECT_PLACE || d.message == MSG_SELECT_DISFIELD) &&
	   length % 3 == 0) {
		Json places = Json::array();
		bool known = true;
		for(std::size_t i = 0; i < length; i += 3) {
			const auto found_place = std::find_if(d.candidates.begin(), d.candidates.end(), [&](const auto& c) {
				return c.controller == payload[i] && c.location == payload[i + 1] && c.sequence == payload[i + 2];
			});
			if(found_place == d.candidates.end()) {
				known = false;
				break;
			}
			places.push_back({{"controller", found_place->controller},
			                  {"location", location_name(found_place->location)},
			                  {"sequence", found_place->sequence}});
		}
		if(known)
			accept({{"kind", "select_places"}, {"places", std::move(places)}});
	}
	if(packet_type == CTOS_RESPONSE && (d.message == MSG_SELECT_PLACE || d.message == MSG_SELECT_DISFIELD) &&
	   length == 3 && d.target == 0 && payload[0] == *d.player && payload[1] == 0 && payload[2] == 0)
		accept({{"kind", "select_places"}, {"places", Json::array()}});
	if(!found)
		invalid("响应不属于当前提示的合法动作");
	return *found;
}
} // namespace

DecisionPrompt::DecisionPrompt(std::shared_ptr<const DecisionData> data) : data_(std::move(data)) {}
const Json& DecisionPrompt::prompt() const { return data_->prompt; }
std::uint8_t DecisionPrompt::message_type() const { return data_->message; }
std::optional<std::uint8_t> DecisionPrompt::selecting_player() const { return data_->player; }
ParseDecisionResult ParseDecision(const std::uint8_t* bytes, std::size_t length, DecisionSource source,
	const std::vector<std::uint32_t>* allowed_card_ids) {
	try { return {DecisionPrompt(parse(bytes, length, source, allowed_card_ids)), {}}; }
	catch(const CodecFailure& error) { return {std::nullopt, {error.code(), error.what()}}; }
}
EncodeDecisionResult EncodeDecision(const DecisionPrompt& prompt, const Json& action) {
	try {
		auto response = encode(*prompt.data_, action);
		if(response.payload.size() > UINT8_MAX) invalid("动作响应超过客户端发送长度上限");
		return {std::move(response), {}};
	} catch(const CodecFailure& error) { return {std::nullopt, {error.code(), error.what()}}; }
	catch(const Json::exception&) { return {std::nullopt, {"invalid_action", "动作缺少必填字段或字段类型错误"}}; }
}
DecodeDecisionResult DecodeDecisionResponse(const DecisionPrompt& prompt, std::uint8_t packet_type,
	const std::uint8_t* payload, std::size_t length) {
	try { return {decode(*prompt.data_, packet_type, payload, length), {}}; }
	catch(const CodecFailure& error) { return {std::nullopt, {error.code(), error.what()}}; }
}
} // namespace ygo::agent_client
