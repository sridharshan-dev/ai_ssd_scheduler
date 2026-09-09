import argparse
import os
import pickle as pkl
import numpy as np 

from parse import *

figure_save_dir = 'flexgen-model-figures/flexgen-mode-opt30b-bs-{}-{}'
RESULT_DIR = 'flexgen-model-offload-opt30b-bs-{}-{}-trace'

parser = argparse.ArgumentParser()
parser.add_argument('--fs',
                    type=str,
                    default='',
                    help='File system')
parser.add_argument('--bs',
                    type=int,
                    default=1,
                    help='Block size')
args = parser.parse_args()

BS = args.bs
FS = args.fs


# result
result_dir = RESULT_DIR.format(BS, FS)
results_file_flexgen = 'opt-30b-model-offload-bs-{}-{}.txt'.format(BS, FS)
results_file_bpftrace = 'opt-30b-model-offload-bs-{}-{}-bpftrace-block.txt'.format(
    BS, FS)
results_file_gpu = 'opt-30b-model-offload-bs-{}-{}-gpu.txt'.format(BS, FS)
flexgen_file = os.path.join(result_dir, results_file_flexgen)
bitesize_file = os.path.join(result_dir, results_file_bpftrace)
gpu_util_file = os.path.join(result_dir, results_file_gpu)

# save path etc
figure_save_dir = figure_save_dir.format(BS, FS)
if not os.path.exists(figure_save_dir):
    os.makedirs(figure_save_dir)

info_file = os.path.join(figure_save_dir, 'opt-30b-model-offload-bs-{}-{}-info.txt'.format(BS, FS))
gpu_util_save_path = os.path.join(
    figure_save_dir,
    'opt-30b-model-offload-bs-{}-{}-gpu_util.pdf'.format(BS, FS))
bitesize_save_prefix = os.path.join(figure_save_dir,
                                    'opt-30b-model-offload-bs-{}-{}-bitesize-'.format(BS, FS))
sector_access_count_prefix = os.path.join(figure_save_dir, 'opt-30b-model-offload-bs-{}-{}-sector-access-count-'.format(BS, FS))
sector_access_cdf_prefix = os.path.join(figure_save_dir, 'opt-30b-model-offload-bs-{}-{}-sector-access-cdf-'.format(BS, FS))
size_hist_op_prefix = os.path.join(figure_save_dir, 'opt-30b-model-offload-bs-{}-{}-size-hist-'.format(BS, FS))

info_file = open(info_file, 'w')

## args
GPU_RESOLUTION = 0.2  #s

gpu_util = parse_gpu_util(gpu_util_file)
average_gpu_util = sum(gpu_util) / len(gpu_util)
print(f"Average GPU Utilization: {average_gpu_util:.2f}%")
info_file.write(f"Average GPU Utilization: {average_gpu_util:.2f}%\n\n")

timestamps, op, bite_size, start_sector, num_sectors = parse_bite_size(
    bitesize_file) # timestamps is already in seconds
bite_size_by_op, bite_size_aggregated, io_size_by_sec = process_bite_size(
    timestamps, op, bite_size)

print('Bite size aggregated:')
for key in bite_size_aggregated:
    print(key)
    print('  ', bite_size_aggregated[key])
    info_file.write(key + '\n')
    info_file.write(str(bite_size_aggregated[key]) + '\n\n')
# print(io_size_by_sec['R'])

# Plot header
from plot import *

# plot GPU
if True:
    # Data, set unused value to none
    fig_save_path = gpu_util_save_path
    group_list = ['default']
    y_values = {'default': gpu_util}
    std_dev = None
    # x_ticks = ['xtick_1', 'xtick_1']
    legend_label = None

    title = None
    xlabel = 'Time'
    ylabel = 'GPU utilization (%)'

    # Parameters
    linewidth = 1
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

    for (index, group_name) in zip(range(len(group_list)), group_list):
        # x, y, std_dev, data_label = data[group_name]
        x = range(1, len(y_values[group_name]) + 1)
        x = [x * GPU_RESOLUTION for x in x]
        y = y_values[group_name]
        yerr = None
        if std_dev:
            yerr = std_dev[group_name]

        # TODO: Add this to the github plot repo
        if legend_label == None:
            cur_legend_label = 'placeholder'
        else:
            cur_legend_label = legend_label[group_name]

        plt.errorbar(
            x,
            y,
            yerr=yerr,
            label=cur_legend_label,
            linewidth=linewidth,
            markersize=markersize,
            color=get_next_color(),
        )

    if legend_label != None:
        plt.legend(fontsize=legend_font_size, labelspacing=0.1)


    plt.savefig(fig_save_path, bbox_inches='tight')
    plt.close()

