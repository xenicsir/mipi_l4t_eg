# Compile the same sources under distinct object names: ordinary objects remain
# the deployed MicroLynx FIFO implementation, even when both modules are built.
CFLAGS_gencp-over-i2c/titan_libunio.o += -DGENCP_I2C_BUFFER_SIZE=1024
CFLAGS_gencp-over-i2c/titan_gencp_client.o += -DGENCP_I2C_BUFFER_SIZE=1024

$(obj)/gencp-over-i2c/titan_libunio.o: $(src)/gencp-over-i2c/libunio.c FORCE
	$(call if_changed_dep,cc_o_c)

$(obj)/gencp-over-i2c/titan_gencp_client.o: $(src)/gencp-over-i2c/gencp_client.c FORCE
	$(call if_changed_dep,cc_o_c)
