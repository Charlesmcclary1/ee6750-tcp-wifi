"""
EE6750 Group 15 – Transport Over Wireless
TCP Performance Evaluation: Mobility & Contention over WiFi
Simulated version – runs in Jupyter Notebook or VS Code without Mininet-WiFi.

Install dependencies:
    pip install numpy matplotlib scipy pandas

Run:
    python ee6750_experiment.py
    or paste into a Jupyter notebook cell and run.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy import stats
import itertools
import json
import os
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────
MOBILITY_SPEEDS = [0, 2, 5, 10]   # m/s
FLOW_COUNTS     = [1, 3, 5]
LOSS_RATES      = [0, 1, 3, 5]    # percent
TRIALS          = 5
DURATION        = 30               # seconds per trial
BANDWIDTH_MAX   = 54.0             # Mbps (802.11n baseline)
RESULTS_DIR     = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# ALGORITHM 2 – Build Topology (simulated)
# ─────────────────────────────────────────────────────────────
def build_topology(num_flows):
    """
    Simulates a Mininet-WiFi topology.
    Returns a topology dict describing AP + stations.
    In real deployment: replace with mn_wifi.net.Mininet_wifi() calls.
    """
    topology = {
        'ap': {'ssid': 'experiment-net', 'channel': 6, 'range': 100},
        'stations': [
            {'id': f'sta{i}', 'ip': f'10.0.0.{i}', 'x': 10 + i*8, 'y': 10}
            for i in range(1, num_flows + 1)
        ],
        'receiver': {'id': 'recv', 'ip': f'10.0.0.{num_flows+1}', 'x': 50, 'y': 80},
        'num_flows': num_flows,
    }
    return topology

# ─────────────────────────────────────────────────────────────
# ALGORITHM 3 – Set Mobility (simulated)
# ─────────────────────────────────────────────────────────────
def set_mobility(topology, speed):
    """
    Simulates RandomWaypoint mobility by computing a signal degradation
    factor based on mobility speed and LogDistance path loss model.
    speed=0 → static (no degradation from movement).
    In real deployment: replace with net.setMobilityModel() call.
    """
    topology['speed'] = speed
    if speed == 0:
        topology['mobility_degradation'] = 0.0
    else:
        # LogDistance model: every doubling of effective distance adds ~6 dB loss
        # Mobility causes intermittent distance increases → modeled as degradation factor
        topology['mobility_degradation'] = min(0.6, speed * 0.045)
    return topology

# ─────────────────────────────────────────────────────────────
# ALGORITHM 4 – Traffic Generation (simulated)
# ─────────────────────────────────────────────────────────────
def simulate_tcp_flow(speed, loss_rate_pct, num_flows, flow_idx, duration):
    """
    Simulates one TCP CUBIC flow's behavior over a WiFi link.

    Models:
      - 802.11 MAC contention (CSMA/CA overhead with multiple flows)
      - Signal degradation from mobility (LogDistance)
      - TCP cwnd reduction from packet loss (misinterpreted as congestion)
      - Retransmission behavior

    Returns per-flow metrics dict.
    """
    # ── Base channel capacity after MAC contention overhead ──
    # CSMA/CA efficiency drops with more stations (Bianchi model approximation)
    csma_efficiency = 1.0 / (1.0 + 0.15 * (num_flows - 1))
    base_capacity   = BANDWIDTH_MAX * csma_efficiency

    # ── Mobility-induced SINR degradation ──
    mobility_factor = 1.0 - min(0.6, speed * 0.045)
    # Add per-flow noise from handoff events at higher speeds
    handoff_noise   = np.random.exponential(speed * 0.008) if speed > 0 else 0
    mobility_factor = max(0.1, mobility_factor - handoff_noise)

    # ── Effective loss rate (channel + mobility-induced link errors) ──
    link_loss_pct      = loss_rate_pct + speed * 0.3
    effective_loss_frac = min(0.5, link_loss_pct / 100.0)

    # ── TCP cwnd dynamics ──
    # TCP CUBIC: cwnd resets on perceived congestion (loss)
    # Wireless losses falsely trigger this even when pipe isn't full
    cwnd_factor = (1.0 - effective_loss_frac) ** 1.5

    # ── Throughput ──
    throughput = (base_capacity * mobility_factor * cwnd_factor
                  + np.random.normal(0, base_capacity * 0.03))
    throughput = max(0.1, throughput)

    # ── Goodput (application-received) ──
    goodput = throughput * (1.0 - effective_loss_frac)

    # ── RTT samples (ms) ──
    # Base RTT for WiFi ~5-15ms; grows with loss (retransmit backoffs) and mobility
    base_rtt   = 8.0 + speed * 1.2 + loss_rate_pct * 2.5
    rtt_jitter = np.random.exponential(base_rtt * 0.25, size=200)
    rtt_samples= np.abs(np.random.normal(base_rtt, base_rtt * 0.15, 200)
                        + rtt_jitter)

    # ── Retransmissions ──
    # Expected retransmits ∝ loss rate × packets sent
    packets_sent  = int((throughput * 1e6 / 8) / 1500 * duration)
    retransmits   = int(packets_sent * effective_loss_frac
                        * np.random.uniform(0.8, 1.2))

    return {
        'throughput':    round(throughput, 4),
        'goodput':       round(goodput, 4),
        'rtt_samples':   rtt_samples.tolist(),
        'retransmits':   retransmits,
        'packets_sent':  packets_sent,
        'loss_pct':      round(effective_loss_frac * 100, 2),
    }

def launch_iperf_flows(topology, num_flows, duration):
    """
    Simulates launching iperf3 flows and collecting per-flow logs.
    In real deployment: replace with sta.popen('iperf3 -c ...') calls.
    """
    speed    = topology.get('speed', 0)
    flow_logs = []
    for i in range(num_flows):
        flow = simulate_tcp_flow(speed, 0, num_flows, i, duration)
        flow_logs.append(flow)
    return flow_logs

# ─────────────────────────────────────────────────────────────
# ALGORITHM 5 – Metrics Extraction
# ─────────────────────────────────────────────────────────────
def analyze(flow_logs, loss_rate_pct, speed, num_flows):
    """
    Computes aggregate metrics from per-flow data.
    In real deployment: also parse .pcap via tshark for RTT.
    """
    if not flow_logs:
        return None

    # Re-simulate with the actual loss_rate for this scenario
    flow_logs = [
        simulate_tcp_flow(speed, loss_rate_pct, num_flows, i, DURATION)
        for i in range(num_flows)
    ]

    throughputs  = [f['throughput']  for f in flow_logs]
    goodputs     = [f['goodput']     for f in flow_logs]
    retransmits  = [f['retransmits'] for f in flow_logs]
    all_rtt      = []
    for f in flow_logs:
        all_rtt.extend(f['rtt_samples'])

    all_rtt.sort()
    n       = len(throughputs)
    sum_t   = sum(throughputs)
    sum_t2  = sum(t**2 for t in throughputs)

    # Jain's Fairness Index
    fairness = (sum_t ** 2) / (n * sum_t2) if sum_t2 > 0 else 1.0

    # 95th percentile latency
    p95_idx    = int(0.95 * len(all_rtt))
    latency_p95 = all_rtt[p95_idx] if all_rtt else 0

    return {
        'throughputs':     throughputs,
        'mean_throughput': float(np.mean(throughputs)),
        'mean_goodput':    float(np.mean(goodputs)),
        'retransmits':     sum(retransmits),
        'latency_p95':     round(latency_p95, 2),
        'all_rtt':         all_rtt,
        'loss_pct':        round(float(np.mean([f['loss_pct'] for f in flow_logs])), 2),
        'fairness':        round(fairness, 4),
        'num_flows':       n,
    }

# ─────────────────────────────────────────────────────────────
# ALGORITHM 1 – Main Experiment Controller
# ─────────────────────────────────────────────────────────────
def run_experiment():
    results_db = []
    combos     = list(itertools.product(MOBILITY_SPEEDS, FLOW_COUNTS, LOSS_RATES))
    total      = len(combos) * TRIALS

    print("=" * 60)
    print("EE6750 Group 15 – TCP over WiFi Experiment")
    print(f"Scenarios: {len(combos)}  |  Trials each: {TRIALS}  |  Total runs: {total}")
    print("=" * 60)

    run = 0
    for m, f, l in combos:
        for trial in range(1, TRIALS + 1):
            run += 1
            pct = int(run / total * 30)
            bar = "█" * pct + "░" * (30 - pct)
            print(f"\r[{bar}] {run}/{total}  m={m}m/s  f={f}flows  l={l}%  trial={trial}", end="", flush=True)

            topology = build_topology(f)
            topology = set_mobility(topology, m)

            flow_logs = launch_iperf_flows(topology, f, DURATION)
            metrics   = analyze(flow_logs, l, m, f)

            results_db.append({
                'm': m, 'f': f, 'l': l,
                'trial': trial, 'metrics': metrics
            })

    print(f"\n\n✓ Experiment complete. {total} runs finished.")

    # Save raw results
    raw_path = os.path.join(RESULTS_DIR, 'raw_results.json')
    serializable = []
    for r in results_db:
        entry = dict(r)
        if entry['metrics']:
            m2 = dict(entry['metrics'])
            m2.pop('all_rtt', None)     # too large for JSON display
            m2.pop('throughputs', None)
            entry['metrics'] = m2
        serializable.append(entry)
    with open(raw_path, 'w') as fout:
        json.dump(serializable, fout, indent=2)
    print(f"Raw results → {raw_path}")

    return results_db

# ─────────────────────────────────────────────────────────────
# ALGORITHM 6 – Statistical Aggregation
# ─────────────────────────────────────────────────────────────
def aggregate(results_db):
    groups = defaultdict(list)
    for entry in results_db:
        key = (entry['m'], entry['f'], entry['l'])
        if entry['metrics']:
            groups[key].append(entry['metrics'])

    aggregated = {}
    for key, trial_metrics in groups.items():
        def ci(vals):
            if len(vals) < 2:
                return 0.0
            return 1.96 * float(np.std(vals, ddof=1)) / np.sqrt(len(vals))

        throughputs = [m['mean_throughput'] for m in trial_metrics]
        latencies   = [m['latency_p95']     for m in trial_metrics]
        fairnesses  = [m['fairness']        for m in trial_metrics]
        retransmits = [m['retransmits']     for m in trial_metrics]
        all_rtt     = []
        for m in trial_metrics:
            all_rtt.extend(m.get('all_rtt', []))

        aggregated[key] = {
            'mean_throughput':  float(np.mean(throughputs)),
            'ci_throughput':    ci(throughputs),
            'mean_latency':     float(np.mean(latencies)),
            'ci_latency':       ci(latencies),
            'mean_fairness':    float(np.mean(fairnesses)),
            'ci_fairness':      ci(fairnesses),
            'mean_retransmits': float(np.mean(retransmits)),
            'all_rtt':          all_rtt,
        }

    return aggregated

# ─────────────────────────────────────────────────────────────
# ALGORITHM 7 – Visualization
# ─────────────────────────────────────────────────────────────
def plot(aggregated, results_db):
    colors = ['#2E86AB', '#E84855', '#3BB273']
    fig    = plt.figure(figsize=(18, 14))
    fig.patch.set_facecolor('#F8F9FA')
    gs     = gridspec.GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.32)

    # ── Fig 1: Throughput vs Mobility Speed ──────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor('#FFFFFF')
    for idx, f in enumerate(FLOW_COUNTS):
        xs, ys, errs = [], [], []
        for m in MOBILITY_SPEEDS:
            key = (m, f, 0)
            if key in aggregated:
                xs.append(m)
                ys.append(aggregated[key]['mean_throughput'])
                errs.append(aggregated[key]['ci_throughput'])
        if xs:
            ax1.errorbar(xs, ys, yerr=errs, marker='o', linewidth=2,
                         markersize=7, capsize=5, color=colors[idx],
                         label=f'{f} flow(s)', zorder=3)
    ax1.set_xlabel('Mobility speed (m/s)', fontsize=11)
    ax1.set_ylabel('Throughput (Mbps)', fontsize=11)
    ax1.set_title('Fig 1 – Throughput vs Mobility Speed\n(0% loss, 95% CI shown)', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_xticks(MOBILITY_SPEEDS)

    # ── Fig 2: Latency CDF ───────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor('#FFFFFF')
    scenarios = [
        ((0,  1, 0), 'Static, 1 flow, 0% loss',          '#2E86AB'),
        ((5,  3, 1), 'Moderate mobility, 3 flows, 1% loss', '#F4A261'),
        ((10, 5, 5), 'High mobility, 5 flows, 5% loss',   '#E84855'),
    ]
    for key, label, color in scenarios:
        if key in aggregated:
            rtt = sorted(aggregated[key]['all_rtt'])
            if rtt:
                n   = len(rtt)
                cdf = np.arange(1, n + 1) / n
                ax2.plot(rtt, cdf, linewidth=2, color=color, label=label)
                p95 = rtt[int(0.95 * n)]
                ax2.axvline(p95, color=color, linestyle=':', alpha=0.6, linewidth=1)
    ax2.set_xlabel('RTT latency (ms)', fontsize=11)
    ax2.set_ylabel('CDF', fontsize=11)
    ax2.set_title("Fig 2 – Latency CDF by Scenario\n(dotted = 95th percentile)", fontsize=12, fontweight='bold')
    ax2.legend(fontsize=8, loc='lower right')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.set_xlim(left=0)
    ax2.set_ylim(0, 1.05)

    # ── Fig 3: Fairness vs Load ──────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor('#FFFFFF')
    loss_colors = ['#2E86AB', '#3BB273', '#F4A261', '#E84855']
    for idx, l in enumerate(LOSS_RATES):
        xs, ys, errs = [], [], []
        for f in FLOW_COUNTS:
            vals = [aggregated[(m, f, l)]['mean_fairness']
                    for m in MOBILITY_SPEEDS if (m, f, l) in aggregated]
            if vals:
                xs.append(f)
                ys.append(float(np.mean(vals)))
                errs.append(1.96 * float(np.std(vals, ddof=1)) / np.sqrt(len(vals)) if len(vals) > 1 else 0)
        if xs:
            ax3.errorbar(xs, ys, yerr=errs, marker='s', linewidth=2,
                         markersize=7, capsize=5, color=loss_colors[idx],
                         label=f'{l}% loss', zorder=3)
    ax3.set_xlabel('Number of flows', fontsize=11)
    ax3.set_ylabel("Jain's fairness index", fontsize=11)
    ax3.set_title("Fig 3 – Fairness vs Contention Load\n(averaged across mobility speeds)", fontsize=12, fontweight='bold')
    ax3.set_ylim(0, 1.05)
    ax3.set_xticks(FLOW_COUNTS)
    ax3.axhline(1.0, color='gray', linestyle=':', linewidth=1, alpha=0.5, label='Perfect fairness')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3, linestyle='--')

    # ── Fig 4: Retransmissions Heatmap ───────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor('#FFFFFF')
    heat_data = np.zeros((len(LOSS_RATES), len(MOBILITY_SPEEDS)))
    for li, l in enumerate(LOSS_RATES):
        for mi, m in enumerate(MOBILITY_SPEEDS):
            vals = [aggregated[(m, f, l)]['mean_retransmits']
                    for f in FLOW_COUNTS if (m, f, l) in aggregated]
            heat_data[li, mi] = float(np.mean(vals)) if vals else 0

    im = ax4.imshow(heat_data, cmap='YlOrRd', aspect='auto')
    ax4.set_xticks(range(len(MOBILITY_SPEEDS)))
    ax4.set_xticklabels([f'{m} m/s' for m in MOBILITY_SPEEDS], fontsize=9)
    ax4.set_yticks(range(len(LOSS_RATES)))
    ax4.set_yticklabels([f'{l}% loss' for l in LOSS_RATES], fontsize=9)
    ax4.set_title('Fig 4 – Avg Retransmissions\n(across flow counts)', fontsize=12, fontweight='bold')
    plt.colorbar(im, ax=ax4, label='Retransmissions')
    for li in range(len(LOSS_RATES)):
        for mi in range(len(MOBILITY_SPEEDS)):
            ax4.text(mi, li, f'{heat_data[li, mi]:.0f}',
                     ha='center', va='center', fontsize=8,
                     color='black' if heat_data[li, mi] < heat_data.max() * 0.6 else 'white')

    fig.suptitle('EE6750 Group 15 – TCP Performance over WiFi\nMobility & Contention Analysis',
                 fontsize=15, fontweight='bold', y=1.01)

    plt.savefig(os.path.join(RESULTS_DIR, 'all_figures.pdf'), bbox_inches='tight', dpi=150)
    plt.savefig(os.path.join(RESULTS_DIR, 'all_figures.png'), bbox_inches='tight', dpi=150)
    print(f"Figures saved → {RESULTS_DIR}/all_figures.pdf  +  .png")
    plt.show()

    # ── Summary Table ────────────────────────────────────────
    print("\n" + "=" * 75)
    print(f"{'Scenario':<30} {'Throughput (Mbps)':>18} {'P95 Latency (ms)':>18} {'Fairness':>10}")
    print("-" * 75)
    key_scenarios = [
        (0,  1, 0), (0,  5, 0),
        (5,  1, 1), (5,  3, 1),
        (10, 5, 5), (10, 1, 5),
    ]
    for key in key_scenarios:
        if key in aggregated:
            m, f, l = key
            d = aggregated[key]
            label = f'm={m}m/s  f={f}flows  l={l}%'
            print(f"{label:<30} {d['mean_throughput']:>15.2f} Mbps"
                  f"  {d['mean_latency']:>12.1f} ms"
                  f"  {d['mean_fairness']:>10.4f}")
    print("=" * 75)

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__' or '__file__' not in dir():
    # Works whether run as a script or pasted into a Jupyter cell
    results_db = run_experiment()
    aggregated = aggregate(results_db)
    plot(aggregated, results_db)
