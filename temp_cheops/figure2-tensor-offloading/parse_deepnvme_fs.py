from plot import *
import argparse
import os.path
import os
from time import sleep

RESULT_DIR = 'deepnvme-results'
SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]  # in MB
EXPR_CMD = {
    'store-cpu': '_store_cpu_tensor.py',
    'load-cpu': '_load_cpu_tensor.py',
    'store-gpu': '_store_gpu_tensor.py',
    'load-gpu': '_load_gpu_tensor.py'
}

parser = argparse.ArgumentParser()
parser.add_argument('--fs', action='store', default='', help='File system')
args = parser.parse_args()
FS = args.fs

RESULT_DIR = f'{RESULT_DIR}-{FS}'

# parse single file

def parse_deepnvme_file(fname):
    f = open(fname, 'r')
    lines = f.readlines()
    f.close()

    result = lines[-1].strip().split(',')[-1].strip()
    result = float(result.split(' ')[0])

    return result


all_bandwidths = {}
for ENGINE in ['py', 'aio']:
    all_bandwidths[ENGINE] = {}
    # store
    for EXPR in ['store-cpu', 'store-gpu']:
        all_bandwidths[ENGINE][EXPR] = []
        for cur_size in SIZES:
            cur_result_file = f'deepnvme-{ENGINE}-{FS}-{EXPR}-{cur_size}-mb.txt'
            cur_result_file = os.path.join(RESULT_DIR, f'{ENGINE}-{EXPR}',
                                           cur_result_file)
            cur_bw = parse_deepnvme_file(cur_result_file)
            all_bandwidths[ENGINE][EXPR].append(cur_bw)

    # load
    for EXPR in ['load-cpu', 'load-gpu']:
        all_bandwidths[ENGINE][EXPR] = []
        for cur_size in SIZES:
            cur_result_file = f'deepnvme-{ENGINE}-{FS}-{EXPR}-{cur_size}-mb.txt'
            cur_result_file = os.path.join(RESULT_DIR, f'{ENGINE}-{EXPR}',
                                           cur_result_file)
            cur_bw = parse_deepnvme_file(cur_result_file)
            all_bandwidths[ENGINE][EXPR].append(cur_bw)


# Load
if True:
    # Data, set unused value to none
    fig_save_path = f'deepnvme-load-{FS}.pdf'
    group_list = ['py-cpu', 'py-gpu', 'aio-cpu', 'aio-gpu']
    y_values = {'py-cpu': all_bandwidths['py']['load-cpu'],
                'py-gpu': all_bandwidths['py']['load-gpu'],
                'aio-cpu': all_bandwidths['aio']['load-cpu'],
                'aio-gpu': all_bandwidths['aio']['load-gpu']}
    std_dev = None  # {'group1': prefill_throughput_std}
    x_ticks = SIZES
    legend_label = {'py-cpu': 'py-cpu', 'py-gpu': 'py-gpu',
                    'aio-cpu': 'aio-cpu', 'aio-gpu': 'aio-gpu'}

    title = None
    xlabel = 'Size (MiB)'
    ylabel = 'Bandwidth (GiB/s)'

    # Parameters
    linewidth = 4
    markersize = 15

    datalabel_size = 26
    datalabel_va = 'bottom'
    axis_tick_font_size = 34
    axis_label_font_size = 44
    legend_font_size = 30

    reset_color()
    fig, ax = plt.subplots(figsize=(12, 8))

    plt.xlabel(xlabel, fontsize=axis_label_font_size)
    plt.ylabel(ylabel, fontsize=axis_label_font_size)
    plt.grid(True)

    ax.tick_params(axis='both', which='major', labelsize=axis_tick_font_size)
    ax.set_xticks(range(1, len(x_ticks) + 1))
    ax.set_xticklabels([str(size) for size in x_ticks])

    for (index, group_name) in zip(range(len(group_list)), group_list):
        # x, y, std_dev, data_label = data[group_name]
        x = range(1, len(y_values[group_name]) + 1)
        y = y_values[group_name]
        yerr = None
        if std_dev:
            yerr = std_dev[group_name]

        plt.errorbar(
            x,
            y,
            yerr=yerr,
            label=legend_label[group_name],
            marker=dot_style[index % len(dot_style)],
            linewidth=linewidth,
            markersize=markersize,
            color=get_next_color(),
        )

    if legend_label != None:
        plt.legend(fontsize=legend_font_size, labelspacing=0.1)

    plt.savefig(fig_save_path, bbox_inches='tight')
    plt.close()

# Store
if True:
    # Data, set unused value to none
    fig_save_path = f'deepnvme-store-{FS}.pdf'
    group_list = ['py-cpu', 'py-gpu', 'aio-cpu', 'aio-gpu']
    y_values = {
        'py-cpu': all_bandwidths['py']['store-cpu'],
        'py-gpu': all_bandwidths['py']['store-gpu'],
        'aio-cpu': all_bandwidths['aio']['store-cpu'],
        'aio-gpu': all_bandwidths['aio']['store-gpu']
    }
    std_dev = None  # {'group1': prefill_throughput_std}
    x_ticks = SIZES
    legend_label = {
        'py-cpu': 'py-cpu',
        'py-gpu': 'py-gpu',
        'aio-cpu': 'aio-cpu',
        'aio-gpu': 'aio-gpu'
    }

    title = None
    xlabel = 'Tensor Size (MiB)'
    ylabel = 'Bandwidth (GiB/s)'

    # Parameters
    linewidth = 4
    markersize = 15

    datalabel_size = 26
    datalabel_va = 'bottom'
    axis_tick_font_size = 34
    axis_label_font_size = 44
    legend_font_size = 30

    reset_color()
    fig, ax = plt.subplots(figsize=(12, 8))

    plt.xlabel(xlabel, fontsize=axis_label_font_size)
    plt.ylabel(ylabel, fontsize=axis_label_font_size)
    plt.grid(True)

    ax.tick_params(axis='both', which='major', labelsize=axis_tick_font_size)
    ax.set_xticks(range(1, len(x_ticks) + 1))
    ax.set_xticklabels([str(size) for size in x_ticks])
    ax.tick_params(axis='x', labelrotation=45)
    # ax.xaxis.set_ticks()
    # ax.set_xlim()
    # ax.set_ylim()

    for (index, group_name) in zip(range(len(group_list)), group_list):
        # x, y, std_dev, data_label = data[group_name]
        x = range(1, len(y_values[group_name]) + 1)
        y = y_values[group_name]
        yerr = None
        if std_dev:
            yerr = std_dev[group_name]

        plt.errorbar(
            x,
            y,
            yerr=yerr,
            label=legend_label[group_name],
            marker=dot_style[index % len(dot_style)],
            linewidth=linewidth,
            markersize=markersize,
            color=get_next_color(),
        )

    if legend_label != None:
        plt.legend(fontsize=legend_font_size,
                   labelspacing=0.1, loc='upper right')

    plt.savefig(fig_save_path, bbox_inches='tight')
    plt.close()
