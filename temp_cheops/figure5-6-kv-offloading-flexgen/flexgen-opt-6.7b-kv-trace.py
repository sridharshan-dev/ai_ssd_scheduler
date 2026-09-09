import argparse
import os.path
from time import sleep

from proc import *

# python3 flexgen-opt-6.7b-kv-trace.py --bs 1 --fs ext4 --run > flexgen-opt-6.7b-kv-trace-bs-1-ext4-log.txt

OFFLOAD_DIR = '/mnt/nvmevirt/flexgen-offload'
FLEXGEN_CMD = f'sudo systemd-run --scope --property=MemoryLimit=10G /home/z_ren/anaconda3/envs/flexgen/bin/python3 -m flexllmgen.flex_opt --model facebook/opt-6.7b --path _DUMMY_ --offload-dir {OFFLOAD_DIR} --prompt-len 256 --gen-len 256 --num-gpu-batches 1 --percent 100 0 0 0 100 0'

RESULT_DIR = 'flexgen-kv-offload-opt-6.7b-bs-{}-{}-trace'

parser = argparse.ArgumentParser()
parser.add_argument('--run',
                    action='store_true',
                    default=False,
                    help='Execute the commands')
parser.add_argument('--fs', type=str, default='', help='File system')
parser.add_argument('--bs', type=int, default=1, help='Batch size')
args = parser.parse_args()

RUN = args.run
BS = args.bs
FS = args.fs

assert (FS in ['ext4', 'xfs'])

# Create the result directory
result_dir = RESULT_DIR.format(BS, FS)
if not os.path.exists(result_dir):
    os.makedirs(result_dir)

results_file_flexgen = 'opt-6.7b-kv-offload-bs-{}-{}.txt'.format(BS, FS)
results_file_bpftrace = 'opt-6.7b-kv-offload-bs-{}-{}-bpftrace-block.txt'.format(
    BS, FS)
results_file_gpu = 'opt-6.7b-kv-offload-bs-{}-{}-gpu.txt'.format(BS, FS)
results_file_flexgen = os.path.join(result_dir, results_file_flexgen)
results_file_bpftrace = os.path.join(result_dir, results_file_bpftrace)
results_file_gpu = os.path.join(result_dir, results_file_gpu)

flexgen_cmd = f'{FLEXGEN_CMD} --gpu-batch-size {BS} > {results_file_flexgen} 2>&1'
gpu_util_monitor_cmd = f'nvidia-smi --query-gpu=timestamp,utilization.gpu --format=csv -lms 200 > {results_file_gpu} 2>&1'
bpftrace_cmd = f'sudo bpftrace ../bpftrace-scripts/bio-bite-size.bt > {results_file_bpftrace} 2>&1'

p_inference = exec_cmd_background(flexgen_cmd, run=RUN)
p_gpu_util = exec_cmd_background(gpu_util_monitor_cmd, run=RUN)
p_bpftrace = exec_cmd_background(bpftrace_cmd, run=RUN)

if RUN:
    p_inference.wait()
    kill_process_and_children(p_gpu_util.pid)
    exec_cmd(f'sudo kill {p_bpftrace.pid}', run=RUN)
    p_bpftrace.kill()
