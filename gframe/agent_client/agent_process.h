#ifndef YGO_AGENT_CLIENT_AGENT_PROCESS_H
#define YGO_AGENT_CLIENT_AGENT_PROCESS_H

#include <cstdint>
#include <string>

namespace ygo::agent_client {

struct AgentProcessReady {
	std::uint16_t port = 0;
	std::string nonce;
	int decision_timeout_ms = 60000;
};

// Owns only the child it started. No shell or model credentials are passed in
// argv.
class AgentProcess final {
  public:
	AgentProcess() = default;
	~AgentProcess();
	AgentProcess(const AgentProcess &) = delete;
	AgentProcess &operator=(const AgentProcess &) = delete;

	bool Start(const std::string &executable, const std::string &profile, const std::string &token,
			   const std::string &nonce, AgentProcessReady &ready, std::string &error);
	bool Running();
	void Stop();

  private:
#if defined(_WIN32)
	void *process_ = nullptr;
#else
	int pid_ = -1;
#endif
};

} // namespace ygo::agent_client
#endif
