#include "nand_backend.h"
#include <string.h>
#include <stdio.h>

#define MAX(a, b) ((a) > (b) ? (a) : (b))

void nand_backend_init(nand_backend_t *backend) {
    memset(backend, 0, sizeof(nand_backend_t));
}

/* Predicts service completion delay for a request without mutating channel/die state */
double nand_backend_predict_delay(const nand_backend_t *backend, uint64_t slba, uint32_t nlb, double now_us, int is_write) {
    if (nlb == 0) return NAND_T_FW_US;

    uint64_t start_page = slba / NAND_SECTORS_PER_PAGE;
    uint64_t end_page = (slba + nlb - 1) / NAND_SECTORS_PER_PAGE;
    uint32_t num_pages = (uint32_t)(end_page - start_page + 1);

    /* Local copy of channel bus and LUN busy timers for accurate multi-page serialization */
    double temp_bus_busy[NAND_NUM_CHANNELS];
    double temp_lun_busy[NAND_NUM_CHANNELS][NAND_LUNS_PER_CHANNEL];

    for (int c = 0; c < NAND_NUM_CHANNELS; c++) {
        temp_bus_busy[c] = backend->channels[c].bus_busy_until_us;
        for (int l = 0; l < NAND_LUNS_PER_CHANNEL; l++) {
            temp_lun_busy[c][l] = backend->channels[c].luns[l].busy_until_us;
        }
    }

    double max_page_finish = now_us;

    for (uint32_t i = 0; i < num_pages; i++) {
        uint64_t p = start_page + i;
        uint32_t ch_id = (uint32_t)(p % NAND_NUM_CHANNELS);
        uint32_t lun_id = (uint32_t)((p / NAND_NUM_CHANNELS) % NAND_LUNS_PER_CHANNEL);

        double page_finish = now_us;

        if (!is_write) {
            /* READ: Die Sensing -> Bus DMA Transfer */
            double sense_start = MAX(now_us, temp_lun_busy[ch_id][lun_id]);
            double sense_finish = sense_start + NAND_T_R_US;
            temp_lun_busy[ch_id][lun_id] = sense_finish;

            double xfer_start = MAX(sense_finish, temp_bus_busy[ch_id]);
            double xfer_finish = xfer_start + NAND_T_XFER_US;
            temp_bus_busy[ch_id] = xfer_finish;

            page_finish = xfer_finish;
        } else {
            /* WRITE: Bus DMA Transfer -> Die Program */
            double xfer_start = MAX(now_us, temp_bus_busy[ch_id]);
            double xfer_finish = xfer_start + NAND_T_XFER_US;
            temp_bus_busy[ch_id] = xfer_finish;

            double prog_start = MAX(xfer_finish, temp_lun_busy[ch_id][lun_id]);
            double prog_finish = prog_start + NAND_T_PROG_US;
            temp_lun_busy[ch_id][lun_id] = prog_finish;

            page_finish = prog_finish;
        }

        if (page_finish > max_page_finish) {
            max_page_finish = page_finish;
        }
    }

    double total_delay = (max_page_finish - now_us) + NAND_T_FW_US;
    return total_delay > 0.0 ? total_delay : NAND_T_FW_US;
}

/* Commits request execution to the NAND backend, advancing hardware state timers */
double nand_backend_dispatch(nand_backend_t *backend, uint64_t slba, uint32_t nlb, double now_us, int is_write) {
    if (nlb == 0) return now_us + NAND_T_FW_US;

    uint64_t start_page = slba / NAND_SECTORS_PER_PAGE;
    uint64_t end_page = (slba + nlb - 1) / NAND_SECTORS_PER_PAGE;
    uint32_t num_pages = (uint32_t)(end_page - start_page + 1);

    double max_page_finish = now_us;

    for (uint32_t i = 0; i < num_pages; i++) {
        uint64_t p = start_page + i;
        uint32_t ch_id = (uint32_t)(p % NAND_NUM_CHANNELS);
        uint32_t lun_id = (uint32_t)((p / NAND_NUM_CHANNELS) % NAND_LUNS_PER_CHANNEL);

        nand_channel_t *ch = &backend->channels[ch_id];
        nand_lun_t *lun = &ch->luns[lun_id];

        double page_finish = now_us;

        if (!is_write) {
            /* READ: Die Sensing -> Bus DMA Transfer */
            double sense_start = MAX(now_us, lun->busy_until_us);
            double sense_finish = sense_start + NAND_T_R_US;
            lun->busy_until_us = sense_finish;
            lun->current_op = NAND_OP_READ;
            lun->op_count++;

            double xfer_start = MAX(sense_finish, ch->bus_busy_until_us);
            double xfer_finish = xfer_start + NAND_T_XFER_US;
            ch->bus_busy_until_us = xfer_finish;
            ch->page_transfers++;

            page_finish = xfer_finish;
            backend->total_read_pages++;
        } else {
            /* WRITE: Bus DMA Transfer -> Die Program */
            double xfer_start = MAX(now_us, ch->bus_busy_until_us);
            double xfer_finish = xfer_start + NAND_T_XFER_US;
            ch->bus_busy_until_us = xfer_finish;
            ch->page_transfers++;

            double prog_start = MAX(xfer_finish, lun->busy_until_us);
            double prog_finish = prog_start + NAND_T_PROG_US;
            lun->busy_until_us = prog_finish;
            lun->current_op = NAND_OP_WRITE;
            lun->op_count++;

            page_finish = prog_finish;
            backend->total_write_pages++;
        }

        if (page_finish > max_page_finish) {
            max_page_finish = page_finish;
        }
    }

    return max_page_finish + NAND_T_FW_US;
}

/* Injects background GC erase operation onto a target channel/LUN */
void nand_backend_inject_gc(nand_backend_t *backend, uint32_t ch_idx, uint32_t lun_idx, double now_us, double erase_us) {
    if (ch_idx >= NAND_NUM_CHANNELS || lun_idx >= NAND_LUNS_PER_CHANNEL) return;

    nand_lun_t *lun = &backend->channels[ch_idx].luns[lun_idx];
    double start_us = MAX(now_us, lun->busy_until_us);
    lun->busy_until_us = start_us + erase_us;
    lun->current_op = NAND_OP_ERASE;
    lun->op_count++;
    backend->total_erase_cycles++;
}

void nand_backend_get_mapping(uint64_t slba, uint32_t *out_ch, uint32_t *out_lun, uint32_t *out_page) {
    uint64_t start_page = slba / NAND_SECTORS_PER_PAGE;
    if (out_ch) *out_ch = (uint32_t)(start_page % NAND_NUM_CHANNELS);
    if (out_lun) *out_lun = (uint32_t)((start_page / NAND_NUM_CHANNELS) % NAND_LUNS_PER_CHANNEL);
    if (out_page) *out_page = (uint32_t)start_page;
}
