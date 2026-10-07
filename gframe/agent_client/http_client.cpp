#include "http_client.h"

#include <event2/buffer.h>
#include <event2/dns.h>
#include <event2/event.h>
#include <event2/http.h>
#include <event2/util.h>

#include <utility>

namespace ygo::agent {

struct HttpClient::State {
	std::mutex mutex;
	std::string host;
	std::string token;
	std::uint16_t port = 0;
	int timeout_ms = 0;
	Completion completion;
	bool stopping = false;
	bool busy = false;
	std::string pending;
	std::string pending_path;
	bool pending_get = false;
	int pending_timeout_ms = 0;
	event_base *base = nullptr;
	evdns_base *dns = nullptr;
	event *wake_event = nullptr;
	event *deadline = nullptr;
	evhttp_connection *connection = nullptr;
	evhttp_request *request = nullptr;
	evutil_socket_t sockets[2] = {EVUTIL_INVALID_SOCKET, EVUTIL_INVALID_SOCKET};
	std::string transport_error;

	~State() {
		if(request)
			evhttp_cancel_request(request);
		if(connection)
			evhttp_connection_free(connection);
		if(deadline)
			event_free(deadline);
		if(wake_event)
			event_free(wake_event);
		if(dns)
			evdns_base_free(dns, 0);
		if(base)
			event_base_free(base);
		for(auto socket : sockets)
			if(socket != EVUTIL_INVALID_SOCKET)
				evutil_closesocket(socket);
	}

	void Wake() const {
		const char byte = 1;
		// A full socket already guarantees a pending wakeup.
		send(sockets[1], &byte, 1, 0);
	}

	void Finish(HttpResult result) {
		event_del(deadline);
		{
			std::lock_guard<std::mutex> lock(mutex);
			busy = false;
		}
		// Never allow application exceptions to unwind across a C callback.
		try {
			completion(std::move(result));
		} catch(...) {
		}
	}

	static void OnError(evhttp_request_error error, void *context) {
		auto &self = *static_cast<State *>(context);
		self.transport_error = "HTTP transport error " + std::to_string(static_cast<int>(error));
	}

	static void OnResponse(evhttp_request *response, void *context) {
		auto &self = *static_cast<State *>(context);
		self.request = nullptr;
		HttpResult result;
		if(!response) {
			result.error = self.transport_error.empty() ? "HTTP connection failed" : self.transport_error;
		} else {
			result.status = evhttp_request_get_response_code(response);
			auto *input = evhttp_request_get_input_buffer(response);
			const auto size = evbuffer_get_length(input);
			if(size > max_json_size)
				result.error = "HTTP response exceeds size limit";
			else {
				result.body.resize(size);
				if(size)
					evbuffer_copyout(input, result.body.data(), size);
				if(result.status < 200 || result.status >= 300)
					result.error = "HTTP status " + std::to_string(result.status);
			}
		}
		self.Finish(std::move(result));
	}

	static void OnDeadline(evutil_socket_t, short, void *context) {
		auto &self = *static_cast<State *>(context);
		if(self.request) {
			evhttp_cancel_request(self.request);
			self.request = nullptr;
		}
		self.Finish({0, {}, "HTTP request timed out"});
	}

	void Begin(std::string json, const std::string &path, bool get, int request_timeout_ms) {
		if(connection)
			evhttp_connection_free(connection);
		connection = evhttp_connection_base_new(base, dns, host.c_str(), port);
		if(!connection) {
			Finish({0, {}, "Cannot create HTTP connection"});
			return;
		}
		evhttp_connection_set_retries(connection, 0);
		evhttp_connection_set_max_body_size(connection, max_json_size);
		evhttp_connection_set_max_headers_size(connection, 16 * 1024);
		const int effective_timeout = request_timeout_ms > 0 ? request_timeout_ms : timeout_ms;
		const timeval timeout{effective_timeout / 1000, (effective_timeout % 1000) * 1000};
		evhttp_connection_set_timeout_tv(connection, &timeout);
		transport_error.clear();
		request = evhttp_request_new(OnResponse, this);
		if(!request) {
			Finish({0, {}, "Cannot create HTTP request"});
			return;
		}
		evhttp_request_set_error_cb(request, OnError);
		auto *headers = evhttp_request_get_output_headers(request);
		const auto authority =
			(host.find(':') == std::string::npos ? host : "[" + host + "]") + ":" + std::to_string(port);
		bool valid = evhttp_add_header(headers, "Host", authority.c_str()) == 0 &&
					 evhttp_add_header(headers, "Connection", "close") == 0;
		if(!get)
			valid = valid && evhttp_add_header(headers, "Content-Type", "application/json") == 0;
		if(!token.empty())
			valid = valid && evhttp_add_header(headers, "Authorization", ("Bearer " + token).c_str()) == 0;
		if(!get)
			valid = valid && evbuffer_add(evhttp_request_get_output_buffer(request), json.data(), json.size()) == 0;
		if(!valid) {
			evhttp_request_free(request);
			request = nullptr;
			Finish({0, {}, "Cannot construct HTTP request"});
			return;
		}
		if(evhttp_make_request(connection, request, get ? EVHTTP_REQ_GET : EVHTTP_REQ_POST, path.c_str()) != 0) {
			request = nullptr; // libevent frees the request on failure.
			Finish({0, {}, "Cannot submit HTTP request"});
			return;
		}
		if(event_add(deadline, &timeout) != 0)
			OnDeadline(0, 0, this);
	}

