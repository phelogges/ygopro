#include "agent_process.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <string_view>
#include <thread>
#include <vector>

#if !defined(_WIN32)
#include <cerrno>
#include <csignal>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
#endif

namespace ygo::agent_client {

AgentProcess::~AgentProcess() { Stop(); }

#if !defined(_WIN32)
namespace {

bool ValidProfile(const std::string &profile) {
	if(profile.empty() || profile.size() > 64)
		return false;
	for(const char character : profile)
		if((character < 'a' || character > 'z') && (character < 'A' || character > 'Z') &&
		   (character < '0' || character > '9') && character != '_' && character != '-')
			return false;
	return true;
}

std::vector<std::string> ChildEnvironment(const std::string &token, const std::string &nonce) {
	std::vector<std::string> entries;
	for(char **entry = environ; entry && *entry; ++entry) {
		const std::string_view value(*entry);
		if(value.substr(0, 24) != "YGOPRO_AGENT_BOOT_TOKEN=" && value.substr(0, 24) != "YGOPRO_AGENT_BOOT_NONCE=")
			entries.emplace_back(*entry);
	}
	entries.push_back("YGOPRO_AGENT_BOOT_TOKEN=" + token);
	entries.push_back("YGOPRO_AGENT_BOOT_NONCE=" + nonce);
	return entries;
}

bool ReadReadyLine(int fd, std::string &line, std::string &error) {
	const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(60);
	while(std::chrono::steady_clock::now() < deadline) {
		const auto remaining =
			std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now()).count();
		pollfd descriptor{fd, POLLIN, 0};
		const int count = poll(&descriptor, 1, static_cast<int>(std::min<std::int64_t>(remaining, 250)));
		if(count < 0) {
			if(errno == EINTR)
				continue;
			error = "读取 Agent 服务就绪消息失败";
			return false;
		}
		if(count == 0)
			continue;
		if(descriptor.revents & (POLLIN | POLLHUP)) {
			char bytes[256];
			const auto size = read(fd, bytes, sizeof bytes);
			if(size <= 0) {
				error = "Agent 服务没有返回就绪消息";
				return false;
			}
			for(ssize_t i = 0; i < size; ++i) {
				if(bytes[i] == '\n')
					return true;
				if(line.size() >= 4096) {
					error = "Agent 服务就绪消息过长";
					return false;
				}
				line.push_back(bytes[i]);
			}
		}
	}
	error = "Agent 服务启动超时";
	return false;
}

} // namespace
#endif

bool AgentProcess::Start(const std::string &executable, const std::string &profile, const std::string &token,
						 const std::string &nonce, AgentProcessReady &ready, std::string &error) {
#if defined(_WIN32)
	(void)executable;
	(void)profile;
	(void)token;
	(void)nonce;
	(void)ready;
	error = "此构建尚未支持 Windows Agent 子进程";
	return false;
#else
	if(pid_ != -1 || executable.empty() || !ValidProfile(profile) || token.empty() || nonce.empty()) {
		error = "Agent 子进程参数无效";
		return false;
	}
	int pipe_fds[2];
	if(pipe(pipe_fds) != 0) {
		error = "无法创建 Agent 就绪管道";
		return false;
	}
	posix_spawn_file_actions_t actions;
	if(posix_spawn_file_actions_init(&actions) != 0) {
		close(pipe_fds[0]);
		close(pipe_fds[1]);
		error = "无法初始化 Agent 子进程";
		return false;
	}
	posix_spawn_file_actions_adddup2(&actions, pipe_fds[1], STDOUT_FILENO);
	posix_spawn_file_actions_addclose(&actions, pipe_fds[0]);
	posix_spawn_file_actions_addclose(&actions, pipe_fds[1]);
	std::vector<std::string> environment = ChildEnvironment(token, nonce);
	std::vector<char *> envp;
	for(auto &entry : environment)
		envp.push_back(entry.data());
	envp.push_back(nullptr);
	std::vector<std::string> arguments{executable, "--config", profile};
	std::vector<char *> argv;
	for(auto &argument : arguments)
		argv.push_back(argument.data());
	argv.push_back(nullptr);
	pid_t child = -1;
	const int spawn_error = posix_spawnp(&child, executable.c_str(), &actions, nullptr, argv.data(), envp.data());
	posix_spawn_file_actions_destroy(&actions);
	close(pipe_fds[1]);
	if(spawn_error != 0) {
		close(pipe_fds[0]);
		error = "无法启动 Agent 服务 (" + std::to_string(spawn_error) + ")";
		return false;
	}
	pid_ = child;
	std::string line;
	const bool received = ReadReadyLine(pipe_fds[0], line, error);
	close(pipe_fds[0]);
	if(!received) {
		Stop();
		return false;
	}
	try {
		const auto message = nlohmann::json::parse(line);
		if(!message.is_object() || message.value("schema_version", 0) != 3 || !message.contains("port") ||
		   !message["port"].is_number_integer() || message.value("nonce", std::string{}) != nonce) {
			error = "Agent 服务就绪消息不匹配";
			Stop();
			return false;
		}
		const int port = message["port"].get<int>();
		if(port < 1 || port > 65535) {
			error = "Agent 服务端口无效";
			Stop();
			return false;
		}
		ready.port = static_cast<std::uint16_t>(port);
		ready.nonce = nonce;
		const int timeout = message.value("decision_timeout_ms", 0);
		if(timeout < 1000 || timeout > 120000) {
			error = "Agent 服务决策期限无效";
			Stop();
			return false;
		}
		ready.decision_timeout_ms = timeout;
		return true;
	} catch(const nlohmann::json::exception &) {
		error = "Agent 服务就绪消息不是有效 JSON";
		Stop();
		return false;
	}
#endif
}

bool AgentProcess::Running() {
#if defined(_WIN32)
	return process_ != nullptr;
#else
	if(pid_ == -1)
		return false;
	int status = 0;
	if(waitpid(pid_, &status, WNOHANG) == 0)
		return true;
	pid_ = -1;
	return false;
#endif
}

void AgentProcess::Stop() {
#if defined(_WIN32)
	process_ = nullptr;
#else
	if(pid_ == -1)
		return;
	const int child = pid_;
	pid_ = -1;
	if(waitpid(child, nullptr, WNOHANG) == child)
		return;
	kill(child, SIGTERM);
	for(int attempt = 0; attempt < 20; ++attempt) {
		if(waitpid(child, nullptr, WNOHANG) == child)
			return;
		std::this_thread::sleep_for(std::chrono::milliseconds(50));
	}
	kill(child, SIGKILL);
	waitpid(child, nullptr, 0);
#endif
}

} // namespace ygo::agent_client
