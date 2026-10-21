# Private buffered GenCP objects for the iLumos composite module.
eg_ilumos_src := $(dir $(lastword $(MAKEFILE_LIST)))

CFLAGS_gencp-over-i2c/ilumos_libunio.o += -DGENCP_I2C_BUFFER_SIZE=1024
CFLAGS_gencp-over-i2c/ilumos_gencp_client.o += -DGENCP_I2C_BUFFER_SIZE=1024

$(obj)/gencp-over-i2c/ilumos_libunio.o: $(eg_ilumos_src)libunio.c FORCE
	$(call if_changed_dep,cc_o_c)

$(obj)/gencp-over-i2c/ilumos_gencp_client.o: $(eg_ilumos_src)gencp_client.c FORCE
	$(call if_changed_dep,cc_o_c)
