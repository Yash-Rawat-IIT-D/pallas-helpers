MPICC ?= mpicc
CFLAGS ?= -O2 -g

all: mpi_test_spinloop

mpi_test_spinloop: mpi_test_spinloop.c
	$(MPICC) $(CFLAGS) $< -o $@

clean:
	rm -f mpi_test_spinloop

.PHONY: all clean
