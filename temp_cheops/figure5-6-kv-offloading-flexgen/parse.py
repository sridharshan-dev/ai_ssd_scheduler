def parse_gpu_util(fpath):
    f = open(fpath, 'r')
    lines = f.readlines()[1:]
    f.close()

    results = []
    for cur_line in lines:
        cur_line = cur_line.strip()
        if cur_line == '':
            continue
        results.append(float(cur_line.split()[2]))

    return results


def parse_bite_size(fpath):
    f = open(fpath, 'r')
    lines = f.readlines()
    f.close()

    timestamps = []
    op = []
    bite_size = []
    start_sector = []
    num_sectors = []
    for cur_line in lines:
        cur_line = cur_line.strip()
        if not (cur_line and cur_line[0].isdigit()):
            continue
        cur_line = cur_line.split(' ')
        cur_timestamp = int(cur_line[0][:-1][:-9])  # to seconds
        cur_op = cur_line[1][:-1]
        cur_bite_size = int(int(cur_line[2][:-1]) / 1024)  # in KB
        cur_start_sector = int(cur_line[3][:-1])
        cur_num_sectors = int(cur_line[4])
        timestamps.append(cur_timestamp)
        op.append(cur_op)
        bite_size.append(cur_bite_size)
        start_sector.append(cur_start_sector)
        num_sectors.append(cur_num_sectors)

    return timestamps, op, bite_size, start_sector, num_sectors


def aggregate_io_by_sec(timestamp, bite_size):
    timestamp_aggregated = []
    bite_size_aggregated = []
    cur_ts = timestamp[0]
    cur_aggregated_size = 0
    cur_qps = 0

    # for next_ts, next_bite_size in zip(timestamp, bite_size):
    #     if cur_ts == next_ts:
    #         cur_aggregated_size += next_bite_size
    #         cur_qps += 1
    #     else:
    #         timestamp_aggregated.append(cur_ts)
    #         bite_size_aggregated.append(cur_aggregated_size)
    #         # cur_ts += 1
    #         # while cur_ts < next_ts:
    #         #     timestamp_aggregated.append(cur_ts)
    #         #     bite_size_aggregated.append(0)
    #         #     cur_ts += 1
    #         cur_ts = next_ts
    #         cur_aggregated_size = next_bite_size

    results = {}
    for cur_ts, cur_bite_size in zip(timestamp, bite_size):
        if not cur_ts in results:
            results[cur_ts] = 0
        results[cur_ts] += cur_bite_size

    sorted_ts = list(results.keys())
    sorted_ts.sort()

    prev_ts = sorted_ts[0] - 1
    for cur_ts in sorted_ts:
        while prev_ts + 1 < cur_ts:
            timestamp_aggregated.append(prev_ts)
            bite_size_aggregated.append(0)
            prev_ts += 1
        timestamp_aggregated.append(cur_ts)
        bite_size_aggregated.append(results[cur_ts])
        prev_ts = cur_ts

    return timestamp_aggregated, bite_size_aggregated, cur_qps


def aggregate_sector_id():
    pass


def sector_usage_count(start_sector, num_sectors):
    pass


'''
What do we need?
  1. Count of each size
  2. IO traffic by operation
'''


def process_bite_size(timestamps, op, bite_size):
    bite_size_by_op = {'ALL_READS' : {'ts': [], 'size': []}, 'ALL_WRITES' : {'ts': [], 'size': []}}
    bite_size_aggregated = {}
    io_size_by_sec = {}
    for cur_ts, cur_op, cur_bite_size in zip(timestamps, op, bite_size):
        if not (cur_op in bite_size_by_op):
            bite_size_by_op[cur_op] = {'ts': [], 'size': []}
        bite_size_by_op[cur_op]['ts'].append(cur_ts)
        bite_size_by_op[cur_op]['size'].append(cur_bite_size)
        if 'W' in cur_op:
            bite_size_by_op['ALL_WRITES']['ts'].append(cur_ts)
            bite_size_by_op['ALL_WRITES']['size'].append(cur_bite_size)     
        if 'R' in cur_op:
            bite_size_by_op['ALL_READS']['ts'].append(cur_ts)
            bite_size_by_op['ALL_READS']['size'].append(cur_bite_size)     


    for cur_op in bite_size_by_op.keys():
        bite_size_aggregated[cur_op] = {}
        for cur_size in bite_size_by_op[cur_op]['size']:
            if not (cur_size in bite_size_aggregated[cur_op]):
                bite_size_aggregated[cur_op][cur_size] = 0
            bite_size_aggregated[cur_op][cur_size] += 1

    for cur_op in bite_size_by_op.keys():
        cur_ts_aggregated, cur_size_aggregated, cur_qps = aggregate_io_by_sec(
            bite_size_by_op[cur_op]['ts'], bite_size_by_op[cur_op]['size'])
        io_size_by_sec[cur_op] = {
            'ts': cur_ts_aggregated,
            'size': cur_size_aggregated,
            'qps': cur_qps
        }
        # if cur_op == 'RA':
        #     print(cur_ts_aggregated)
        #     print(len(cur_ts_aggregated))

    return bite_size_by_op, bite_size_aggregated, io_size_by_sec


def get_access_frequency(op, start_sector, num_sectors):
    results = {}
    for cur_op, cur_start_sector, cur_num_sectors in zip(
            op, start_sector, num_sectors):
        if not cur_op in results:
            results[cur_op] = {}
        for cur_sector in range(cur_start_sector,
                                cur_start_sector + cur_num_sectors):
            if not cur_sector in results[cur_op]:
                results[cur_op][cur_sector] = 0
            results[cur_op][cur_sector] += 1

    reverse_index = {}
    for cur_op in results.keys():
        reverse_index[cur_op] = {}
        for cur_sec, cur_num in results[cur_op].items():
            if cur_num not in reverse_index[cur_op]:
                reverse_index[cur_op][cur_num] = 0
            reverse_index[cur_op][cur_num] += 1

    return results, reverse_index
