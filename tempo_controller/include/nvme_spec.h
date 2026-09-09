#ifndef NVME_SPEC_H
#define NVME_SPEC_H

#include <stdint.h>
#include <stddef.h>

/* Standard NVMe Opcode Definitions */
#define NVME_CMD_FLUSH       0x00
#define NVME_CMD_WRITE       0x01
#define NVME_CMD_READ        0x02
#define NVME_CMD_DATASET_MGMT 0x0A

/* Project TEMPO AI Priority Tiers (Encoded in CDW13 bits [31:30]) */
typedef enum {
    AI_PRIORITY_CRITICAL   = 0x00, /* Next-token KV block lookup / critical decode */
    AI_PRIORITY_NORMAL     = 0x01, /* Batch prefetch, model weight staging */
    AI_PRIORITY_BACKGROUND = 0x02  /* Checkpoint writes, logging, background GC */
} ai_priority_tier_t;

/* Standard 64-Byte NVMe Submission Queue Entry (SQE) */
#pragma pack(push, 1)
typedef struct {
    uint8_t   opcode;       /* Byte 0: Opcode */
    uint8_t   flags;        /* Byte 1: Fused operation & PRPs */
    uint16_t  cid;          /* Bytes 2-3: Command Identifier */
    uint32_t  nsid;         /* Bytes 4-7: Namespace Identifier (1) */
    uint64_t  reserved1;    /* Bytes 8-15: Reserved */
    uint64_t  mptr;         /* Bytes 16-23: Metadata Pointer */
    uint64_t  prp1;         /* Bytes 24-31: PRP Entry 1 */
    uint64_t  prp2;         /* Bytes 32-39: PRP Entry 2 */
    uint32_t  cdw10;        /* Bytes 40-43: Starting LBA (SLBA) Lower 32 bits */
    uint32_t  cdw11;        /* Bytes 44-47: Starting LBA (SLBA) Upper 32 bits */
    uint32_t  cdw12;        /* Bytes 48-51: Number of Logical Blocks (NLB, 0-based) */
    uint32_t  cdw13;        /* Bytes 52-55: TEMPO Custom AI Directive */
    uint32_t  cdw14;        /* Bytes 56-59: Command Dword 14 */
    uint32_t  cdw15;        /* Bytes 60-63: Command Dword 15 */
} nvme_sq_entry_t;
#pragma pack(pop)

/* Verify 64-byte SQE layout at compile time */
typedef char __check_nvme_sqe_size[sizeof(nvme_sq_entry_t) == 64 ? 1 : -1];

/* Standard 16-Byte NVMe Completion Queue Entry (CQE) */
#pragma pack(push, 1)
typedef struct {
    uint32_t  result;       /* Bytes 0-3: Command Specific Result */
    uint32_t  reserved;     /* Bytes 4-7: Reserved */
    uint16_t  sq_head;      /* Bytes 8-9: Submission Queue Head Pointer */
    uint16_t  sq_id;        /* Bytes 10-11: Submission Queue ID */
    uint16_t  cid;          /* Bytes 12-13: Command Identifier */
    uint16_t  status;       /* Bytes 14-15: Phase Tag & Status Field */
} nvme_cq_entry_t;
#pragma pack(pop)

typedef char __check_nvme_cqe_size[sizeof(nvme_cq_entry_t) == 16 ? 1 : -1];

/* Helper functions for TEMPO CDW13 encoding/decoding */
static inline uint32_t tempo_encode_cdw13(ai_priority_tier_t tier, uint16_t slack_us, uint16_t seq_id) {
    uint32_t cdw13 = 0;
    cdw13 |= ((uint32_t)(tier & 0x03)) << 30;           /* Bits 31:30 - Priority Tier */
    cdw13 |= ((uint32_t)(slack_us & 0x3FFF)) << 16;      /* Bits 29:16 - Deadline Slack (0-16383 µs) */
    cdw13 |= ((uint32_t)(seq_id & 0xFFFF));              /* Bits 15:0  - Sequence ID */
    return cdw13;
}

static inline ai_priority_tier_t tempo_decode_tier(uint32_t cdw13) {
    return (ai_priority_tier_t)((cdw13 >> 30) & 0x03);
}

static inline uint16_t tempo_decode_slack_us(uint32_t cdw13) {
    return (uint16_t)((cdw13 >> 16) & 0x3FFF);
}

static inline uint16_t tempo_decode_seq_id(uint32_t cdw13) {
    return (uint16_t)(cdw13 & 0xFFFF);
}

static inline uint64_t nvme_sqe_get_slba(const nvme_sq_entry_t *sqe) {
    return (((uint64_t)sqe->cdw11) << 32) | (uint64_t)sqe->cdw10;
}

static inline uint32_t nvme_sqe_get_nlb(const nvme_sq_entry_t *sqe) {
    return sqe->cdw12 + 1; /* NVMe NLB is 0-based */
}

#endif /* NVME_SPEC_H */
