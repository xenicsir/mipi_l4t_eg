// SPDX-License-Identifier: MIT
#include "eg_gencp_port.hpp"
#include "xccapi_gencp_cl_packet_handler.h"
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <sys/resource.h>

static uint64_t number(const char *text) {
    size_t end;
    std::string value(text);
    if (value.empty() || value[0] == '-') throw std::invalid_argument("Unsigned number required");
    uint64_t n = std::stoull(value, &end, 0);
    if (end != value.size()) throw std::invalid_argument("Invalid number");
    return n;
}
static std::vector<uint8_t> read(EgGenCPPort &port, GenCPPacketHandler &codec,
                                 uint64_t address, uint32_t length) {
    if (!length || length > 1008) throw std::invalid_argument("Read length must be 1..1008");
    std::vector<uint8_t> request, reply;
    codec.ComposeReadCmd(address, length, request, false);
    port.Transaction(request, reply);
    uint32_t offset = 0, size = 0;
    if (!codec.ParseReadAcknowledge(reply, true, offset, size))
        throw std::runtime_error(codec.GetError());
    if (size != length || offset > reply.size() || size > reply.size() - offset)
        throw std::runtime_error("Read ACK size mismatch");
    return std::vector<uint8_t>(reply.begin() + offset, reply.begin() + offset + size);
}
static void dump(const std::vector<uint8_t> &bytes) {
    for (auto value : bytes) std::cout << std::hex << std::setw(2) << std::setfill('0') << unsigned(value);
    std::cout << std::dec << '\n';
}
int main(int argc, char **argv) {
    if (argc < 3) {
        std::cerr << "Usage: egXenethMinimal DEVICE probe|read32 ADDR [COUNT]|read ADDR LEN|write32 ADDR VALUE|write ADDR HEX\n";
        return 2;
    }
    try {
        EgGenCPPort port(argv[1]);
        GenCPPacketHandler codec; // Compiled from the unmodified SDK source.
        auto before = port.Stats();
        auto start = std::chrono::steady_clock::now();
        struct rusage cpu_before = {}, cpu_after = {};
        getrusage(RUSAGE_SELF, &cpu_before);
        std::string command(argv[2]);
        if (command == "probe" && argc == 3) {
            const bool micro = std::string(argv[1]).find("microlynx") != std::string::npos;
            const bool titan = std::string(argv[1]).find("titan") != std::string::npos;
            for (auto item : {std::make_pair("model", uint64_t(0x44)), std::make_pair("serial", uint64_t(0x144)),
                              std::make_pair("firmware", uint64_t(micro ? 0xb0000000 : 0x10000000))}) {
                auto data = read(port, codec, item.second, 64);
                std::cout << item.first << ": " << std::string(data.begin(), std::find_if(data.begin(), data.end(), [](uint8_t n) { return n == 0 || n == 255; })) << '\n';
            }
            for (auto address : {uint64_t(micro ? 0x500e0008 : titan ? 0x500e0000 : 0x50000000),
                                 uint64_t(micro ? 0x500e000c : titan ? 0x500e0004 : 0x50000004)}) {
                auto data = read(port, codec, address, 4);
                std::cout << "0x" << std::hex << address << " = "; dump(data);
            }
        } else if (command == "read32" && (argc == 4 || argc == 5)) {
            uint64_t count = argc == 5 ? number(argv[4]) : 1;
            if (!count || count > 1000000) throw std::invalid_argument("Count must be 1..1000000");
            uint64_t address = number(argv[3]);
            std::vector<uint8_t> data;
            for (uint64_t i = 0; i < count; i++) data = read(port, codec, address, 4);
            std::cout << "reads=" << count << " value="; dump(data);
        } else if (command == "read" && argc == 5) {
            auto length = number(argv[4]);
            if (!length || length > 1008) throw std::invalid_argument("Read length must be 1..1008");
            dump(read(port, codec, number(argv[3]), length));
        } else if ((command == "write32" || command == "write") && argc == 5) {
            std::vector<uint8_t> data;
            if (command == "write32") {
                uint64_t value = number(argv[4]);
                if (value > 0xffffffff) throw std::invalid_argument("32-bit value out of range");
                for (int i = 3; i >= 0; i--) data.push_back(value >> (i * 8));
            } else {
                std::string hex(argv[4]);
                if (hex.empty() || hex.size() % 2 || hex.size() > 2000 ||
                    hex.find_first_not_of("0123456789abcdefABCDEF") != std::string::npos)
                    throw std::invalid_argument("Even hexadecimal string of 1..1000 bytes required");
                for (size_t i = 0; i < hex.size(); i += 2) data.push_back(std::stoul(hex.substr(i, 2), nullptr, 16));
            }
            std::vector<uint8_t> request, reply;
            codec.ComposeWriteCmd(number(argv[3]), data, request, GENCP_CAP_WRITEN_LENGTH_FIELD, false);
            port.Transaction(request, reply);
            if (!codec.ParseWriteAcknowledge(reply, true)) throw std::runtime_error(codec.GetError());
            std::cout << "write=OK bytes=" << data.size() << '\n';
        } else throw std::invalid_argument("Invalid command or arguments");
        auto after = port.Stats();
        getrusage(RUSAGE_SELF, &cpu_after);
        auto micros = [](timeval t) { return int64_t(t.tv_sec) * 1000000 + t.tv_usec; };
        std::cout << "transport=" << after.transport_bytes << " transactions=" << after.transactions - before.transactions
                  << " polls=" << after.polls - before.polls << " tx_requested_bytes=" << after.tx_requested_bytes - before.tx_requested_bytes
                  << " rx_requested_bytes=" << after.rx_requested_bytes - before.rx_requested_bytes
                  << " cpu_user_us=" << micros(cpu_after.ru_utime) - micros(cpu_before.ru_utime)
                  << " cpu_system_us=" << micros(cpu_after.ru_stime) - micros(cpu_before.ru_stime)
                  << " elapsed_ms=" << std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count() << '\n';
        return 0;
    } catch (const std::system_error &error) {
        std::cerr << error.what() << '\n';
        return error.code().value() == EOPNOTSUPP ? 3 : 1;
    } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
