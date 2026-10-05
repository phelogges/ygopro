#ifndef YGO_AGENT_SHA256_FILE_H
#define YGO_AGENT_SHA256_FILE_H

#include <filesystem>
#include <string>

namespace ygo::agent {

struct Sha256FileResult {
	std::string hex;
	std::string error;
	explicit operator bool() const noexcept { return error.empty(); }
};

// Hashes the file's bytes, using bounded memory. On failure hex is empty and
// error describes the failure. The caller must ensure the file stays unchanged
// while it is being read.
Sha256FileResult ComputeFileSha256(const std::filesystem::path& path);

} // namespace ygo::agent
#endif
