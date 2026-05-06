# EE6750 Group 15 — TCP Performance over WiFi

**Course:** EE6750 — Transport over Wireless  
**Topic Track:** Transport over Wireless  
**Team:** Charles McClary  

---

## Overview

This project evaluates **TCP CUBIC performance over emulated IEEE 802.11g WiFi** using Mininet-WiFi on an Ubuntu virtual machine. We systematically vary mobility speed, number of competing flows, and channel loss rate across 240 controlled experimental runs to quantify the impact of wireless impairments on TCP throughput, latency, retransmissions, and fairness.

---

## Research Question

> How does increasing mobility and channel loss affect TCP throughput and latency over WiFi?

---

## Hypotheses

| ID | Hypothesis |
|----|------------|
| H1 | Increasing mobility speed decreases TCP throughput and increases 95th-percentile latency |
| H2 | Higher packet loss rates increase TCP retransmissions and reduce flow fairness |
| H3 | Under high contention (multiple flows), per-flow throughput decreases due to MAC-layer CSMA/CA overhead |

---

## Testbed & Tools

| Component | Details |
|-----------|---------|
| Emulation platform | Mininet-WiFi on Ubuntu 22.04 (VirtualBox) |
| WiFi driver | mac80211_hwsim (10 radios) |
| Access Point | 802.11g, Channel 1, Range 116 m |
| Propagation model | Log-distance (exponent = 3) |
| Traffic generator | iperf3 — TCP CUBIC |
| Packet capture | Wireshark / tshark |
| Automation | Python scripting |
| Random seed | 42 (fixed for reproducibility) |

---

## Experimental Parameters

| Variable | Values |
|----------|--------|
| Mobility speed | 0, 2, 5, 10 m/s |
| Flow count | 1, 3, 5 TCP flows |
| Channel loss rate | 0%, 1%, 3%, 5% |
| Trial duration | 30 seconds |
| Trials per scenario | 5 |
| **Total runs** | **240** |

---

## Scenarios

| ID | Label | Mobility | Flows | Loss |
|----|-------|----------|-------|------|
| S1 | Baseline | 0 m/s | 1 | 0% |
| S2 | Variant-A | 5 m/s | 3 | 1% |
| S3 | Variant-B | 10 m/s | 5 | 5% |

---

## Metrics Collected

- Mean throughput (Mbps)
- Goodput (Mbps)
- 95th-percentile RTT latency (ms)
- TCP retransmission count
- Jain's Fairness Index — J = (Σxᵢ)² / (n × Σxᵢ²)
- Effective packet loss % (from pcap analysis)

---

## Key Results

| Scenario | Throughput | P95 Latency | Retransmissions | Fairness |
|----------|-----------|-------------|-----------------|----------|
| S1 Baseline | 1497 Mbps | 3.1 ms | ~25 | 1.000 |
| S2 Variant-A | ~350 Mbps | 42.1 ms | ~500 | 0.999 |
| S3 Variant-B | ~175 Mbps | 45.0 ms | ~2500 | 0.999 |

**Key finding:** Packet loss rate is the dominant factor driving TCP degradation in software emulation — retransmissions increased **135x** from 0% to 5% loss, and P95 latency grew **15x** from baseline to worst-case. Mobility had minimal throughput impact due to mac80211_hwsim limitations.

---

## Repository Structure

```
ee6750-tcp-wifi/
├── ee6750_mininet_final.py   # Full Mininet-WiFi experiment (run on Ubuntu VM)
├── ee6750_experiment.py      # Simulation version (runs anywhere, no Mininet needed)
├── results/
│   ├── raw_results.json      # Raw trial data
│   ├── all_figures.pdf       # All 5 figures (publication quality)
│   └── all_figures.png       # All 5 figures (PNG)
├── EE6750_Group15_IEEE_Paper.docx   # IEEE-format term paper
├── EE6750_Group15_Presentation.pptx # 11-slide presentation
└── README.md
```

---

## How to Run

### Option 1 — Simulation (runs on Windows, Mac, or Linux, no Mininet needed)

```bash
pip install numpy matplotlib scipy pandas
python ee6750_experiment.py
```

### Option 2 — Full Mininet-WiFi (requires Ubuntu VM)

```bash
# Install dependencies
sudo apt update
sudo apt install python3 iperf3 tshark
pip3 install numpy matplotlib

# Install Mininet-WiFi
git clone https://github.com/intrig-unicamp/mininet-wifi
cd mininet-wifi && sudo util/install.sh -Wln
cd ..

# Load WiFi kernel module
sudo modprobe mac80211_hwsim radios=10

# Run experiment
sudo python3 ee6750_mininet_final.py
```

Results are saved to the `results/` folder as JSON data and PDF/PNG figures.

---

## Figures

| Figure | Description |
|--------|-------------|
| Fig 1 | Throughput vs. Mobility Speed (0% loss, 95% CI, n=5) |
| Fig 2 | Latency CDF for 3 labeled scenarios (dotted = P95) |
| Fig 3 | Jain's Fairness Index vs. number of flows |
| Fig 4 | Retransmissions heatmap (mobility × loss rate) |
| Fig 5 | Baseline vs. Variant comparison across all metrics |

---

## Cross-Layer Causal Chain

```
Mobility ↑  →  SINR ↓  (LogDistance model)
            →  Link-layer loss ↑
            →  TCP retransmits ↑
            →  cwnd reduction
            →  Throughput ↓  ·  Latency ↑
            →  Fairness ↓ under multi-flow contention
```

---

## References

1. J. F. Kurose and K. W. Ross, *Computer Networking: A Top-Down Approach*, 8th ed. Pearson, 2021.
2. H. Balakrishnan et al., "A comparison of mechanisms for improving TCP performance over wireless links," *IEEE/ACM Trans. Netw.*, vol. 5, no. 6, pp. 756–769, 1997.
3. R. de Oliveira et al., "Mininet-WiFi: A platform for hybrid physical-virtual SDW networking research," in *Proc. IEEE GLOBECOM*, 2014.
4. G. Bianchi, "Performance analysis of the IEEE 802.11 DCF," *IEEE J. Sel. Areas Commun.*, vol. 18, no. 3, pp. 535–547, 2000.
5. S. Ha, I. Rhee, and L. Xu, "CUBIC: A new TCP-friendly high-speed TCP variant," *ACM SIGOPS Oper. Syst. Rev.*, vol. 42, no. 5, pp. 64–74, 2008.
6. R. Ludwig and R. H. Katz, "The Eifel algorithm," *ACM SIGCOMM Comput. Commun. Rev.*, vol. 30, no. 1, pp. 30–36, 2000.

---

*EE6750 — Transport over Wireless — Group 15 — Spring 2025*
