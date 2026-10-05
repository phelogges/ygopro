#include "sha256_file.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <limits>

namespace ygo::agent {
namespace {

constexpr std::array<std::uint32_t, 64> round_constants{{
	0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
	0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
	0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
	0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
	0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
	0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
	0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
	0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
	0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
	0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
	0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
	0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
	0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
	0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
	0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
}};

constexpr std::uint32_t RotateRight(std::uint32_t value, unsigned count) noexcept {
	return (value >> count) | (value << (32 - count));
}

class Sha256 {
public:
	bool Update(const unsigned char* input, std::size_t size) noexcept {
		constexpr auto max_bytes = std::numeric_limits<std::uint64_t>::max() / 8;
		if(size > max_bytes - total_bytes_) return false;
		total_bytes_ += size;
		while(size) {
			const auto count = std::min(size, block_.size() - used_);
			std::copy_n(input, count, block_.data() + used_);
			used_ += count;
			input += count;
			size -= count;
			if(used_ == block_.size()) {
				Compress();
				used_ = 0;
			}
		}
		return true;
	}

	std::string Finalize() {
		const auto bit_count = total_bytes_ * 8;
		block_[used_++] = 0x80;
		if(used_ > 56) {
			std::fill(block_.begin() + used_, block_.end(), 0);
			Compress();
			used_ = 0;
		}
		std::fill(block_.begin() + used_, block_.begin() + 56, 0);
		for(unsigned i = 0; i < 8; ++i)
			block_[63 - i] = static_cast<unsigned char>(bit_count >> (i * 8));
		Compress();
		constexpr char digits[] = "0123456789abcdef";
		std::string result;
		result.reserve(64);
		for(auto word : state_)
			for(int shift = 28; shift >= 0; shift -= 4)
				result.push_back(digits[(word >> shift) & 0xf]);
		return result;
	}

private:
	void Compress() noexcept {
		std::array<std::uint32_t, 64> words{};
		for(std::size_t i = 0; i < 16; ++i) {
			const auto* bytes = block_.data() + i * 4;
			words[i] = (static_cast<std::uint32_t>(bytes[0]) << 24)
			         | (static_cast<std::uint32_t>(bytes[1]) << 16)
			         | (static_cast<std::uint32_t>(bytes[2]) << 8)
			         | static_cast<std::uint32_t>(bytes[3]);
		}
		for(std::size_t i = 16; i < words.size(); ++i) {
			const auto x = words[i - 15];
			const auto y = words[i - 2];
			const auto sigma0 = RotateRight(x, 7) ^ RotateRight(x, 18) ^ (x >> 3);
			const auto sigma1 = RotateRight(y, 17) ^ RotateRight(y, 19) ^ (y >> 10);
			words[i] = words[i - 16] + sigma0 + words[i - 7] + sigma1;
		}
		auto a = state_[0], b = state_[1], c = state_[2], d = state_[3];
		auto e = state_[4], f = state_[5], g = state_[6], h = state_[7];
		for(std::size_t i = 0; i < words.size(); ++i) {
			const auto sum1 = RotateRight(e, 6) ^ RotateRight(e, 11) ^ RotateRight(e, 25);
			const auto choose = (e & f) ^ (~e & g);
			const auto temp1 = h + sum1 + choose + round_constants[i] + words[i];
			const auto sum0 = RotateRight(a, 2) ^ RotateRight(a, 13) ^ RotateRight(a, 22);
			const auto majority = (a & b) ^ (a & c) ^ (b & c);
			const auto temp2 = sum0 + majority;
			h = g;
			g = f;
			f = e;
			e = d + temp1;
			d = c;
			c = b;
			b = a;
			a = temp1 + temp2;
		}
		state_[0] += a;
		state_[1] += b;
		state_[2] += c;
		state_[3] += d;
		state_[4] += e;
		state_[5] += f;
		state_[6] += g;
		state_[7] += h;
	}

	std::array<std::uint32_t, 8> state_{{
		0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
		0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
	}};
	std::array<unsigned char, 64> block_{};
	std::size_t used_ = 0;
	std::uint64_t total_bytes_ = 0;
};

} // namespace

Sha256FileResult ComputeFileSha256(const std::filesystem::path& path) {
	std::error_code status_error;
	if(std::filesystem::is_directory(path, status_error))
		return {{}, "Cannot read directory for SHA-256: " + path.string()};
	std::ifstream input(path, std::ios::binary);
	if(!input.is_open()) return {{}, "Cannot open file for SHA-256: " + path.string()};
	Sha256 hash;
	std::array<unsigned char, 64 * 1024> buffer{};
	while(true) {
		input.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(buffer.size()));
		const auto count = input.gcount();
		if(count > 0 && !hash.Update(buffer.data(), static_cast<std::size_t>(count)))
			return {{}, "File exceeds SHA-256 length limit: " + path.string()};
		if(input.bad() || (input.fail() && !input.eof()))
			return {{}, "Cannot read file for SHA-256: " + path.string()};
		if(input.eof()) break;
	}
	return {hash.Finalize(), {}};
}

} // namespace ygo::agent
