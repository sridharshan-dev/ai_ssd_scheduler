#ifndef NAND_BACKEND_H
#define NAND_BACKEND_H

#include <stdint.h>
#include <stddef.h>

#define NAND_NUM_CHANNELS         8
#define NAND_LUNS_PER_CHANNEL     2
#define NAND_TOTAL_DIES           (NAND_NUM_CHANNELS * NAND_LUNS_PER_CHANNEL)
#define NAND_PAGE_SIZE_BYTES      32768
#define NAND_SECTOR_SIZE_BYTES    512
#define NAND_SECTORS_PER_PAGE     (NAND_PAGE_SIZE_BYTES / NAND_SECTOR_SIZE_BYTES) /* 64 sectors */

/* Samsung 970 Pro Published Flash Timing Baseline */
#define NAND_T_R_US               36.0    /* Cell sense latency */
#define NAND_T_PROG_US            185.0   /* Cell program latency */
#define NAND_T_BERS_US            3500.0  /* Block erase latency */
#define NAND_T_XFER_US            40.96   /* 32 KiB @ 800 MB/s bus */
#define NAND_T_FW_US              30.5    /* Controller firmware overhead */

typedef enum {
    NAND_OP_IDLE = 0,
    NAND_OP_READ,
    NAND_OP_WRITE,
    NAND_OP_ERASE
} nand_op_type_t;

typedef struct {
    double          busy_until_us;
    nand_op_type_t  current_op;
    uint32_t        op_count;
} nand_lun_t;

typedef struct {
    double      bus_busy_until_us;
    nand_lun_t  luns[NAND_LUNS_PER_CHANNEL];
    uint32_t    page_transfers;
} nand_channel_t;

typedef struct {
    nand_channel_t channels[NAND_NUM_CHANNELS];
    uint64_t       total_read_pages;
    uint64_t       total_write_pages;
    uint64_t       total_erase_cycles;
} nand_backend_t;

void   nand_backend_init(nand_backend_t *backend);
double nand_backend_predict_delay(const nand_backend_t *backend, uint64_t slba, uint32_t nlb, double now_us, int is_write);
double nand_backend_dispatch(nand_backend_t *backend, uint64_t slba, uint32_t nlb, double now_us, int is_write);
void   nand_backend_inject_gc(nand_backend_t *backend, uint32_t ch_idx, uint32_t lun_idx, double now_us, double erase_us);

#endif /* NAND_BACKEND_H */
