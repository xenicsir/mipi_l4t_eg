// SPDX-License-Identifier: MIT
#ifndef EG_GENCP_PORT_HPP
#define EG_GENCP_PORT_HPP
#include "eg_camera_gencp.h"
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <system_error>
#include <sys/ioctl.h>
#include <unistd.h>
#include <vector>

// One call is one complete transaction. No serial-port configuration or direct
// I2C access is needed. Sensor errors remain in the returned GenCP ACK.
class EgGenCPPort {
    int fd_;
    static unsigned get16(const uint8_t *p) { return (unsigned(p[0]) << 8) | p[1]; }
public:
    explicit EgGenCPPort(const char *device) : fd_(::open(device, O_RDWR | O_CLOEXEC)) {
        if (fd_ < 0) throw std::system_error(errno, std::generic_category(), device);
    }
    ~EgGenCPPort() { if (fd_ >= 0) ::close(fd_); }
    EgGenCPPort(const EgGenCPPort &) = delete;
    EgGenCPPort &operator=(const EgGenCPPort &) = delete;

    void Transaction(const std::vector<uint8_t> &request, std::vector<uint8_t> &reply) {
        if (request.size() < 16 || request.size() > EG_GENCP_PACKET_MAX)
            throw std::invalid_argument("GenCP request length");
        eg_gencp_xfer x = {};
        x.version = EG_GENCP_ABI_VERSION;
        x.tx_length = request.size();
        x.rx_capacity = EG_GENCP_PACKET_MAX;
        std::copy(request.begin(), request.end(), x.tx);
        if (::ioctl(fd_, EG_IOCTL_GENCP_XFER, &x) < 0)
            throw std::system_error(errno, std::generic_category(), "GenCP transaction");
        if (x.rx_length < 16 || x.rx_length > x.rx_capacity ||
            get16(x.rx) != 0x0100 || get16(x.rx + 12) + 16 != x.rx_length ||
            get16(x.rx + 6) != get16(x.tx + 6) || get16(x.rx + 14) != get16(x.tx + 14) ||
            get16(x.rx + 10) != get16(x.tx + 10) + 1)
            throw std::runtime_error("Invalid or mismatched GenCP ACK");
        reply.assign(x.rx, x.rx + x.rx_length);
    }
    eg_gencp_stats Stats() {
        eg_gencp_stats value = {};
        if (::ioctl(fd_, EG_IOCTL_GENCP_STATS, &value) < 0)
            throw std::system_error(errno, std::generic_category(), "GenCP statistics");
        if (value.version != EG_GENCP_ABI_VERSION)
            throw std::runtime_error("Unsupported GenCP ABI version");
        return value;
    }
};
static_assert(sizeof(eg_gencp_xfer) == 2080, "GenCP transaction ABI size");
static_assert(sizeof(eg_gencp_stats) == 40, "GenCP statistics ABI size");
#endif
