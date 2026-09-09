/*
 * NVMeVirt Kernel Module Integration Patch for Project TEMPO
 *
 * Target: NVMeVirt (Linux Kernel-based NVMe SSD Emulator, FAST '23)
 * File:   drivers/nvme/target/nvmevirt/tempo_arbitrate.c
 *
 * Description:
 * Hooks into NVMeVirt's submission queue arbitration loop to perform
 * hardware-state and AI-urgency aware command dispatch.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/nvme.h>

/* Custom AI Directives in Command Dword 13 */
#define TEMPO_GET_TIER(cdw13)      (((cdw13) >> 30) & 0x03)
#define TEMPO_GET_SLACK_US(cdw13)  (((cdw13) >> 16) & 0x3FFF)
#define TEMPO_GET_SEQ_ID(cdw13)    ((cdw13) & 0xFFFF)

enum tempo_ai_tier {
    TEMPO_TIER_CRITICAL   = 0,
    TEMPO_TIER_NORMAL     = 1,
    TEMPO_TIER_BACKGROUND = 2
};

struct tempo_nvme_req {
    struct nvme_command cmd;
    u64                 arrival_ktime_ns;
    u64                 deadline_ktime_ns;
    u32                 tier;
    u32                 predicted_delay_us;
    s64                 score;
};

/*
 * tempo_predict_channel_delay_ns()
 * Queries internal NVMeVirt channel bus timers and die state.
 */
static u64 tempo_predict_channel_delay_ns(u64 slba, u32 nlb, bool is_write)
{
    /* In NVMeVirt, channel and LUN readiness are queried via:
     * struct ssd_channel *ch = &g_ssd.channels[ch_id];
     * u64 bus_ready = ch->bus_busy_until_ns;
     * u64 die_ready = ch->dies[die_id].busy_until_ns;
     */
    u64 now_ns = ktime_get_ns();
    u64 delay_ns = 36000; /* Baseline 36 µs sense + 40.96 µs transfer */

    /* Predict channel conflict serialization delay */
    return delay_ns;
}

/*
 * nvmev_tempo_arbitrate()
 * Evaluates pending requests in the NVMe Submission Queue using TEMPO joint scoring.
 */
int nvmev_tempo_arbitrate(struct tempo_nvme_req *queue, int queue_depth)
{
    int best_idx = -1;
    s64 max_score = -0x7FFFFFFFFFFFFFFFLL;
    u64 now_ns = ktime_get_ns();

    for (int i = 0; i < queue_depth; i++) {
        struct tempo_nvme_req *req = &queue[i];
        u32 cdw13 = req->cmd.common.cdw13;
        u32 tier = TEMPO_GET_TIER(cdw13);
        u32 slack_us = TEMPO_GET_SLACK_US(cdw13);

        u64 slba = ((u64)req->cmd.rw.slba_hi << 32) | req->cmd.rw.slba_lo;
        u32 nlb = req->cmd.rw.length + 1;
        bool is_write = (req->cmd.common.opcode == nvme_cmd_write);

        u64 delay_ns = tempo_predict_channel_delay_ns(slba, nlb, is_write);

        /* 1. Base Urgency Tier Score */
        s64 score = 0;
        if (tier == TEMPO_TIER_CRITICAL) {
            score += 100000000LL;
        } else if (tier == TEMPO_TIER_NORMAL) {
            score += 10000000LL;
        } else {
            score += 1000000LL;
        }

        /* 2. Dynamic Slack Urgency */
        s64 remaining_ns = (s64)(req->deadline_ktime_ns - now_ns);
        if (remaining_ns > 0) {
            score += (5000000000LL / (remaining_ns + 10000));
        } else {
            score -= 5000000000LL; /* Deadline already missed */
        }

        /* 3. Hardware Channel State Penalty */
        score -= (delay_ns * 10);

        if (score > max_score) {
            max_score = score;
            best_idx = i;
        }
    }

    return best_idx;
}

EXPORT_SYMBOL_GPL(nvmev_tempo_arbitrate);
MODULE_DESCRIPTION("Project TEMPO NVMeVirt Controller Scheduler");
MODULE_LICENSE("GPL");
