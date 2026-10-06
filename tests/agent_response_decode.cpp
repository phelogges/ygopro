#include "gframe/agent_client/decision_codec.h"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

std::uint8_t HexDigit(char value) {
	if(value >= '0' && value <= '9') return static_cast<std::uint8_t>(value - '0');
	if(value >= 'a' && value <= 'f') return static_cast<std::uint8_t>(value - 'a' + 10);
	if(value >= 'A' && value <= 'F') return static_cast<std::uint8_t>(value - 'A' + 10);
	throw std::invalid_argument("invalid hex digit");
}

std::vector<std::uint8_t> DecodeHex(const std::string& value) {
	if(value.size() % 2 != 0) throw std::invalid_argument("odd hex length");
	std::vector<std::uint8_t> result;
	result.reserve(value.size() / 2);
	for(std::size_t i = 0; i < value.size(); i += 2)
		result.push_back(static_cast<std::uint8_t>((HexDigit(value[i]) << 4) | HexDigit(value[i + 1])));
	return result;
}

nlohmann::json Decode(const nlohmann::json& request) {
	using namespace ygo::agent_client;
	const auto message = DecodeHex(request.at("message_hex").get<std::string>());
	const auto payload = DecodeHex(request.at("payload_hex").get<std::string>());
	const auto source_name = request.at("source").get<std::string>();
	DecisionSource source;
	if(source_name == "game_message") source = DecisionSource::game_message;
	else if(source_name == "select_hand") source = DecisionSource::select_hand;
	else if(source_name == "select_turn_player") source = DecisionSource::select_turn_player;
	else throw std::invalid_argument("unknown decision source");
	std::vector<std::uint32_t> allowed_ids;
	if(request.contains("allowed_card_ids"))
		allowed_ids = request.at("allowed_card_ids").get<std::vector<std::uint32_t>>();
	const auto parsed = ParseDecision(message.data(), message.size(), source,
		allowed_ids.empty() ? nullptr : &allowed_ids);
	if(!parsed.decision)
		return {{"error", {{"code", parsed.error.code}, {"message", parsed.error.message}}}};
	const auto decoded = DecodeDecisionResponse(*parsed.decision,
		request.at("packet_type").get<std::uint8_t>(), payload.data(), payload.size());
	if(!decoded.action)
		return {{"error", {{"code", decoded.error.code}, {"message", decoded.error.message}}}};
	return {{"action", *decoded.action}};
}

} // namespace

int main() {
	std::string line;
	while(std::getline(std::cin, line)) {
		try {
			std::cout << Decode(nlohmann::json::parse(line)).dump() << '\n';
		} catch(const std::exception& error) {
			std::cout << nlohmann::json({{"error", {{"code", "invalid_input"},
				{"message", error.what()}}}}).dump() << '\n';
		}
	}
}