# Plot total bite size (Read)
if True:
    fig_save_path = bitesize_save_prefix + 'total-read.pdf'
    table_data = [['size (KB)', 'count']]
    call_count = bite_size_aggregated['RA']
    keys = sorted(call_count.keys())
    for cur_bitesize in keys:
        table_data.append([cur_bitesize, call_count[cur_bitesize]])

    fig, ax = plt.subplots()

    # Hide axes
    ax.axis("tight")
    ax.axis("off")

    # Create the table
    table = ax.table(cellText=table_data,
                     colLabels=None,
                     loc="right",
                     cellLoc='right')
    # Adjust the layout
    plt.subplots_adjust(left=0.2, top=0.8)

    # Show the table
    plt.savefig(fig_save_path, bbox_inches='tight')
    plt.close()
    
# Size histogram
size_hist_op = ['RA', 'W']
if True:
    for cur_op in size_hist_op:
        cur_bite_size_aggregated = bite_size_aggregated[cur_op]
        fig_save_path = size_hist_op_prefix + cur_op + '.pdf'
        
        # x
        x = sorted(cur_bite_size_aggregated.keys())
        # y
        y = [cur_bite_size_aggregated[cur_size] for cur_size in x]
        
        group_list = ['group1']
        x_values = {'group1': x}
        y_values = {'group1': y}
        std_dev = None
        x_ticks = None # ['xtick_1', 'xtick_1']
        legend_label = {'group1': 'g1'}

        title = None
        xlabel = 'Bite size (KB)'
        ylabel = 'Count'

        # Parameters
        bar_width = 0.4

        datalabel_size = 26
        datalabel_va = 'bottom'
        axis_tick_font_size = 34
        axis_label_font_size = 44
        legend_font_size = 30

        # plot
        reset_color()
        fig, ax = plt.subplots(figsize=(12, 8))
        plt.grid(axis='y')  # x, y, both

        # set ticks
        if x_ticks:
            plt.xticks(list(np.arange(len(x_ticks))), x_ticks)

        if title:
            plt.title(title)

        if xlabel:
            plt.xlabel(xlabel, fontsize=axis_label_font_size)
        if ylabel:
            plt.ylabel(ylabel, fontsize=axis_label_font_size)

        ax.tick_params(axis='both', which='major', labelsize=axis_tick_font_size)

        # compute bar offset, with respect to center
        bar_offset = []
        mid_point = (len(group_list) * bar_width) / 2
        for i in range(len(group_list)):
            bar_offset.append(bar_width * i + 0.5 * bar_width - mid_point)

        
        # x_axis = np.arange(len(x_ticks))
        # draw figure by column
        for (index, group_name) in zip(range(len(group_list)), group_list):
            x_axis = x_values['group1']
            y = y_values[group_name]
            yerr = None
            if std_dev:
                yerr = std_dev[group_name]
            bar_pos = x_axis # + bar_offset[index]

            plt.bar(bar_pos,
                    y,
                    width=bar_width,
                    label=legend_label[group_name],
                    yerr=yerr,
                    color=get_next_color())


        # Legend: Change the ncol and loc to fine-tune the location of legend
        if legend_label != None:
            plt.legend(fontsize=legend_font_size)
        plt.savefig(fig_save_path, bbox_inches='tight')
        plt.close()

def avg(l):
    return sum(l) / len(l)

