#ifndef TEMPO_SCHEDULER_H
#define TEMPO_SCHEDULER_H

#include "nvme_spec.h"
#include "nand_backend.h"

#define MAX_QUEUE_DEPTH 128

typedef enum {
    POLICY_FIFO         = 0, /* S0: Arrival order */
    POLICY_AI_PRIORITY  = 1, /* S1: Urgency tier strictly, FIFO tie-breaking */
    POLICY_SSD_STATE    = 2, /* S2: Greedy shortest channel delay */
    POLICY_TEMPO        = 3  /* S3: Joint AI urgency + hardware channel readiness */
} scheduler_policy_t;

typedef struct {
    nvme_sq_entry_t    sqe;
    double             arrival_time_us;
    double             deadline_us;
    ai_priority_tier_t tier;
    uint16_t           slack_us;
    uint16_t           seq_id;
    double             predicted_delay_us;
    double             score;
} tempo_request_t;

typedef struct {
    tempo_request_t entries[MAX_QUEUE_DEPTH];
    uint32_t        count;
} tempo_queue_t;

void tempo_queue_init(tempo_queue_t *q);
int  tempo_queue_push(tempo_queue_t *q, const nvme_sq_entry_t *sqe, double arrival_time_us);
int  tempo_queue_remove(tempo_queue_t *q, uint32_t index, tempo_request_t *out_req);
int  tempo_arbitrate(tempo_queue_t *q, const nand_backend_t *backend, double now_us, scheduler_policy_t policy, uint64_t *out_cycles);

#endif /* TEMPO_SCHEDULER_H */
