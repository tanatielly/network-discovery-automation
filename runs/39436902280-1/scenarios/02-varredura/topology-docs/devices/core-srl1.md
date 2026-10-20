# core-srl1

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.21 |
| Papel | Switch L3 |
| Camada | Núcleo (Core) |
| Fabricante | Nokia |
| Sistema | SR Linux |
| Versão | v25.10.5-111-g6fbddec84ef |
| Modelo | 7220 IXR-D2L |
| Serial | Sim Serial No. |
| Uptime | 0d 0h 2m |
| Localização | Core - Rack C1 |
| MAC do chassis | 1a:05:00:ff:00:00 |
| Coletado via | rest, snmp |
| Descrição | SRLinux-v25.10.5-111-g6fbddec84ef 7220 IXR-D2L Copyright (c) 2000-2026 Nokia. Kernel 7.0.0-1017-azure #17~24.04.1-Ubuntu SMP PREEMPT Thu Sep 24 18:46:57 UTC 2026 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| ethernet-1/1 | [edge-mk1](edge-mk1.md) | ether4 | physical | lldp | 25000 Mbps | 10.10.1.0/30 |
| ethernet-1/2 | [core-srl2](core-srl2.md) | ethernet-1/2 | physical | lldp | 25000 Mbps | 10.10.0.0/31 |
| ethernet-1/3 | [dist-frr1](dist-frr1.md) | eth1 | physical | lldp | 25000 Mbps | 10.10.3.0/30 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| ethernet-1/1 | to edge-mk1 ether4 | 10.10.1.2/30 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/2 | to core-srl2 e1-2 | 10.10.0.0/31 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/3 | to dist-frr1 eth1 | 10.10.3.1/30 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/4 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/5 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/6 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/7 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/8 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/9 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/10 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/11 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/12 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/13 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/14 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/15 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/16 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/17 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/18 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/19 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/20 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/21 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/22 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/23 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/24 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/25 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/26 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/27 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/28 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/29 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/30 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/31 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/32 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/33 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/34 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/35 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/36 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/37 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/38 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/39 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/40 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/41 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/42 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/43 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/44 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/45 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/46 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/47 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/48 |  |  |  | down | 25000 Mbps |  |  |
| ethernet-1/49 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/50 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/51 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/52 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/53 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/54 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/55 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/56 |  |  |  | down | 100000 Mbps |  |  |
| ethernet-1/57 |  |  |  | down | 10000 Mbps |  |  |
| ethernet-1/58 |  |  |  | down | 10000 Mbps |  |  |
| mgmt0 |  | 172.20.20.21/24 | up | up | 1000 Mbps | 1514 |  |
| ethernet-1/1.0 |  |  |  |  |  |  |  |
| ethernet-1/2.0 |  |  |  |  |  |  |  |
| ethernet-1/3.0 |  |  |  |  |  |  |  |
| mgmt0.0 |  |  |  |  |  |  |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | ethernet-1/1 | edge-mk1 | ether4 | 10.10.1.1 | MikroTik RouterOS 7.16.2 (stable) 2024-11-26 12:09:40 CHR |
| lldp | ethernet-1/2 | core-srl2 | ethernet-1/2 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 7.0.0-1017-azure |
| lldp | ethernet-1/3 | dist-frr1 | eth1 | 172.20.20.31 | Debian GNU/Linux 12 (bookworm) Linux 7.0.0-1017-azure #17~24 |
| lldp | mgmt0 | core-srl2 | mgmt0 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 7.0.0-1017-azure |
