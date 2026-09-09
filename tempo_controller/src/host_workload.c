#include "host_workload.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <inttypes.h>

typedef struct {
    uint64_t ts_ns;
    char     op[16];
    uint32_t size_bytes;
    uint64_t start_sec;
    uint32_t num_sec;
} raw_trace_entry_t;

static int compare_raw_entries(const void *a, const void *b) {
    const raw_trace_entry_t *ra = (const raw_trace_entry_t *)a;
    const raw_trace_entry_t *rb = (const raw_trace_entry_t *)b;
    if (ra->ts_ns < rb->ts_ns) return -1;
    if (ra->ts_ns > rb->ts_ns) return 1;
    return 0;
}

static int compare_requests(const void *a, const void *b) {
    const host_request_t *ra = (const host_request_t *)a;
    const host_request_t *rb = (const host_request_t *)b;
    if (ra->arrival_us < rb->arrival_us) return -1;
    if (ra->arrival_us > rb->arrival_us) return 1;
    return 0;
}

/* Portable LCG PRNG */
static uint32_t g_lcg_seed = 42;
static void my_srand(uint32_t seed) { g_lcg_seed = seed ? seed : 1; }
static double my_rand_uniform(void) {
    g_lcg_seed = (1103515245U * g_lcg_seed + 12345U) & 0x7FFFFFFFU;
    return ((double)g_lcg_seed + 1.0) / 2147483648.0;
}
static double my_rand_exponential(double scale) {
    double u = my_rand_uniform();
    return -scale * log(u);
}

int host_workload_load_cheops(host_workload_t *wl, const char *trace_path, uint32_t max_requests, uint32_t skip_lines, double default_slack_us, double bg_iops, uint32_t seed) {
    FILE *fp = fopen(trace_path, "r");
    if (!fp) {
        fprintf(stderr, "Error: Unable to open trace file: %s\n", trace_path);
        return -1;
    }

    my_srand(seed);

    raw_trace_entry_t *raw = (raw_trace_entry_t *)malloc(sizeof(raw_trace_entry_t) * max_requests);
    if (!raw) {
        fclose(fp);
        return -1;
    }

    char line[512];
    uint32_t skipped = 0;
    uint32_t raw_count = 0;

    while (fgets(line, sizeof(line), fp)) {
        if (line[0] < '0' || line[0] > '9') continue;

        if (skipped < skip_lines) {
            skipped++;
            continue;
        }

        uint64_t ts_ns = 0, start_sec = 0;
        uint32_t size_bytes = 0, num_sec = 0;
        char op[16];

        int matches = sscanf(line, "%" SCNu64 " , %15[^,] , %u , %" SCNu64 " , %u", &ts_ns, op, &size_bytes, &start_sec, &num_sec);
        if (matches < 5) continue;

        raw[raw_count].ts_ns = ts_ns;
        strncpy(raw[raw_count].op, op, sizeof(raw[raw_count].op) - 1);
        raw[raw_count].op[sizeof(raw[raw_count].op) - 1] = '\0';
        raw[raw_count].size_bytes = size_bytes;
        raw[raw_count].start_sec = start_sec;
        raw[raw_count].num_sec = num_sec;
        raw_count++;

        if (raw_count >= max_requests) break;
    }
    fclose(fp);

    if (raw_count == 0) {
        free(raw);
        return 0;
    }

    /* Sort raw entries by timestamp to eliminate multi-core bpftrace probe logging jitter */
    qsort(raw, raw_count, sizeof(raw_trace_entry_t), compare_raw_entries);
    uint64_t min_ts_ns = raw[0].ts_ns;

    uint32_t alloc_cap = max_requests * 3 + 10000;
    wl->requests = (host_request_t *)malloc(sizeof(host_request_t) * alloc_cap);
    if (!wl->requests) {
        free(raw);
        return -1;
    }
    wl->count = 0;
    wl->capacity = alloc_cap;

    uint32_t read_idx = 0;
    for (uint32_t i = 0; i < raw_count; i++) {
        double arrival_us = (double)(raw[i].ts_ns - min_ts_ns) / 1000.0;
        int is_write = (raw[i].op[0] == 'W');

        nvme_sq_entry_t sqe;
        memset(&sqe, 0, sizeof(sqe));
        sqe.opcode = is_write ? NVME_CMD_WRITE : NVME_CMD_READ;
        sqe.cid = (uint16_t)(i & 0xFFFF);
        sqe.nsid = 1;
        sqe.cdw10 = (uint32_t)(raw[i].start_sec & 0xFFFFFFFF);
        sqe.cdw11 = (uint32_t)(raw[i].start_sec >> 32);
        sqe.cdw12 = (raw[i].num_sec > 0) ? (raw[i].num_sec - 1) : 0;

        ai_priority_tier_t tier;
        uint16_t slack_us;

        if (!is_write) {
            /* 40% of reads are Critical next-token KV decodes */
            if ((read_idx % 5) < 2) {
                tier = AI_PRIORITY_CRITICAL;
                slack_us = (uint16_t)default_slack_us;
            } else {
                tier = AI_PRIORITY_NORMAL;
                slack_us = (uint16_t)(default_slack_us * 2.0);
            }
            read_idx++;
        } else {
            tier = AI_PRIORITY_BACKGROUND;
            slack_us = (uint16_t)(default_slack_us * 5.0);
        }

        sqe.cdw13 = tempo_encode_cdw13(tier, slack_us, (uint16_t)i);

        wl->requests[wl->count].sqe = sqe;
        wl->requests[wl->count].arrival_us = arrival_us;
        wl->count++;
    }

    free(raw);

    /* Generate background Poisson write traffic */
    if (bg_iops > 0.0 && wl->count > 0) {
        double t_start = wl->requests[0].arrival_us;
        double t_end = wl->requests[wl->count - 1].arrival_us;
        double duration_s = (t_end - t_start) / 1e6;

        if (duration_s > 0.0) {
            int num_bg = (int)(bg_iops * duration_s);
            double mean_interval_us = (duration_s * 1e6) / (num_bg > 0 ? num_bg : 1);
            double cur_t = t_start;
            uint64_t base_sec = 100000000ULL;

            for (int b = 0; b < num_bg && wl->count < wl->capacity; b++) {
                double delta_t = my_rand_exponential(mean_interval_us);
                cur_t += delta_t;

                nvme_sq_entry_t sqe;
                memset(&sqe, 0, sizeof(sqe));
                sqe.opcode = NVME_CMD_WRITE;
                sqe.cid = (uint16_t)((90000 + b) & 0xFFFF);
                sqe.nsid = 1;
                uint64_t sec = base_sec + ((uint64_t)b * 256ULL);
                sqe.cdw10 = (uint32_t)(sec & 0xFFFFFFFF);
                sqe.cdw11 = (uint32_t)(sec >> 32);
                sqe.cdw12 = 255; /* 128 KiB */

                sqe.cdw13 = tempo_encode_cdw13(AI_PRIORITY_BACKGROUND, (uint16_t)(default_slack_us * 10.0), (uint16_t)(90000 + b));

                wl->requests[wl->count].sqe = sqe;
                wl->requests[wl->count].arrival_us = cur_t;
                wl->count++;
            }
        }
    }

    /* Sort all requests by arrival time */
    qsort(wl->requests, wl->count, sizeof(host_request_t), compare_requests);

    return (int)wl->count;
}

void host_workload_free(host_workload_t *wl) {
    if (wl->requests) {
        free(wl->requests);
        wl->requests = NULL;
    }
    wl->count = 0;
    wl->capacity = 0;
}
