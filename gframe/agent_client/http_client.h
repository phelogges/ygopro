#ifndef YGO_AGENT_HTTP_CLIENT_H
#define YGO_AGENT_HTTP_CLIENT_H

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace ygo::agent {

struct HttpResult {
	int status = 0; // Zero means that no HTTP response was received.
	std::string body;
	std::string error;
};

// Plain HTTP transport. JSON interpretation belongs to the caller.
class HttpClient final {
public:
	using Completion = std::function<void(HttpResult)>;
	static constexpr std::size_t max_json_size = 1024 * 1024;

	HttpClient() = default;
	~HttpClient();
	HttpClient(const HttpClient&) = delete;
	HttpClient& operator=(const HttpClient&) = delete;

	// Returns false for invalid configuration or an already running client.
	bool Start(std::string host, std::uint16_t port, std::string token,
	           int timeout_ms, Completion completion);
	// Returns false while busy, stopped, or if the JSON exceeds the size limit.
	bool Submit(std::string json);
	// Cancels pending work. Joins the worker except when called by its callback.
	// Callbacks run on the worker; they must be short and must not throw.
	void Stop();

private:
	struct State;
	static void Run(std::shared_ptr<State> state);
	std::mutex mutex_;
	std::shared_ptr<State> state_;
	std::thread worker_;
};

} // namespace ygo::agent
#endif