# Plot bite size: bandwidth (read)
if True:
    fig_save_path = bitesize_save_prefix + 'pre-sec-readwrite.pdf'
    group_list = ['read', 'write']
    y_values = {
            'read': io_size_by_sec['ALL_READS']['size'],
            'write': io_size_by_sec['ALL_WRITES']['size'],            
            }
    y_values['read'] = [x / 1024 for x in y_values['read']]
    y_values['write'] = [x / 1024 for x in y_values['write']]
    
    std_dev = None
    # x_ticks = ['xtick_1', 'xtick_1']
    legend_label = {
        'read': 'read',
        'write': 'write'
    }

    title = None
    xlabel = 'Time (minutes)'
    ylabel = 'Bandwidth (GiB/s)'

    # Parameters
    linewidth = 4
    markersize = 15

    datalabel_size = 26
    datalabel_va = 'bottom'
    axis_tick_font_size = 45
    axis_label_font_size = 55
    legend_font_size = 45

    reset_color()
    fig, ax = plt.subplots(figsize=(12, 8))

    plt.xlabel(xlabel, fontsize=axis_label_font_size)
    plt.ylabel(ylabel, fontsize=axis_label_font_size)
    plt.grid(True)

    ax.tick_params(axis='both', which='major', labelsize=axis_tick_font_size)

    # Ensure both lines start at the same time
    time_min = min(io_size_by_sec['ALL_READS']['ts'][0], io_size_by_sec['ALL_WRITES']['ts'][0])
    time_max = max(io_size_by_sec['ALL_READS']['ts'][-1], io_size_by_sec['ALL_WRITES']['ts'][-1])
    ran = time_max - time_min + 1

    if (io_size_by_sec['ALL_READS']['ts'][0] > time_min):
        y_values['read'] = [0] * (io_size_by_sec['ALL_READS']['ts'][0] - time_min) + y_values['read']
    if (io_size_by_sec['ALL_READS']['ts'][-1] < time_max):
        y_values['read'] = y_values['read'] + [0] * (time_max - io_size_by_sec['ALL_READS']['ts'][-1])

    if (io_size_by_sec['ALL_WRITES']['ts'][0] > time_min):
        y_values['write'] = [0] * (io_size_by_sec['ALL_WRITES']['ts'][0] - time_min) + y_values['write']
    if (io_size_by_sec['ALL_WRITES']['ts'][-1] < time_max):
        y_values['write'] = y_values['write'] + [0] * (time_max - io_size_by_sec['ALL_WRITES']['ts'][-1])


    for (index, group_name) in zip(range(len(group_list)), group_list):
        # x, y, std_dev, data_label = data[group_name]
        x = range(1, len(y_values[group_name]) + 1)
        y = y_values[group_name]

        yerr = None
        if std_dev:
            yerr = std_dev[group_name]

        # TODO: Add this to the github plot repo
        if legend_label == None:
            cur_legend_label = 'placeholder'
        else:
            cur_legend_label = legend_label[group_name]

        plt.errorbar(
            x,
            [float(yy) / 1024. for yy in y],
            yerr=yerr,
            label=cur_legend_label,
            # marker=dot_style[index % len(dot_style)],
            linewidth=linewidth,
            markersize=markersize,
            color=get_next_color(),
        )


    ax.set_xlim(0, 840)
    ax.set_xticks(range(0, 900, 60))
    ax.set_xticklabels([str(size // 60) for size in range(0, 900, 60)])
    ax.set_ylim(0, 10)
    ax.set_yticks(range(1, 11))

    if legend_label != None:
        plt.legend(fontsize=legend_font_size, labelspacing=0.1, loc='upper right', prop={'size': 44})


    plt.savefig(fig_save_path, bbox_inches='tight')
    plt.close()

# Plot bite size: bandwidth (write: ws)
if True:
    fig_save_path = bitesize_save_prefix + 'pre-sec-write.pdf'
    group_list = ['write']
    y_values = {'write': io_size_by_sec['W']['size']}
    y_values['write'] = [x / 1024 for x in y_values['write']]
    std_dev = None
    # x_ticks = ['xtick_1', 'xtick_1']
    legend_label = None

    title = None
    xlabel = 'Time (s)'
    ylabel = 'Write bandwidth (MiB/s)'

    # Parameters
    linewidth = 1
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

    for (index, group_name) in zip(range(len(group_list)), group_list):
        # x, y, std_dev, data_label = data[group_name]
        x = range(1, len(y_values[group_name]) + 1)
        y = y_values[group_name]

        yerr = None
        if std_dev:
            yerr = std_dev[group_name]

        # TODO: Add this to the github plot repo
        if legend_label == None:
            cur_legend_label = 'placeholder'
        else:
            cur_legend_label = legend_label[group_name]

        plt.errorbar(
            x,
            y,
            yerr=yerr,
            label=cur_legend_label,
            linewidth=linewidth,
            markersize=markersize,
            color=get_next_color(),
        )


    if legend_label != None:
        plt.legend(fontsize=legend_font_size, labelspacing=0.1)


    plt.savefig(fig_save_path, bbox_inches='tight')
    plt.close()

# all_op = ['W', 'WSM', 'WS', 'WM', 'RA', 'RM', 'R']
all_op = list(set(op))
sector_access_count = {} # How many times a sector is accessed: number of sectors
# Plot read sector location by seconds
if True:
    pkl_file = open(sector_access_count_prefix + 'all.pkl', 'wb')
    if False: #os.path.exists(sector_access_count_prefix + 'all.pkl'):
        pkl_file = open(sector_access_count_prefix + 'all.pkl', 'rb')
        sector_access_count = pkl.load(pkl_file)
        pkl_file.close()
    else:
        fig_save_path = bitesize_save_prefix + 'mix-sector-location.pdf'
        xlabel = 'Time (s)'
        ylabel = 'Sector ID'
        timestamp = timestamps
        sector = start_sector
        num_sectors = num_sectors
        x = []
        y = []

        print(f"Min start_sector: {min(sector)}")
        print(f"Max start_sector: {max(sector)}")
        print(f'Max num_sectors: {max(num_sectors)}')
        
        all_buckets = {}
        for cur_op in all_op:
            all_buckets[cur_op] = [0] * (max(sector)+max(num_sectors))

        for cur_ts, cur_op_inner, cur_start_sector, cur_num_sector in zip(timestamp, op, sector,
                                                    num_sectors):
            for cur_sector in range(cur_start_sector,
                                    cur_start_sector + cur_num_sector):
                all_buckets[cur_op_inner][cur_sector] += 1
        
        # Aggregated by how many times a sector is accessed
        for cur_op in all_op:
            cur_buckets = all_buckets[cur_op]
            sector_access_count[cur_op] = {}
            for cur_count in cur_buckets:
                if cur_count not in sector_access_count[cur_op]:
                    sector_access_count[cur_op][cur_count] = 0
                sector_access_count[cur_op][cur_count] += 1
            del sector_access_count[cur_op][0]
            
        print('Sector access count:')
        print(sector_access_count)

        # save to file, this needs a very long time to process
        text_file = open(sector_access_count_prefix + 'all.txt', 'w')
        for cur_op in sector_access_count.keys():
            text_file.write(cur_op + '\n')
            text_file.write(str(sector_access_count[cur_op]) + '\n')
        text_file.close()
        
        pkl_file = open(sector_access_count_prefix + 'all.pkl', 'wb')
        pkl.dump(sector_access_count, pkl_file)
        pkl_file.close()


# CDF
cdf_plot_op = ['W', 'RA']
if True:
    for cur_op in cdf_plot_op:
        cur_sector_access_count = sector_access_count[cur_op]
        fig_save_path = sector_access_cdf_prefix + cur_op + '.pdf'
        
        # x
        all_access_count = sorted(cur_sector_access_count.keys())
        # y
        y = [0]
        for cur_count in all_access_count:
            y.append(y[-1] + cur_sector_access_count[cur_count])
        y = y[1:]
        cur_total_access = y[-1]
        y = [i / cur_total_access for i in y]

        # Plot CDF
        group_list = ['read']
        x = all_access_count
        y_values = {'read': y}
        std_dev = None
        # x_ticks = ['xtick_1', 'xtick_1']
        legend_label = None

        title = None
        xlabel = 'Access count'
        ylabel = 'Aggregated ratio'

        # Parameters
        linewidth = 1
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

        for (index, group_name) in zip(range(len(group_list)), group_list):
            y = y_values[group_name]

            yerr = None
            if std_dev:
                yerr = std_dev[group_name]

            # TODO: Add this to the github plot repo
            if legend_label == None:
                cur_legend_label = 'placeholder'
            else:
                cur_legend_label = legend_label[group_name]

            plt.errorbar(
                x,
                y,
                yerr=yerr,
                label=cur_legend_label,
                linewidth=linewidth,
                markersize=markersize,
                color=get_next_color(),
            )

        if legend_label != None:
            plt.legend(fontsize=legend_font_size, labelspacing=0.1)

        plt.savefig(fig_save_path, bbox_inches='tight')
        plt.close()
            
info_file.close()