	static void OnWake(evutil_socket_t socket, short, void *context) {
		auto &self = *static_cast<State *>(context);
		char bytes[64];
		while(recv(socket, bytes, sizeof bytes, 0) > 0) {
		}
		std::string json;
		std::string path;
		bool get = false;
		int request_timeout_ms = 0;
		bool stopping;
		bool busy;
		{
			std::lock_guard<std::mutex> lock(self.mutex);
			stopping = self.stopping;
			busy = self.busy;
			json.swap(self.pending);
			path.swap(self.pending_path);
			get = self.pending_get;
			request_timeout_ms = self.pending_timeout_ms;
		}
		if(stopping) {
			if(self.request) {
				evhttp_cancel_request(self.request);
				self.request = nullptr;
			}
			if(busy)
				self.Finish({0, {}, "HTTP client stopped"});
			event_base_loopbreak(self.base);
		} else if(get || !json.empty())
			self.Begin(std::move(json), path, get, request_timeout_ms);
	}
};

HttpClient::~HttpClient() { Stop(); }

bool HttpClient::Start(std::string host, std::uint16_t port, std::string token,
                      int timeout_ms, Completion completion) {
	if(host.empty() || host.find_first_of("\r\n/ ") != std::string::npos
	   || host.find('\0') != std::string::npos || !port || timeout_ms <= 0 || !completion
	   || token.find_first_of("\r\n") != std::string::npos || token.find('\0') != std::string::npos)
		return false;
	std::lock_guard<std::mutex> lock(mutex_);
	if(state_) return false;
	auto state = std::make_shared<State>();
	state->host = std::move(host);
	state->port = port;
	state->token = std::move(token);
	state->timeout_ms = timeout_ms;
	state->completion = std::move(completion);
	state->base = event_base_new();
	if(!state->base) return false;
	state->dns = evdns_base_new(state->base, 1);
	if(!state->dns) return false;
	if(evutil_socketpair(AF_UNIX, SOCK_STREAM, 0, state->sockets) != 0) return false;
	for(auto socket : state->sockets)
		if(evutil_make_socket_nonblocking(socket) != 0) return false;
	state->wake_event = event_new(state->base, state->sockets[0], EV_READ | EV_PERSIST, State::OnWake, state.get());
	state->deadline = evtimer_new(state->base, State::OnDeadline, state.get());
	if(!state->wake_event || !state->deadline || event_add(state->wake_event, nullptr) != 0) return false;
	try { worker_ = std::thread(Run, state); } catch(...) { return false; }
	state_ = std::move(state);
	return true;
}

bool HttpClient::Submit(std::string json, std::string path, int timeout_ms) {
	if(json.empty() || json.size() > max_json_size ||
	   (path != "/v2/decision" && path != "/v2/sync" && path != "/v2/status" && path != "/v3/decision" &&
		path != "/v3/sync" && path != "/v3/status" && path != "/v3/query-result" && path != "/v3/action-result") ||
	   timeout_ms < 0)
		return false;
	std::lock_guard<std::mutex> lock(mutex_);
	if(!state_)
		return false;
	std::lock_guard<std::mutex> state_lock(state_->mutex);
	if(state_->busy || state_->stopping)
		return false;
	state_->pending = std::move(json);
	state_->pending_path = std::move(path);
	state_->pending_get = false;
	state_->pending_timeout_ms = timeout_ms;
	state_->busy = true;
	state_->Wake();
	return true;
}

bool HttpClient::Get(std::string path, int timeout_ms) {
	if(path != "/v3/ready" || timeout_ms < 0)
		return false;
	std::lock_guard<std::mutex> lock(mutex_);
	if(!state_)
		return false;
	std::lock_guard<std::mutex> state_lock(state_->mutex);
	if(state_->busy || state_->stopping)
		return false;
	state_->pending.clear();
	state_->pending_path = std::move(path);
	state_->pending_get = true;
	state_->pending_timeout_ms = timeout_ms;
	state_->busy = true;
	state_->Wake();
	return true;
}

void HttpClient::Stop() {
	std::thread worker;
	{
		std::lock_guard<std::mutex> lock(mutex_);
		if(!state_) return;
		{
			std::lock_guard<std::mutex> state_lock(state_->mutex);
			state_->stopping = true;
		}
		state_->Wake();
		state_.reset();
		worker = std::move(worker_);
	}
	if(worker.joinable()) {
		if(worker.get_id() == std::this_thread::get_id()) worker.detach();
		else worker.join();
	}
}

void HttpClient::Run(std::shared_ptr<State> state) {
	event_base_dispatch(state->base);
}

} // namespace ygo::agent
