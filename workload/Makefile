# Pip's Garden. Built inside the mario-eval toolchain image:
#   docker run --rm -v "$PWD":/work mario-eval-toolchain make
# Output: pips-garden.z64 (graded build). `make PLAY=1` builds the TV/audio
# variant for real hardware.
BUILD_DIR = build
include $(N64_INST)/include/n64.mk

# The shipped engine is built like many 1990s console games were: without
# optimization. Changing these flags is allowed.
OPT_FLAGS = -O0
N64_CFLAGS += $(OPT_FLAGS)

ifdef PLAY
N64_CFLAGS += -DPLAY
endif

SRCS = src/main.c src/world.c src/render.c src/synth.c src/math3d.c src/mev.c

all: pips-garden.z64

$(BUILD_DIR)/pips-garden.elf: $(SRCS:%.c=$(BUILD_DIR)/%.o)
pips-garden.z64: N64_ROM_TITLE = "Pips Garden"

clean:
	rm -rf $(BUILD_DIR) pips-garden.z64

-include $(wildcard $(BUILD_DIR)/*.d $(BUILD_DIR)/src/*.d)

.PHONY: all clean
