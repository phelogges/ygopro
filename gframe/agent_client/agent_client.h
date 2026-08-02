#ifndef YGOPRO_AGENT_CLIENT_H
#define YGOPRO_AGENT_CLIENT_H

#include <cstddef>
#include <cstdint>
#include <string>

namespace ygo {

// Keeps remote AI I/O separate from the duel protocol and GUI code.  All
// methods which touch the field are called by the client/main threads only.
class AgentClient {
public:
	static AgentClient& Instance();
	void Configure(bool enabled, std::string host, uint16_t port, int timeout_ms, std::string log_path);
	void Start();
	void Stop();
	void OnDecisionAvailable(const unsigned char* message, size_t length);
	void CapturePreDuelDecision(const char* kind);
	void Poll();
	bool IsControlling() const;
};

}
#endif
