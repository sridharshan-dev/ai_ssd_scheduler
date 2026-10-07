#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

#include "nvme_spec.h"
#include "nand_backend.h"
#include "tempo_scheduler.h"
#include "host_workload.h"
#include "tempo_verifier.h"

#define MAX_COMPLETED_REQS 100000
#define MAX_EVENTS         200000

typedef enum {
    EVENT_ARRIVAL = 0,
    EVENT_COMPLETION = 1
} event_type_t;

typedef struct {
    double       timestamp_us;
    event_type_t type;
    uint32_t     req_idx;
} sim_event_t;

typedef struct {
    sim_event_t *heap;
    uint32_t     size;
    uint32_t     capacity;
} event_queue_t;

static void eq_init(event_queue_t *eq, uint32_t capacity) {
    eq->heap = (sim_event_t *)malloc(sizeof(sim_event_t) * capacity);
    eq->size = 0;
    eq->capacity = capacity;
}

static void eq_free(event_queue_t *eq) {
    if (eq->heap) free(eq->heap);
    eq->heap = NULL;
    eq->size = 0;
}

static void eq_push(event_queue_t *eq, double ts, event_type_t type, uint32_t req_idx) {
    if (eq->size >= eq->capacity) return;
    uint32_t i = eq->size++;
    while (i > 0) {
        uint32_t p = (i - 1) / 2;
        if (eq->heap[p].timestamp_us <= ts) break;
        eq->heap[i] = eq->heap[p];
        i = p;
    }
    eq->heap[i].timestamp_us = ts;
    eq->heap[i].type = type;
    eq->heap[i].req_idx = req_idx;
}

static int eq_pop(event_queue_t *eq, sim_event_t *out_evt) {
    if (eq->size == 0) return 0;
    *out_evt = eq->heap[0];
    sim_event_t last = eq->heap[--eq->size];
    if (eq->size == 0) return 1;

    uint32_t i = 0;
    while (i * 2 + 1 < eq->size) {
        uint32_t left = i * 2 + 1;
        uint32_t right = left + 1;
        uint32_t smallest = (right < eq->size && eq->heap[right].timestamp_us < eq->heap[left].timestamp_us) ? right : left;
        if (last.timestamp_us <= eq->heap[smallest].timestamp_us) break;
        eq->heap[i] = eq->heap[smallest];
        i = smallest;
    }
    eq->heap[i] = last;
    return 1;
}

typedef struct {
    uint16_t           cid;
    ai_priority_tier_t tier;
    double             arrival_us;
    double             completion_us;
    double             latency_us;
    double             deadline_us;
    int                missed_deadline;
} completion_record_t;

static int compare_doubles(const void *a, const void *b) {
    double da = *(const double *)a;
    double db = *(const double *)b;
    if (da < db) return -1;
    if (da > db) return 1;
    return 0;
}

static double calculate_percentile(double *sorted_vals, uint32_t count, double percentile) {
    if (count == 0) return 0.0;
    double index = (percentile / 100.0) * (count - 1);
    uint32_t lower = (uint32_t)floor(index);
    uint32_t upper = (uint32_t)ceil(index);
    if (lower == upper || upper >= count) return sorted_vals[lower];
    double weight = index - lower;
    return sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight;
}

