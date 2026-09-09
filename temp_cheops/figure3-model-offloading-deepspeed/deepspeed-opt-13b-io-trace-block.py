import argparse
import os.path
from time import sleep

from proc import *

# python3 deepspeed-opt-13b-io-trace-block.py --fs xfs -bs 1 --run > deepspeed-opt-13b-io-trace-block-xfs-bs-1-log.txt 2>&1

OFFLOAD_DIR = '/mnt/nvmevirt/deepspeed-offload'
deepspeed_cmd = f'/home/z_ren/anaconda3/envs/deepspeed-inference/bin/deepspeed --num_gpus 1 run_model.py --dummy --model facebook/opt-13b --cpu-offload  --disk-offload --offload-dir {OFFLOAD_DIR}  --prompt-len 256 --gen-len 32 --loops 1'

RESULT_DIR = 'deepspeed-model-offloading-opt-13b-bs-{}-{}-trace'

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

result_dir = RESULT_DIR.format(BS, FS)
if not os.path.exists(result_dir):
    os.makedirs(result_dir)

results_file_deepspeed = 'opt-13b-model-offload-bs-{}-{}.txt'.format(BS, FS)
results_file_bpftrace = 'opt-13b-model-offload-bs-{}-{}-bpftrace-block.txt'.format(
    BS, FS)
results_file_gpu = 'opt-13b-model-offload-bs-{}-{}-gpu.txt'.format(BS, FS)
results_file_deepspeed= os.path.join(result_dir, results_file_deepspeed)
results_file_bpftrace = os.path.join(result_dir, results_file_bpftrace)
results_file_gpu = os.path.join(result_dir, results_file_gpu)

deepspeed_cmd = f'{deepspeed_cmd} --batch-size {BS}  >> {results_file_deepspeed} 2>&1'
gpu_util_monitor_cmd = f'nvidia-smi --query-gpu=timestamp,utilization.gpu --format=csv -lms 200 > {results_file_gpu} 2>&1'
bpftrace_cmd = f'sudo bpftrace ../bpftrace-scripts/bio-bite-size.bt > {results_file_bpftrace} 2>&1'

p_inference = exec_cmd_background(deepspeed_cmd, run=RUN)
p_gpu_util = exec_cmd_background(gpu_util_monitor_cmd, run=RUN)
p_bpftrace = exec_cmd_background(bpftrace_cmd, run=RUN)
if RUN:
    p_inference.wait()
    kill_process_and_children(p_gpu_util.pid)
    exec_cmd(f'sudo kill {p_bpftrace.pid}', run=RUN)
    p_bpftrace.kill()
