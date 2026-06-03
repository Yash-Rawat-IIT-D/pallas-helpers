#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>


int iterations = 1000;
long delay_us = 10000;
int payload_bytes = 8;

static int parse_int_arg(char **argv, int index, int default_value) {
    if (argv[index] == NULL) {
        return default_value;
    }
    return atoi(argv[index]);
}

static long parse_long_arg(char **argv, int index, long default_value) {
    if (argv[index] == NULL) {
        return default_value;
    }
    return atol(argv[index]);
}

int main(int argc, char **argv) {
    int rank, size;
    char *send_buffer = NULL;
    char *recv_buffer = NULL;
    long long total_polls = 0;

    MPI_Init(&argc, &argv);
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    if (size != 2) {
        if (rank == 0) {
            fprintf(stderr, "mpi_test_spinloop requires exactly 2 MPI ranks\n");
        }
        MPI_Finalize();
        return 1;
    }

    if (argc > 1) {
        iterations = parse_int_arg(argv, 1, iterations);
    }
    if (argc > 2) {
        delay_us = parse_long_arg(argv, 2, delay_us);
    }
    if (argc > 3) {
        payload_bytes = parse_int_arg(argv, 3, payload_bytes);
    }

    if (iterations < 1) {
        iterations = 1;
    }
    if (delay_us < 0) {
        delay_us = 0;
    }

    if (payload_bytes < 1) {
        payload_bytes = 1;
    }

    send_buffer = (char *)malloc((size_t)payload_bytes);
    recv_buffer = (char *)malloc((size_t)payload_bytes);
    if (send_buffer == NULL || recv_buffer == NULL) {
        fprintf(stderr, "rank=%d failed to allocate payload buffers\n", rank);
        free(send_buffer);
        free(recv_buffer);
        MPI_Finalize();
        return 1;
    }

    for (int i = 0; i < payload_bytes; ++i) {
        send_buffer[i] = (char)(i & 0x7f);
        recv_buffer[i] = 0;
    }

    for (int iter = 0; iter < iterations; ++iter) {
        MPI_Request req;

        MPI_Barrier(MPI_COMM_WORLD);

        if (rank == 1) {
            int flag = 0;
            long long polls = 0;

            MPI_Irecv(recv_buffer, payload_bytes, MPI_BYTE, 0, iter,
                      MPI_COMM_WORLD, &req);

            while (!flag) {
                MPI_Test(&req, &flag, MPI_STATUS_IGNORE);
                polls++;
            }

            total_polls += polls;
        } else {
            if (delay_us > 0) {
                usleep((useconds_t)delay_us);
            }

            MPI_Isend(send_buffer, payload_bytes, MPI_BYTE, 1, iter,
                      MPI_COMM_WORLD, &req);
            MPI_Wait(&req, MPI_STATUS_IGNORE);
        }
    }

    if (rank == 1) {
        double avg_polls = (double)total_polls / (double)iterations;
        printf("rank=%d iterations=%d delay_us=%ld payload_bytes=%d total_polls=%lld avg_polls_per_iter=%.6f\n",
               rank, iterations, delay_us, payload_bytes, total_polls, avg_polls);
    } else {
        printf("rank=%d iterations=%d delay_us=%ld payload_bytes=%d\n",
               rank, iterations, delay_us, payload_bytes);
    }

    free(send_buffer);
    free(recv_buffer);
    MPI_Finalize();
    return 0;
}
