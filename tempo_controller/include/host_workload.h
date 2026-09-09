#ifndef HOST_WORKLOAD_H
#define HOST_WORKLOAD_H

#include "nvme_spec.h"
#include <stdint.h>

typedef struct {
    nvme_sq_entry_t sqe;
    double          arrival_us;
} host_request_t;

typedef struct {
    host_request_t *requests;
    uint32_t        count;
    uint32_t        capacity;
} host_workload_t;

int  host_workload_load_cheops(host_workload_t *wl, const char *trace_path, uint32_t max_requests, uint32_t skip_lines, double default_slack_us, double bg_iops, uint32_t seed);
void host_workload_free(host_workload_t *wl);

#endif /* HOST_WORKLOAD_H */