int main(int argc, char **argv) {
    const char *trace_path = "temp_cheops/results/figure5-6-kv-offloading-flexgen/flexgen-kv-offload-opt-6.7b-bs-64-ext4-trace/opt-6.7b-kv-offload-bs-64-ext4-bpftrace-block.txt";
    scheduler_policy_t policy = POLICY_TEMPO;
    uint32_t max_requests = 1500;
    uint32_t skip_lines = 67800;
    double slack_us = 800.0;
    double bg_iops = 200.0;
    uint32_t max_qd = 32;
    uint32_t seed = 42;
    int json_output = 0;
    int decision_log = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--verify") == 0 || strcmp(argv[i], "--verify-all") == 0) {
            return run_all_verification_tests();
        } else if (strcmp(argv[i], "--test-exact") == 0) {
            test_exact_scenario();
            return 0;
        } else if (strcmp(argv[i], "--test-sanity") == 0) {
            test_4_sanity_policies();
            return 0;
        } else if (strcmp(argv[i], "--test-state") == 0) {
            test_state_mutation();
            return 0;
        } else if (strcmp(argv[i], "--test-tiny") == 0) {
            test_tiny_workload();
            return 0;
        } else if (strcmp(argv[i], "--decision-log") == 0 || strcmp(argv[i], "--verbose") == 0) {
            decision_log = 1;
        } else if (strcmp(argv[i], "--policy") == 0 && i + 1 < argc) {
            i++;
            if (strcmp(argv[i], "fifo") == 0) policy = POLICY_FIFO;
            else if (strcmp(argv[i], "ai_priority") == 0) policy = POLICY_AI_PRIORITY;
            else if (strcmp(argv[i], "ssd_state") == 0) policy = POLICY_SSD_STATE;
            else if (strcmp(argv[i], "tempo") == 0) policy = POLICY_TEMPO;
        } else if (strcmp(argv[i], "--requests") == 0 && i + 1 < argc) {
            max_requests = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--skip") == 0 && i + 1 < argc) {
            skip_lines = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--slack") == 0 && i + 1 < argc) {
            slack_us = atof(argv[++i]);
        } else if (strcmp(argv[i], "--bg-iops") == 0 && i + 1 < argc) {
            bg_iops = atof(argv[++i]);
        } else if (strcmp(argv[i], "--qd") == 0 && i + 1 < argc) {
            max_qd = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            seed = (uint32_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--trace") == 0 && i + 1 < argc) {
            trace_path = argv[++i];
        } else if (strcmp(argv[i], "--json") == 0) {
            json_output = 1;
        }
    }

    host_workload_t wl;
    int total_wl = host_workload_load_cheops(&wl, trace_path, max_requests, skip_lines, slack_us, bg_iops, seed);
    if (total_wl <= 0) {
        fprintf(stderr, "Failed to load trace: %s\n", trace_path);
        return 1;
    }

    nand_backend_t backend;
    nand_backend_init(&backend);

    tempo_queue_t queue;
    tempo_queue_init(&queue);

    event_queue_t eq;
    eq_init(&eq, MAX_EVENTS);

    completion_record_t *completions = (completion_record_t *)malloc(sizeof(completion_record_t) * MAX_COMPLETED_REQS);
    uint32_t num_completed = 0;

    /* Schedule all arrivals */
    for (uint32_t i = 0; i < wl.count; i++) {
        eq_push(&eq, wl.requests[i].arrival_us, EVENT_ARRIVAL, i);
    }

    double current_time_us = 0.0;
    uint32_t in_flight_count = 0;
    uint64_t total_arbitration_cycles = 0;
    uint32_t arbitration_count = 0;
    uint64_t total_bytes_transferred = 0;

    /* Try Dispatch Helper Function */
    #define TRY_DISPATCH() do { \
        while (in_flight_count < max_qd && queue.count > 0 && num_completed < MAX_COMPLETED_REQS) { \
            uint64_t cycles = 0; \
            int win_idx = tempo_arbitrate_ex(&queue, &backend, current_time_us, policy, &cycles, decision_log); \
            if (win_idx < 0) break; \
            total_arbitration_cycles += cycles; \
            arbitration_count++; \
            tempo_request_t selected; \
            tempo_queue_remove(&queue, (uint32_t)win_idx, &selected); \
            in_flight_count++; \
            uint64_t slba = nvme_sqe_get_slba(&selected.sqe); \
            uint32_t nlb = nvme_sqe_get_nlb(&selected.sqe); \
            int is_write = (selected.sqe.opcode == NVME_CMD_WRITE); \
            total_bytes_transferred += (uint64_t)nlb * 512ULL; \
            double completion_us = nand_backend_dispatch(&backend, slba, nlb, current_time_us, is_write); \
            if (decision_log) { \
                uint32_t ch_id = 0, lun_id = 0; \
                nand_backend_get_mapping(slba, &ch_id, &lun_id, NULL); \
                printf("  >> DISPATCHED: Req #%u -> Target CH%u/DIE%u | Completion Event at T=%.2f us\n\n", \
                       selected.sqe.cid, ch_id, lun_id, completion_us); \
            } \
            uint32_t c_idx = num_completed++; \
            completions[c_idx].cid = selected.sqe.cid; \
            completions[c_idx].tier = selected.tier; \
            completions[c_idx].arrival_us = selected.arrival_time_us; \
            completions[c_idx].completion_us = completion_us; \
            completions[c_idx].latency_us = completion_us - selected.arrival_time_us; \
            completions[c_idx].deadline_us = selected.deadline_us; \
            completions[c_idx].missed_deadline = (completion_us > selected.deadline_us); \
            eq_push(&eq, completion_us, EVENT_COMPLETION, c_idx); \
        } \
    } while (0)

    sim_event_t evt;
    while (eq_pop(&eq, &evt)) {
        if (evt.timestamp_us > current_time_us) {
            current_time_us = evt.timestamp_us;
        }

        if (evt.type == EVENT_ARRIVAL) {
            uint32_t r_idx = evt.req_idx;
            tempo_queue_push(&queue, &wl.requests[r_idx].sqe, wl.requests[r_idx].arrival_us);
            TRY_DISPATCH();
        } else if (evt.type == EVENT_COMPLETION) {
            if (in_flight_count > 0) in_flight_count--;
            TRY_DISPATCH();
        }
    }

    /* Compute Metrics */
    double crit_latencies[MAX_COMPLETED_REQS];
    uint32_t crit_count = 0;
    uint32_t crit_misses = 0;

    for (uint32_t i = 0; i < num_completed; i++) {
        if (completions[i].tier == AI_PRIORITY_CRITICAL) {
            crit_latencies[crit_count++] = completions[i].latency_us;
            if (completions[i].missed_deadline) {
                crit_misses++;
            }
        }
    }

    qsort(crit_latencies, crit_count, sizeof(double), compare_doubles);

    double p50 = calculate_percentile(crit_latencies, crit_count, 50.0);
    double p95 = calculate_percentile(crit_latencies, crit_count, 95.0);
    double p99 = calculate_percentile(crit_latencies, crit_count, 99.0);
    double p99_9 = calculate_percentile(crit_latencies, crit_count, 99.9);
    double max_lat = (crit_count > 0) ? crit_latencies[crit_count - 1] : 0.0;
    double miss_pct = (crit_count > 0) ? ((double)crit_misses / (double)crit_count * 100.0) : 0.0;

    double total_sim_time_sec = (current_time_us > 0.0) ? (current_time_us / 1000000.0) : 1.0;
    double throughput_mb_s = ((double)total_bytes_transferred / (1024.0 * 1024.0)) / total_sim_time_sec;

    double avg_arb_cycles = (arbitration_count > 0) ? ((double)total_arbitration_cycles / arbitration_count) : 0.0;
    double projected_arm_us = (avg_arb_cycles * 1.25) / 1000.0;

    const char *policy_names[] = {"S0-FIFO", "S1-AI-PRIORITY", "S2-SSD-STATE", "S3-TEMPO"};

    if (json_output) {
        printf("{\n");
        printf("  \"policy\": \"%s\",\n", policy_names[policy]);
        printf("  \"total_completed\": %u,\n", num_completed);
        printf("  \"crit_count\": %u,\n", crit_count);
        printf("  \"crit_misses\": %u,\n", crit_misses);
        printf("  \"miss_pct\": %.2f,\n", miss_pct);
        printf("  \"p50_us\": %.2f,\n", p50);
        printf("  \"p95_us\": %.2f,\n", p95);
        printf("  \"p99_us\": %.2f,\n", p99);
        printf("  \"p99_9_us\": %.2f,\n", p99_9);
        printf("  \"max_us\": %.2f,\n", max_lat);
        printf("  \"throughput_mb_s\": %.2f,\n", throughput_mb_s);
        printf("  \"avg_arb_cycles\": %.1f,\n", avg_arb_cycles);
        printf("  \"projected_arm_us\": %.3f\n", projected_arm_us);
        printf("}\n");
    } else {
        printf("\n===================================================================\n");
        printf("  SSD CONTROLLER FIRMWARE PROTOTYPE: LIVE ARBITRATION BENCHMARK\n");
        printf("===================================================================\n");
        printf(" Policy:                     %s\n", policy_names[policy]);
        printf(" CHEOPS Trace Requests:      %u\n", max_requests);
        printf(" Queue Depth (QD):           %u\n", max_qd);
        printf(" Deadline Slack:             %.1f us\n", slack_us);
        printf(" Background Write Load:      %.1f IOPS\n", bg_iops);
        printf(" Total Requests Dispatched:  %u\n", num_completed);
        printf(" Critical Requests:          %u\n", crit_count);
        printf("-------------------------------------------------------------------\n");
        printf(" Critical Deadline Misses:   %u / %u (%.2f%%)\n", crit_misses, crit_count, miss_pct);
        printf(" Critical P50 Latency:       %.2f us\n", p50);
        printf(" Critical P95 Latency:       %.2f us\n", p95);
        printf(" Critical P99 Latency:       %.2f us\n", p99);
        printf(" Critical P99.9 Tail:        %.2f us\n", p99_9);
        printf(" Critical Max Latency:       %.2f us\n", max_lat);
        printf(" Drive Throughput:           %.2f MB/s\n", throughput_mb_s);
        printf("-------------------------------------------------------------------\n");
        printf(" Avg Controller Arb Cycles:  %.1f cycles\n", avg_arb_cycles);
        printf(" Projected ARM Execution:    %.3f us (@ 800 MHz Cortex-R8)\n", projected_arm_us);
        printf("===================================================================\n\n");
    }

    eq_free(&eq);
    free(completions);
    host_workload_free(&wl);
    return 0;
}
