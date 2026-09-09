import argparse
import os.path
import os
from time import sleep
from proc import *

OFFLOAD_DIR = '/mnt/nvmevirt/deepnvme'
PYTHON = '/home/z_ren/anaconda3/envs/deepspeed-inference/bin/python'

EXPR_DIR = 'deepnvme/file_access/'
RESULT_DIR = 'deepnvme-results'
REP = 5
SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096] # in MB

EXPR_CMD = {
    'store-cpu': '_store_cpu_tensor.py',
    'load-cpu': '_load_cpu_tensor.py',
    'store-gpu': '_store_gpu_tensor.py',
    'load-gpu': '_load_gpu_tensor.py'
}


parser = argparse.ArgumentParser()
parser.add_argument('--run',
                    action='store_true',
                    default=False,
                    help='Execute the commands')
parser.add_argument('--fs', action='store', default='', help='File system')

args = parser.parse_args()
RUN = args.run
FS = args.fs

RESULT_DIR = f'{RESULT_DIR}-{FS}'
os.makedirs(RESULT_DIR, exist_ok=True)

exec_cmd('lsblk -f', run=RUN)

for ENGINE in ['py', 'aio']:
    # store
    for EXPR in ['store-cpu', 'store-gpu']:
        CMD = f'{ENGINE}{EXPR_CMD[EXPR]}'
        CMD = os.path.join(EXPR_DIR, CMD)
        os.makedirs(os.path.join(RESULT_DIR, f'{ENGINE}-{EXPR}'),
                    exist_ok=True)
        for cur_size in SIZES:
            cur_result_file = f'deepnvme-{ENGINE}-{FS}-{EXPR}-{cur_size}-mb.txt'
            cur_result_file = os.path.join(RESULT_DIR, f'{ENGINE}-{EXPR}', cur_result_file)
            cur_cmd = f'{PYTHON} {CMD} --nvme_folder {OFFLOAD_DIR} --mb_size {cur_size} --loop {REP} > {cur_result_file} 2>&1'
            exec_cmd(cur_cmd, run=RUN)

    # load
    for cur_size in SIZES:
        # first make the files to be load
        init_cmd = os.path.join(EXPR_DIR, f'py{EXPR_CMD["store-cpu"]}')
        cur_write_cmd = f'{PYTHON} {init_cmd} --nvme_folder {OFFLOAD_DIR} --mb_size {cur_size} --loop 1'
        exec_cmd(cur_write_cmd, run=RUN)
    for EXPR in ['load-cpu', 'load-gpu']:
        CMD = f'{ENGINE}{EXPR_CMD[EXPR]}'
        CMD = os.path.join(EXPR_DIR, CMD)
        os.makedirs(os.path.join(RESULT_DIR, f'{ENGINE}-{EXPR}'),
                    exist_ok=True)
        for cur_size in SIZES:
            cur_result_file = f'deepnvme-{ENGINE}-{FS}-{EXPR}-{cur_size}-mb.txt'
            cur_result_file = os.path.join(RESULT_DIR, f'{ENGINE}-{EXPR}',
                                           cur_result_file)
            cur_read_file = f'test_ouput_{cur_size}MB.pt'
            cur_cmd = f'{PYTHON} {CMD} --input_file {os.path.join(OFFLOAD_DIR, cur_read_file)} --loop {REP} > {cur_result_file} 2>&1'
            exec_cmd(cur_cmd, run=RUN)
