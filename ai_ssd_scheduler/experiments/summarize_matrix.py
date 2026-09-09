import json

def summarize():
    with open('results/matrix_results.json') as f:
        data = json.load(f)

    # 1. Dimension A: Deadlines
    print("\n" + "=" * 105)
    print("DIMENSION A: DEADLINE SLACK CURVE (400 us -> 3000 us)")
    print("=" * 105)
    print(f"{'Slack (us)':<10} | {'S0-FIFO Miss%':<15} | {'S1-AI-Pri Miss%':<16} | {'S2-State Miss%':<16} | {'S3-TEMPO Miss%':<16} | {'Crit P95 (S3)':<14} | {'Crit P99 (S3)':<14}")
    print("-" * 105)
    by_val_a = {}
    for r in data['dimension_a']:
        v = r['param_val']
        by_val_a.setdefault(v, {})[r['scheduler']] = r
    for v in sorted(by_val_a.keys()):
        s0 = by_val_a[v]['S0-FIFO']
        s1 = by_val_a[v]['S1-AI-Priority']
        s2 = by_val_a[v]['S2-SSD-State']
        s3 = by_val_a[v]['S3-AI+SSD-State']
        print(f"{v:<10.0f} | {s0['miss_pct']:<15.1f} | {s1['miss_pct']:<16.1f} | {s2['miss_pct']:<16.1f} | {s3['miss_pct']:<16.1f} | {s3['crit_p95']:<14.1f} | {s3['crit_p99']:<14.1f}")

    # 2. Dimension B: Background Contention
    print("\n" + "=" * 105)
    print("DIMENSION B: BACKGROUND WRITE CONTENTION CURVE (0 IOPS -> 1600 IOPS)")
    print("=" * 105)
    print(f"{'BG IOPS':<10} | {'S0-FIFO Miss%':<15} | {'S1-AI-Pri Miss%':<16} | {'S2-State Miss%':<16} | {'S3-TEMPO Miss%':<16} | {'Crit P95 (S3)':<14} | {'Crit P99 (S3)':<14}")
    print("-" * 105)
    by_val_b = {}
    for r in data['dimension_b']:
        v = r['param_val']
        by_val_b.setdefault(v, {})[r['scheduler']] = r
    for v in sorted(by_val_b.keys()):
        s0 = by_val_b[v]['S0-FIFO']
        s1 = by_val_b[v]['S1-AI-Priority']
        s2 = by_val_b[v]['S2-SSD-State']
        s3 = by_val_b[v]['S3-AI+SSD-State']
        print(f"{v:<10.0f} | {s0['miss_pct']:<15.1f} | {s1['miss_pct']:<16.1f} | {s2['miss_pct']:<16.1f} | {s3['miss_pct']:<16.1f} | {s3['crit_p95']:<14.1f} | {s3['crit_p99']:<14.1f}")

    # 3. Dimension C: GC Interference
    print("\n" + "=" * 105)
    print("DIMENSION C: GC INTERFERENCE DURATION CURVE (0 ms -> 5.0 ms)")
    print("=" * 105)
    print(f"{'Erase (ms)':<10} | {'S0-FIFO P99':<15} | {'S1-AI-Pri P99':<16} | {'S2-State P99':<16} | {'S3-TEMPO P99':<16} | {'S1 Miss %':<12} | {'S3 Miss %':<12}")
    print("-" * 105)
    by_val_c = {}
    for r in data['dimension_c']:
        v = r['param_val']
        by_val_c.setdefault(v, {})[r['scheduler']] = r
    for v in sorted(by_val_c.keys()):
        s0 = by_val_c[v]['S0-FIFO']
        s1 = by_val_c[v]['S1-AI-Priority']
        s2 = by_val_c[v]['S2-SSD-State']
        s3 = by_val_c[v]['S3-AI+SSD-State']
        print(f"{v:<10.1f} | {s0['crit_p99']:<15.1f} | {s1['crit_p99']:<16.1f} | {s2['crit_p99']:<16.1f} | {s3['crit_p99']:<16.1f} | {s1['miss_pct']:<12.1f} | {s3['miss_pct']:<12.1f}")

    # 4. Dimension D: Queue Depth
    print("\n" + "=" * 105)
    print("DIMENSION D: CONTROLLER QUEUE DEPTH SCALING (QD = 1 -> 64)")
    print("=" * 105)
    print(f"{'Queue Depth':<12} | {'S0-FIFO P95':<15} | {'S1-AI-Pri P95':<16} | {'S2-State P95':<16} | {'S3-TEMPO P95':<16} | {'S1 Miss %':<12} | {'S3 Miss %':<12}")
    print("-" * 105)
    by_val_d = {}
    for r in data['dimension_d']:
        v = r['param_val']
        by_val_d.setdefault(v, {})[r['scheduler']] = r
    for v in sorted(by_val_d.keys()):
        s0 = by_val_d[v]['S0-FIFO']
        s1 = by_val_d[v]['S1-AI-Priority']
        s2 = by_val_d[v]['S2-SSD-State']
        s3 = by_val_d[v]['S3-AI+SSD-State']
        print(f"{v:<12d} | {s0['crit_p95']:<15.1f} | {s1['crit_p95']:<16.1f} | {s2['crit_p95']:<16.1f} | {s3['crit_p95']:<16.1f} | {s1['miss_pct']:<12.1f} | {s3['miss_pct']:<12.1f}")

if __name__ == '__main__':
    summarize()
