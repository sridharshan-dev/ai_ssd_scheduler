#include "tempo_scheduler.h"
#include <string.h>
#include <float.h>

#ifdef _MSC_VER
#include <intrin.h>
#else
#include <x86intrin.h>
#endif

void tempo_queue_init(tempo_queue_t *q) {
    q->count = 0;
    memset(q->entries, 0, sizeof(q->entries));
}

int tempo_queue_push(tempo_queue_t *q, const nvme_sq_entry_t *sqe, double arrival_time_us) {
    if (q->count >= MAX_QUEUE_DEPTH) {
        return -1; /* Queue full */
    }

    tempo_request_t *req = &q->entries[q->count];
    memcpy(&req->sqe, sqe, sizeof(nvme_sq_entry_t));
    req->arrival_time_us = arrival_time_us;
    req->tier = tempo_decode_tier(sqe->cdw13);
    req->slack_us = tempo_decode_slack_us(sqe->cdw13);
    req->seq_id = tempo_decode_seq_id(sqe->cdw13);
    req->deadline_us = arrival_time_us + (double)req->slack_us;
    req->predicted_delay_us = 0.0;
    req->score = 0.0;

    q->count++;
    return 0;
}

int tempo_queue_remove(tempo_queue_t *q, uint32_t index, tempo_request_t *out_req) {
    if (index >= q->count) return -1;

    if (out_req) {
        memcpy(out_req, &q->entries[index], sizeof(tempo_request_t));
    }

    /* Shift remaining entries left */
    for (uint32_t i = index; i < q->count - 1; i++) {
        q->entries[i] = q->entries[i + 1];
    }
    q->count--;
    return 0;
}

/* Arbitrates among pending requests in the queue according to selected policy */
int tempo_arbitrate(tempo_queue_t *q, const nand_backend_t *backend, double now_us, scheduler_policy_t policy, uint64_t *out_cycles) {
    if (q->count == 0) return -1;

    uint64_t start_cycles = __rdtsc();
    int best_idx = -1;

    switch (policy) {
        case POLICY_FIFO: {
            /* S0: Select the earliest arrived request */
            double earliest_arrival = DBL_MAX;
            for (uint32_t i = 0; i < q->count; i++) {
                if (q->entries[i].arrival_time_us < earliest_arrival) {
                    earliest_arrival = q->entries[i].arrival_time_us;
                    best_idx = (int)i;
                }
            }
            break;
        }

        case POLICY_AI_PRIORITY: {
            /* S1: Priority Tier strictly (CRITICAL > NORMAL > BACKGROUND), FIFO tie-break */
            ai_priority_tier_t best_tier = AI_PRIORITY_BACKGROUND + 1;
            double earliest_arrival = DBL_MAX;

            for (uint32_t i = 0; i < q->count; i++) {
                ai_priority_tier_t tier = q->entries[i].tier;
                double arr = q->entries[i].arrival_time_us;

                if (tier < best_tier) {
                    best_tier = tier;
                    earliest_arrival = arr;
                    best_idx = (int)i;
                } else if (tier == best_tier && arr < earliest_arrival) {
                    earliest_arrival = arr;
                    best_idx = (int)i;
                }
            }
            break;
        }

        case POLICY_SSD_STATE: {
            /* S2: Greedy Shortest Channel/Die Service Delay */
            double min_delay = DBL_MAX;

            for (uint32_t i = 0; i < q->count; i++) {
                uint64_t slba = nvme_sqe_get_slba(&q->entries[i].sqe);
                uint32_t nlb = nvme_sqe_get_nlb(&q->entries[i].sqe);
                int is_write = (q->entries[i].sqe.opcode == NVME_CMD_WRITE);

                double delay = nand_backend_predict_delay(backend, slba, nlb, now_us, is_write);
                q->entries[i].predicted_delay_us = delay;

                if (delay < min_delay) {
                    min_delay = delay;
                    best_idx = (int)i;
                }
            }
            break;
        }

        case POLICY_TEMPO: {
            /* S3: Joint AI Urgency + Channel Readiness + Slack Pressure */
            double best_score = -DBL_MAX;

            /* First pass: find highest tier present in queue */
            ai_priority_tier_t highest_tier = AI_PRIORITY_BACKGROUND;
            for (uint32_t i = 0; i < q->count; i++) {
                if (q->entries[i].tier < highest_tier) {
                    highest_tier = q->entries[i].tier;
                }
            }

            for (uint32_t i = 0; i < q->count; i++) {
                tempo_request_t *req = &q->entries[i];
                /* Only evaluate candidates belonging to the highest available tier */
                if (req->tier > highest_tier) continue;

                uint64_t slba = nvme_sqe_get_slba(&req->sqe);
                uint32_t nlb = nvme_sqe_get_nlb(&req->sqe);
                int is_write = (req->sqe.opcode == NVME_CMD_WRITE);

                double delay = nand_backend_predict_delay(backend, slba, nlb, now_us, is_write);
                req->predicted_delay_us = delay;

                /* 1. Base Urgency Tier Weight */
                double tier_base = 0.0;
                if (req->tier == AI_PRIORITY_CRITICAL) {
                    tier_base = 100000.0;
                } else if (req->tier == AI_PRIORITY_NORMAL) {
                    tier_base = 10000.0;
                } else {
                    tier_base = 1000.0;
                }

                /* 2. Dynamic Slack Urgency */
                double remaining_slack = req->deadline_us - now_us;
                double slack_score = 0.0;

                if (remaining_slack > 0.0) {
                    /* Higher urgency as remaining slack tightens */
                    slack_score = 5000.0 / (remaining_slack + 10.0);
                } else {
                    /* Deadline already expired; demote to avoid wasting scarce channel slots */
                    slack_score = -5000.0;
                }

                /* 3. Hardware Channel Readiness Delay Penalty */
                /* Scale delay penalty: 1 µs delay costs 10 points */
                double delay_penalty = delay * 10.0;

                /* 4. Arrival Age Tie-breaker */
                double age_bonus = (now_us - req->arrival_time_us) * 0.1;

                double total_score = tier_base + slack_score - delay_penalty + age_bonus;
                req->score = total_score;

                if (total_score > best_score) {
                    best_score = total_score;
                    best_idx = (int)i;
                }
            }
            break;
        }
    }

    uint64_t end_cycles = __rdtsc();
    if (out_cycles) {
        *out_cycles = (end_cycles >= start_cycles) ? (end_cycles - start_cycles) : 0;
    }

    return best_idx;
}
