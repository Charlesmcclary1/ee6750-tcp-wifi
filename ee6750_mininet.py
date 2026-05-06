#!/usr/bin/env python3
"""
EE6750 Group 15 - TCP over WiFi
Full Mininet-WiFi Implementation
Run with: sudo python3 ee6750_mininet.py
Requires: Ubuntu 20.04/22.04, Mininet-WiFi, iperf3, tshark, matplotlib
"""

import os
import sys
import json
import time
import subprocess
import itertools
import statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from collections import defaultdict

np.random.seed(42)

MOBILITY_SPEEDS = [0, 2, 5, 10]
FLOW_COUNTS = [1, 3, 5]
LOSS_RATES = [0, 1, 3, 5]
TRIALS = 5
DURATION = 30
RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

from mininet.log import setLogLevel
from mininet.node import Controller
from mn_wifi.net import Mininet_wifi
from mn_wifi.node import OVSKernelAP
from mn_wifi.cli import CLI
from mn_wifi.link import wmediumd
from mn_wifi.wmediumdConnector import interference

def build_topology(num_flows):
    setLogLevel('warning')
    net = Mininet_wifi(
        controller=Controller,
        link=wmediumd,
        wmediumd_mode=interference
    )
    c0 = net.addController('c0')
    ap1 = net.addAccessPoint(
        'ap1',
        ssid='ee6750-net',
        mode='n',
        channel='6',
        position='50,50,0',
        range=100
    )
    stations = []
    for i in range(1, num_flows + 1):
        sta = net.addStation(
            'sta%d' % i,
            ip='10.0.0.%d/24' % i,
            position='%d,10,0' % (10 + i * 8)
        )
        stations.append(sta)
    recv = net.addStation(
        'recv',
        ip='10.0.0.%d/24' % (num_flows + 1),
        position='50,80,0'
    )
    net.setPropagationModel(model='logDistance', exp=3)
    net.configureWifiNodes()
    net.build()
    c0.start()
    ap1.start([c0])
    return net, stations, recv

def set_mobility(net, stations, recv, speed):
    if speed == 0:
        return
    net.startMobility(time=0)
    for sta in stations:
        net.mobility(
            sta,
            'startpos',
            time=0,
            position=sta.position
        )
        net.mobility(
            sta,
            'endpos',
            time=DURATION,
            position='%d,%d,0' % (
                np.random.randint(5, 95),
                np.random.randint(5, 95)
            )
        )
    net.stopMobility(time=DURATION + 2)

def set_loss(stations, loss_pct):
    for sta in stations:
        intf = sta.defaultIntf()
        if loss_pct > 0:
            sta.cmd(
                'tc qdisc replace dev %s root netem loss %d%%' % (intf, loss_pct)
            )
        else:
            sta.cmd(
                'tc qdisc del dev %s root 2>/dev/null; true' % intf
            )

