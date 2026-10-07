CC = gcc
CFLAGS = -O2 -Wall -D__USE_MINGW_ANSI_STDIO=1 -Iinclude
LDFLAGS = -lm

SRC = src/controller_main.c src/nand_backend.c src/tempo_scheduler.c src/host_workload.c src/tempo_verifier.c
TARGET = tempo_controller.exe

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET) $(LDFLAGS)

clean:
	rm -f $(TARGET) *.o
