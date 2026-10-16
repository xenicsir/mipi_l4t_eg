# Compile the same sources under distinct object names: ordinary objects remain
# the deployed MicroLynx FIFO implementation, even when both modules are built.
# NVIDIA overlay builds keep $(src) relative to the main kernel tree. Resolve
# our C prerequisites beside this fragment instead.
eg_titan_src := $(dir $(lastword $(MAKEFILE_LIST)))

CFLAGS_gencp-over-i2c/titan_libunio.o += -DGENCP_I2C_BUFFER_SIZE=1024
CFLAGS_gencp-over-i2c/titan_gencp_client.o += -DGENCP_I2C_BUFFER_SIZE=1024

$(obj)/gencp-over-i2c/titan_libunio.o: $(eg_titan_src)libunio.c FORCE
	$(call if_changed_dep,cc_o_c)

$(obj)/gencp-over-i2c/titan_gencp_client.o: $(eg_titan_src)gencp_client.c FORCE
	$(call if_changed_dep,cc_o_c)
