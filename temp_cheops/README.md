# [ARTIFACT] CHEOPS'25 An I/O Characterizing Study of Offloading LLM Models and KV Caches to NVMe SSD

This repo is the artifact of CHEOPS'25 An I/O Characterizing Study of Offloading LLM Models and KV Caches to NVMe SSD.

## Environment Setup

Install conda

```bash
wget https://repo.anaconda.com/archive/Anaconda3-2024.02-1-Linux-x86_64.sh
chmod +x Anaconda3-2024.02-1-Linux-x86_64.sh 
./Anaconda3-2024.02-1-Linux-x86_64.sh
conda create --name llm-storage python=3.11.10
conda install pip
conda install -c conda-forge gcc=12.1.0
```

Please refer to this link to install the CUDA driver: [https://docs.nvidia.com/cuda/archive/12.0.0/cuda-installation-guide-linux/index.html](https://docs.nvidia.com/cuda/archive/12.0.0/cuda-installation-guide-linux/index.html)

### Install DeepSpeed

Tutorial: [https://github.com/microsoft/DeepSpeedExamples/blob/master/inference/huggingface/zero_inference/README.md](https://github.com/microsoft/DeepSpeedExamples/blob/master/inference/huggingface/zero_inference/README.md)

```bash
sudo apt install libaio-dev
sudo apt install ninja-build

# create and activate the conda environment

conda install python=3.11.10
conda install pip
export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/:$LD_LIBRARY_PATH

# Install the requirements from: https://github.com/microsoft/DeepSpeedExamples/blob/master/inference/huggingface/zero_inference/
pip install -r requirements.txt

# run ds_report to check if async_io is successfully installed
```


### Install FlexGen

```bash
conda create  --name flexgen
conda activate flexgen
conda install pip
conda install python=3.11.10

# Install pytorch, use nvidia-smi to check CUDA version. https://pytorch.org/get-started/locally/

# Install flexgen: https://github.com/FMInference/FlexLLMGen?tab=readme-ov-file#installation
```

### bpftrace setup

bpftrace install tutorial: https://github.com/bpftrace/bpftrace/tree/master

Then go to //bpftrace-scripts and change the major and minor number to the major and minor number where the models and KV cache are offloaded to in the following experiments.

### NVMeVirt Setup

If you are using a NVMeVirt virtual device, please refer to [https://github.com/snu-csl/nvmevirt](https://github.com/snu-csl/nvmevirt) for the installation and setup guide.

## Figure 2: Tensor Offloading

Download the following codes and put them in the figure2-tensor-offloading directory:
[https://github.com/deepspeedai/DeepSpeedExamples/tree/master/deepnvme](https://github.com/deepspeedai/DeepSpeedExamples/tree/master/deepnvme)

Then modify:
* line 7: the directory that the offloded tensors will be read from/written to.
* line 8: the python binary that supports the DeepSpeed framework.

```bash
cd figure2-tensor-offloading

# run the experiments
# NOTE the --fs option is only an identifier that indicates which filesystem is used, it will not reformat the file system.
python3 run_deepnvme.py --run --fs YOUR_FILE_SYSTEM

# Plot the results
python3 parse_deepnvme_fs.py --fs YOUR_FILE_SYSTEM
```

## Figure 3: Model Offloading: DeepSpeed

Download the following file from DeepSpeed examples [https://github.com/deepspeedai/DeepSpeedExamples/tree/master/inference/huggingface/zero_inference](https://github.com/deepspeedai/DeepSpeedExamples/tree/master/inference/huggingface/zero_inference):
* run_model.sh
* timer.py
* utils.py
And copy them to the 'figure3-model-offloading-deepspeed' directory.

Then modify:
* line 9: the offload dir
* line 10: change the python path to the binary of the conda environemnt where DeepSpeed is installed.

```bash
# Run the experiments
# Note that the --fs is simply an indicator on which file system is being used, it will not re-format the file system
# If error ‘Deepspeed inference error: ModuleNotFoundError: No module named 'transformers.integrations.deepspeed'; 'transformers.integrations' is not a package’
# Change that import to ‘from transformers.deepspeed import xxx’
python3 deepspeed-opt-13b-io-trace-block.py --fs YOUR_FILE_SYSTEM --bs BATCH_SIZE --run

# Plot the results
python3 deepspeed-opt-13b-io-trace-parse.py --fs YOUR_FILE_SYSTEM --bs BATCH_SIZE
```

## Figure 4: Model Offloading: FlexGen

Modify the following lines:
* line 9: the offload dir
* line 10: replace the python path with the binary that where the FlexGen is installed.

```bash
# Run the experiments
# Note Note that the --fs is simply an indicator on which file system is being used, it will not re-format the file system
python3 flexgen-opt30b-model-trace-block.py --fs YOUR_FILE_SYSTEM --bs BATCH_SIZE --run

# Plot
python3 flexgen-opt-30b-io-trace-parse.py --fs YOUR_FILE_SYSTEM --bs BATCH_SIZE
```

## Figure 5 & 6: KV cache offloding: FlexGen

Modify the following lines:
* line 9: the offload dir
* line 10: replace the python path with the binary that where the FlexGen is installed.

```bash
# Run the experiments
# Note Note that the --fs is simply an indicator on which file system is being used, it will not re-format the file system
python3 flexgen-opt-6.7b-kv-trace.py --fs YOUR_FILE_SYSTEM --bs BATCH_SIZE --run

# Plot
python3 flexgen-opt-6.7b-kv-parse.py --fs YOUR_FILE_SYSTEM --bs BATCH_SIZE
```

# License
This code and artifact is distributed under the MIT license. 

```
MIT License

Copyright (c) 2025 StoNet Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```