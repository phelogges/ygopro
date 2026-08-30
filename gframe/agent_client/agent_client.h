#ifndef YGOPRO_AGENT_CLIENT_H
#define YGOPRO_AGENT_CLIENT_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "agent_protocol.h"

namespace ygo {

struct AgentObservedCard {
	uint32_t code{};
	int player{};
	uint32_t location{};
	uint32_t sequence{};
	uint32_t position{};
	uint32_t sub_sequence{};
};

// Keeps remote AI I/O separate from the duel protocol and GUI code.  All
// methods which touch the field are called by the client/main threads only.
class AgentClient {
public:
	static AgentClient& Instance();
	void Configure(bool enabled, std::string host, uint16_t port, int timeout_ms, std::string log_path);
	void Start();
	void Stop();
	void BeginDuel();
	void OnDecisionAvailable(const unsigned char* message, size_t length);
	void CapturePreDuelDecision(agent_protocol::Decision decision);
	void OnPreDuelDecisionSubmitted(agent_protocol::Decision decision, agent_protocol::Action action, uint8_t raw_value);
	void OnPreDuelHandResult(uint8_t self_hand, uint8_t opponent_hand);
	void OnCardMoved(uint32_t engine_code, uint32_t observed_code, agent_protocol::CardIdProvenance id_provenance,
		int previous_player, uint32_t previous_location, uint32_t previous_sequence,
		uint32_t previous_position, int player, uint32_t location, uint32_t sequence, uint32_t position, uint32_t reason);
	void OnChainAdded(uint32_t code, int player, uint32_t location, uint32_t sequence, uint32_t description, uint32_t chain_index);
	void OnChainSolving(uint32_t chain_index);
	void OnChainResolved(uint32_t chain_index);
	void OnChainEnded();
	void OnChainStatus(uint32_t chain_index, bool disabled);
	void OnSummonAttempted(uint32_t code, int player, uint32_t location, uint32_t sequence, uint32_t position,
		agent_protocol::SummonType summon_type);
	void OnLifePointsChanged(int player, int before, int after, agent_protocol::LifePointChange change_kind);
	void OnCardsDrawn(int player, const uint32_t* codes, size_t count);
	void OnHiddenZoneShuffled(int player, agent_protocol::Zone zone);
	void OnEngineHint(uint8_t hint_type, int player, uint32_t data);
	void OnCardsConfirmed(agent_protocol::CardObservationKind kind, int context_player, bool skip_panel,
		const std::vector<AgentObservedCard>& cards);
	void OnCardsIndicated(const std::vector<AgentObservedCard>& cards);
	void OnCardRelationChanged(agent_protocol::CardRelation relation, const AgentObservedCard& source,
		const AgentObservedCard& target, bool added);
	void OnTurnStarted(int player, uint32_t turn);
	void OnPhaseChanged(uint16_t raw_phase);
	void OnAttackDeclared(const AgentObservedCard& attacker, const AgentObservedCard* target);
	void OnBattleSnapshot(const AgentObservedCard& attacker, int attack, int defense, bool destroyed,
		const AgentObservedCard* defender, int defender_attack, int defender_defense, bool defender_destroyed);
	void OnAttackDisabled();
	void OnDecisionSubmitted(const uint8_t* response, size_t length);
	void OnSurrenderRequested();
	void OnSummonSucceeded(agent_protocol::SummonType summon_type);
	void OnDuelEnded(agent_protocol::DuelWinner winner, uint8_t raw_winner, uint8_t reason);
	void Poll();
	bool IsControlling() const;
};

}
#endif