def start_packet_capture(trial_dir, duration):
    pcap = os.path.join(trial_dir, 'capture.pcap')
    proc = subprocess.Popen(
        [
            'tshark', '-i', 'any',
            '-a', 'duration:%d' % (duration + 5),
            '-w', pcap, '-q'
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    return proc, pcap

def launch_iperf_flows(stations, recv, num_flows, duration, trial_dir):
    recv_ip = recv.IP()
    server_procs = []
    for i in range(num_flows):
        port = 5201 + i
        log = os.path.join(trial_dir, 'server_%d.json' % (i + 1))
        p = recv.popen(
            'iperf3 -s -p %d -1 --json > %s 2>/dev/null' % (port, log),
            shell=True
        )
        server_procs.append(p)
    time.sleep(1)
    client_procs = []
    log_paths = []
    for i in range(num_flows):
        sta = stations[i]
        port = 5201 + i
        log = os.path.join(trial_dir, 'flow_%d.json' % (i + 1))
        log_paths.append(log)
        p = sta.popen(
            'iperf3 -c %s -p %d -t %d --json -C cubic > %s 2>/dev/null'
            % (recv_ip, port, duration, log),
            shell=True
        )
        client_procs.append(p)
    for p in client_procs:
        p.wait()
    time.sleep(1)
    for p in server_procs:
        p.terminate()
    return log_paths

def parse_loss_from_pcap(pcap_path):
    try:
        out = subprocess.check_output(
            [
                'tshark', '-r', pcap_path,
                '-Y', 'tcp.analysis.retransmission',
                '-q'
            ],
            stderr=subprocess.DEVNULL,
            text=True
        )
        retx = max(0, out.strip().count('\n'))
        total_out = subprocess.check_output(
            [
                'tshark', '-r', pcap_path,
                '-Y', 'tcp', '-q'
            ],
            stderr=subprocess.DEVNULL,
            text=True
        )
        total = max(1, total_out.strip().count('\n'))
        return round((retx / total) * 100, 2)
    except Exception:
        return 0.0

def analyze(log_paths, pcap_path):
    throughputs = []
    goodputs = []
    retransmits = []
    rtt_samples = []
    for log in log_paths:
        if not os.path.exists(log):
            continue
        try:
            with open(log) as f:
                data = json.load(f)
            end = data['end']
            bps = end['sum_sent']['bits_per_second']
            throughputs.append(bps / 1e6)
            gbps = end['sum_received']['bits_per_second']
            goodputs.append(gbps / 1e6)
            retx = end['sum_sent'].get('retransmits', 0)
            retransmits.append(retx)
            for stream in end.get('streams', []):
                rtt_us = stream.get('sender', {}).get('mean_rtt', 0)
                if rtt_us > 0:
                    rtt_samples.append(rtt_us / 1000.0)
        except (json.JSONDecodeError, KeyError):
            continue
    if not throughputs:
        return None
    rtt_samples.sort()
    n = len(throughputs)
    p95_idx = int(0.95 * len(rtt_samples))
    latency_p95 = rtt_samples[p95_idx] if rtt_samples else 0.0
    loss_pct = parse_loss_from_pcap(pcap_path)
    sum_t = sum(throughputs)
    sum_t2 = sum(t ** 2 for t in throughputs)
    fairness = (sum_t ** 2) / (n * sum_t2) if sum_t2 > 0 else 1.0
    return {
        'throughputs': throughputs,
        'mean_throughput': statistics.mean(throughputs),
        'mean_goodput': statistics.mean(goodputs),
        'retransmits': sum(retransmits),
        'latency_p95': round(latency_p95, 2),
        'rtt_samples': rtt_samples,
        'loss_pct': loss_pct,
        'fairness': round(fairness, 4),
        'num_flows': n,
    }

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
            return 1.96 * statistics.stdev(vals) / (len(vals) ** 0.5)
        throughputs = [m['mean_throughput'] for m in trial_metrics]
        latencies = [m['latency_p95'] for m in trial_metrics]
        fairnesses = [m['fairness'] for m in trial_metrics]
        retransmits = [m['retransmits'] for m in trial_metrics]
        all_rtt = []
        for m in trial_metrics:
            all_rtt.extend(m.get('rtt_samples', []))
        aggregated[key] = {
            'mean_throughput': statistics.mean(throughputs),
            'ci_throughput': ci(throughputs),
            'mean_latency': statistics.mean(latencies),
            'ci_latency': ci(latencies),
            'mean_fairness': statistics.mean(fairnesses),
            'ci_fairness': ci(fairnesses),
            'mean_retransmits': statistics.mean(retransmits),
            'all_rtt': all_rtt,
        }
    return aggregated

def plot(aggregated):
    colors = ['#2E86AB', '#E84855', '#3BB273']
    fig = plt.figure(figsize=(18, 14))
    fig.patch.set_facecolor('#F8F9FA')
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.32)
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
            ax1.errorbar(
                xs, ys, yerr=errs,
                marker='o', linewidth=2, markersize=7,
                capsize=5, color=colors[idx],
                label='%d flow(s)' % f, zorder=3
            )
    ax1.set_xlabel('Mobility speed (m/s)', fontsize=11)
    ax1.set_ylabel('Throughput (Mbps)', fontsize=11)
    ax1.set_title('Fig 1 - Throughput vs Mobility Speed\n(0%% loss, 95%% CI)', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_xticks(MOBILITY_SPEEDS)
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor('#FFFFFF')
    scenarios = [
        ((0, 1, 0), 'Static, 1 flow, 0%% loss', '#2E86AB'),
        ((5, 3, 1), 'Moderate mobility, 3 flows, 1%% loss', '#F4A261'),
        ((10, 5, 5), 'High mobility, 5 flows, 5%% loss', '#E84855'),
    ]
    for key, label, color in scenarios:
        if key in aggregated:
            rtt = sorted(aggregated[key]['all_rtt'])
            if rtt:
                n = len(rtt)
                cdf = np.arange(1, n + 1) / n
                ax2.plot(rtt, cdf, linewidth=2, color=color, label=label)
                p95 = rtt[int(0.95 * n)]
                ax2.axvline(p95, color=color, linestyle=':', alpha=0.6, linewidth=1)
    ax2.set_xlabel('RTT latency (ms)', fontsize=11)
    ax2.set_ylabel('CDF', fontsize=11)
    ax2.set_title('Fig 2 - Latency CDF by Scenario\n(dotted = 95th percentile)', fontsize=12, fontweight='bold')
    ax2.legend(fontsize=8, loc='lower right')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.set_xlim(left=0)
    ax2.set_ylim(0, 1.05)
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.set_facecolor('#FFFFFF')
    loss_colors = ['#2E86AB', '#3BB273', '#F4A261', '#E84855']
    for idx, l in enumerate(LOSS_RATES):
        xs, ys, errs = [], [], []
        for f in FLOW_COUNTS:
            vals = [
                aggregated[(m, f, l)]['mean_fairness']
                for m in MOBILITY_SPEEDS if (m, f, l) in aggregated
            ]
            if vals:
                xs.append(f)
                ys.append(float(np.mean(vals)))
                errs.append(
                    1.96 * float(np.std(vals, ddof=1)) / np.sqrt(len(vals))
                    if len(vals) > 1 else 0
                )
        if xs:
            ax3.errorbar(
                xs, ys, yerr=errs,
                marker='s', linewidth=2, markersize=7,
                capsize=5, color=loss_colors[idx],
                label='%d%% loss' % l, zorder=3
            )
    ax3.set_xlabel('Number of flows', fontsize=11)
    ax3.set_ylabel("Jain's fairness index", fontsize=11)
    ax3.set_title("Fig 3 - Fairness vs Contention Load", fontsize=12, fontweight='bold')
    ax3.set_ylim(0, 1.05)
    ax3.set_xticks(FLOW_COUNTS)
    ax3.axhline(1.0, color='gray', linestyle=':', linewidth=1, alpha=0.5)
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3, linestyle='--')
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.set_facecolor('#FFFFFF')
    heat_data = np.zeros((len(LOSS_RATES), len(MOBILITY_SPEEDS)))
    for li, l in enumerate(LOSS_RATES):
        for mi, m in enumerate(MOBILITY_SPEEDS):
            vals = [
                aggregated[(m, f, l)]['mean_retransmits']
                for f in FLOW_COUNTS if (m, f, l) in aggregated
            ]
            heat_data[li, mi] = float(np.mean(vals)) if vals else 0
    im = ax4.imshow(heat_data, cmap='YlOrRd', aspect='auto')
    ax4.set_xticks(range(len(MOBILITY_SPEEDS)))
    ax4.set_xticklabels(['%d m/s' % m for m in MOBILITY_SPEEDS], fontsize=9)
    ax4.set_yticks(range(len(LOSS_RATES)))
    ax4.set_yticklabels(['%d%% loss' % l for l in LOSS_RATES], fontsize=9)
    ax4.set_title('Fig 4 - Avg Retransmissions', fontsize=12, fontweight='bold')
    plt.colorbar(im, ax=ax4, label='Retransmissions')
    for li in range(len(LOSS_RATES)):
        for mi in range(len(MOBILITY_SPEEDS)):
            ax4.text(
                mi, li, '%.0f' % heat_data[li, mi],
                ha='center', va='center', fontsize=8,
                color='black' if heat_data[li, mi] < heat_data.max() * 0.6 else 'white'
            )
    fig.suptitle(
        'EE6750 Group 15 - TCP Performance over WiFi\nMobility & Contention Analysis',
        fontsize=15, fontweight='bold', y=1.01
    )
    pdf_path = os.path.join(RESULTS_DIR, 'all_figures.pdf')
    png_path = os.path.join(RESULTS_DIR, 'all_figures.png')
    plt.savefig(pdf_path, bbox_inches='tight', dpi=150)
    plt.savefig(png_path, bbox_inches='tight', dpi=150)
    print('Figures saved: %s and %s' % (pdf_path, png_path))
    plt.close()

def print_summary(aggregated):
    print('')
    print('=' * 75)
    print('%-30s %18s %18s %10s' % ('Scenario', 'Throughput (Mbps)', 'P95 Latency (ms)', 'Fairness'))
    print('-' * 75)
    key_scenarios = [
        (0, 1, 0), (0, 5, 0),
        (5, 1, 1), (5, 3, 1),
        (10, 5, 5), (10, 1, 5),
    ]
    for key in key_scenarios:
        if key in aggregated:
            m, f, l = key
            d = aggregated[key]
            label = 'm=%dm/s f=%d l=%d%%' % (m, f, l)
            print('%-30s %15.2f Mbps %12.1f ms %10.4f' % (
                label,
                d['mean_throughput'],
                d['mean_latency'],
                d['mean_fairness']
            ))
    print('=' * 75)

def main():
    if os.geteuid() != 0:
        print('ERROR: Must run as root. Use: sudo python3 ee6750_mininet.py')
        sys.exit(1)
    results_db = []
    combos = list(itertools.product(MOBILITY_SPEEDS, FLOW_COUNTS, LOSS_RATES))
    total = len(combos) * TRIALS
    run = 0
    print('=' * 60)
    print('EE6750 Group 15 - TCP over WiFi (Mininet-WiFi)')
    print('Scenarios: %d | Trials: %d | Total runs: %d' % (len(combos), TRIALS, total))
    print('=' * 60)
    for m, f, l in combos:
        for trial in range(1, TRIALS + 1):
            run += 1
            pct = int(run / total * 30)
            bar = '#' * pct + '.' * (30 - pct)
            print('\r[%s] %d/%d  m=%d f=%d l=%d%% trial=%d' % (
                bar, run, total, m, f, l, trial
            ), end='', flush=True)
            trial_dir = os.path.join(
                RESULTS_DIR, 'm%d_f%d_l%d_t%d' % (m, f, l, trial)
            )
            os.makedirs(trial_dir, exist_ok=True)
            net = None
            try:
                net, stations, recv = build_topology(f)
                set_mobility(net, stations, recv, m)
                set_loss(stations, l)
                pcap_proc, pcap_path = start_packet_capture(trial_dir, DURATION)
                log_paths = launch_iperf_flows(
                    stations, recv, f, DURATION, trial_dir
                )
                pcap_proc.wait()
                metrics = analyze(log_paths, pcap_path)
                results_db.append({
                    'm': m, 'f': f, 'l': l,
                    'trial': trial, 'metrics': metrics
                })
            except Exception as e:
                print('\n  ERROR in run %d: %s' % (run, str(e)))
                results_db.append({
                    'm': m, 'f': f, 'l': l,
                    'trial': trial, 'metrics': None
                })
            finally:
                if net is not None:
                    try:
                        net.stop()
                    except Exception:
                        pass
                subprocess.call(
                    ['mn', '--clean'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
    print('\n')
    print('Experiment complete. %d runs finished.' % total)
    raw_path = os.path.join(RESULTS_DIR, 'raw_results.json')
    serializable = []
    for r in results_db:
        entry = dict(r)
        if entry['metrics']:
            m2 = dict(entry['metrics'])
            m2.pop('rtt_samples', None)
            m2.pop('throughputs', None)
            entry['metrics'] = m2
        serializable.append(entry)
    with open(raw_path, 'w') as fout:
        json.dump(serializable, fout, indent=2)
    print('Raw results saved: %s' % raw_path)
    aggregated = aggregate(results_db)
    plot(aggregated)
    print_summary(aggregated)

if __name__ == '__main__':
    main()
