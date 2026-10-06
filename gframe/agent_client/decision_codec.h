#ifndef YGO_AGENT_CLIENT_DECISION_CODEC_H
#define YGO_AGENT_CLIENT_DECISION_CODEC_H

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

namespace ygo::agent_client {

enum class DecisionSource { game_message, select_hand, select_turn_player };

struct DecisionError {
	std::string code;
	std::string message;
};

struct DecisionData;
struct ParseDecisionResult;
struct EncodeDecisionResult;
struct DecodeDecisionResult;

// Owns the immutable wire interpretation; JSON returned to HTTP is descriptive only.
class DecisionPrompt {
public:
	const nlohmann::json& prompt() const;
	std::uint8_t message_type() const;
	std::optional<std::uint8_t> selecting_player() const;

private:
	explicit DecisionPrompt(std::shared_ptr<const DecisionData> data);
	std::shared_ptr<const DecisionData> data_;
	friend ParseDecisionResult ParseDecision(const std::uint8_t*, std::size_t, DecisionSource,
		const std::vector<std::uint32_t>*);
	friend EncodeDecisionResult EncodeDecision(const DecisionPrompt&, const nlohmann::json&);
	friend DecodeDecisionResult DecodeDecisionResponse(const DecisionPrompt&, std::uint8_t,
		const std::uint8_t*, std::size_t);
};

struct ParseDecisionResult {
	std::optional<DecisionPrompt> decision;
	DecisionError error;
};

// packet_type is CTOS_RESPONSE / CTOS_HAND_RESULT / CTOS_TP_RESULT.
// payload excludes the packet header. Integers are encoded in protocol LE order.
struct EncodedResponse {
	std::uint8_t packet_type{};
	std::vector<std::uint8_t> payload;
};

struct EncodeDecisionResult {
	std::optional<EncodedResponse> response;
	DecisionError error;
};

struct DecodeDecisionResult {
	std::optional<nlohmann::json> action;
	DecisionError error;
};

// game_message includes MSG_* as byte zero and must contain exactly one message.
// Pre-duel sources take an empty payload (nullptr, 0 is valid).
// For ANNOUNCE_CARD only, allowed_card_ids must be resolved by the caller from
// this exact prompt's opcodes and the runtime database. The set is copied, and
// no pointer to caller data survives this call. Without a nonempty set the
// prompt is unsupported; other message types ignore this argument.
ParseDecisionResult ParseDecision(const std::uint8_t* bytes, std::size_t length,
	DecisionSource source = DecisionSource::game_message,
	const std::vector<std::uint32_t>* allowed_card_ids = nullptr);
EncodeDecisionResult EncodeDecision(const DecisionPrompt& prompt, const nlohmann::json& action);
// Reconstructs a semantic action from the response actually sent by the client.
// Fails if the bytes are malformed, illegal for this prompt, or encode more than
// one distinct candidate (for example finish and cancel both use -1).
DecodeDecisionResult DecodeDecisionResponse(const DecisionPrompt& prompt, std::uint8_t packet_type,
	const std::uint8_t* payload, std::size_t length);

} // namespace ygo::agent_client
#endif
