"""Phase 15: Final Figure Generation Script.

Aggregates all experiment outputs into exact numerical plotting tables and ASCII charts
for Figures 1 through 10.
"""

import json
import os

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            return json.load(f)
    return None

def generate_figure_data():
    print("=" * 115)
    print("PHASE 15: PUBLICATION FIGURES & EXPERIMENTAL SYNTHESIS")
    print("Consolidating empirical data for Figures 1 to 10")
    print("=" * 115)

    matrix_data = load_json(os.path.join("results", "matrix_results.json"))
    crossover_data = load_json(os.path.join("results", "crossover_curve.json"))
    ablation_data = load_json(os.path.join("results", "ablation_analysis.json"))
    energy_data = load_json(os.path.join("results", "energy_evaluation.json"))
    overhead_data = load_json(os.path.join("results", "overhead_profiling.json"))

    print("\n--- FIGURE 3: PRIMARY RESULT - CRITICAL DEADLINE MISS RATE ---")
    if energy_data:
        for item in energy_data:
            print(f"  * {item['scheduler']:<26}: Miss Rate = {item['miss_pct']}%")

    print("\n--- FIGURE 4: DEADLINE SLACK SWEEP (CROSSOVER CURVE) ---")
    if crossover_data:
        curve_pts = crossover_data if isinstance(crossover_data, list) else crossover_data.get("crossover_curve", [])
        print(f"  {'Slack (us)':<12} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Advantage Ratio (S1/S3)':<24}")
        for pt in curve_pts[::2]:  # every 2nd point for brevity
            s1_m = pt["s1_miss_pct"]
            s3_m = pt["s3_miss_pct"]
            ratio = f"{s1_m / s3_m:.2f}x" if s3_m > 0 else "Inf"
            print(f"  {pt['slack_us']:<12.0f} | {s1_m:<12.1f} | {s3_m:<12.1f} | {ratio:<24}")

    print("\n--- FIGURE 5: BACKGROUND CONTENTION SWEEP ---")
    if matrix_data and "dimension_b_background" in matrix_data:
        print(f"  {'BG IOPS':<10} | {'S0 Miss %':<10} | {'S1 Miss %':<10} | {'S2 Miss %':<10} | {'S3 Miss %':<10} | {'S3 Win':<10}")
        for row in matrix_data["dimension_b_background"]:
            s0 = row["schedulers"]["S0-FIFO"]["miss_pct"]
            s1 = row["schedulers"]["S1-AI-Priority"]["miss_pct"]
            s2 = row["schedulers"]["S2-SSD-State"]["miss_pct"]
            s3 = row["schedulers"]["S3-AI+SSD-State"]["miss_pct"]
            win = s1 - s3
            print(f"  {row['bg_iops']:<10} | {s0:<10.1f} | {s1:<10.1f} | {s2:<10.1f} | {s3:<10.1f} | -{win:<9.1f}%")

    print("\n--- FIGURE 8: ABLATION ATTRIBUTION ---")
    if ablation_data and "scenario_a_write_contention" in ablation_data:
        print("  Scenario A (Write Contention):")
        for item in ablation_data["scenario_a_write_contention"]:
            print(f"    - {item['id']:<8} ({item['name']:<32}): Miss = {item['miss_pct']}%, P95 = {item['p95_us']} us")

    print("\n--- FIGURE 10: ENERGY PER DEADLINE-SATISFIED AI REQUEST ---")
    if energy_data:
        for item in energy_data:
            print(f"  * {item['scheduler']:<26}: {item['mj_per_satisfied_req']:.3f} mJ / satisfied request")

if __name__ == "__main__":
    generate_figure_data()
