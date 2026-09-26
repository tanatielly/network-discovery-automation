# core-srl2

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.22 |
| Papel | Switch L3 |
| Camada | Núcleo (Core) |
| Fabricante | Nokia |
| Sistema | SR Linux |
| Versão | 25.10.5-111 |
| Uptime | 0d 0h 2m |
| Localização | Core - Rack C2 |
| Coletado via | netconf, snmp |
| Descoberto a partir de | core-srl1 |
| Descrição | SRLinux-v25.10.5-111-g6fbddec84ef 7220 IXR-D2L Copyright (c) 2000-2026 Nokia. Kernel 6.17.0-1022-azure #22-Ubuntu SMP Mon Jul 27 17:24:03 UTC 2026 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| ethernet-1/2 | [core-srl1](core-srl1.md) | ethernet-1/2 | physical | lldp | 25000 Mbps | 10.10.0.0/31 |
| mgmt0 | [core-srl1](core-srl1.md) | mgmt0 | physical | lldp | 1000 Mbps | 172.20.20.0/24 |
| ethernet-1/1 | edge-mk2 | ether4 | physical | lldp | 25000 Mbps | 10.10.2.0/30 |
| ethernet-1/3 | [dist-frr1](dist-frr1.md) | eth2 | physical | lldp | 10000 Mbps | 10.10.4.0/30 |
| ethernet-1/4 | [dist-frr1](dist-frr1.md) | eth1 | physical | lldp | 10000 Mbps | 192.168.20.0/24 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| ethernet-1/1 | to edge-mk2 ether4 | 10.10.2.2/30 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/2 | to core-srl1 e1-2 | 10.10.0.1/31 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/3 | to dist-frr1 eth2 | 10.10.4.1/30 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/4 | to srv2 eth1 | 192.168.20.1/24 | up | up | 25000 Mbps | 9232 |  |
| ethernet-1/5 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/6 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/7 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/8 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/9 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/10 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/11 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/12 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/13 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/14 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/15 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/16 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/17 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/18 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/19 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/20 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/21 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/22 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/23 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/24 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/25 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/26 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/27 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/28 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/29 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/30 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/31 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/32 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/33 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/34 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/35 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/36 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/37 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/38 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/39 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/40 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/41 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/42 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/43 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/44 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/45 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/46 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/47 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/48 |  |  | down | down | 25000 Mbps | 0 |  |
| ethernet-1/49 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/50 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/51 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/52 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/53 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/54 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/55 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/56 |  |  | down | down | 100000 Mbps | 0 |  |
| ethernet-1/57 |  |  | down | down | 10000 Mbps | 0 |  |
| ethernet-1/58 |  |  | down | down | 10000 Mbps | 0 |  |
| mgmt0 |  | 172.20.20.22/24 | up | up | 1000 Mbps | 1514 |  |
| ethernet-1/1.0 |  |  | up | up |  | 1500 |  |
| ethernet-1/2.0 |  |  | up | up |  | 1500 |  |
| ethernet-1/3.0 |  |  | up | up |  | 1500 |  |
| ethernet-1/4.0 |  |  | up | up |  | 1500 |  |
| mgmt0.0 |  |  | up | up |  | 0 |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | ethernet-1/1 | edge-mk2 | ether4 | 10.10.2.1 | MikroTik RouterOS 7.16.2 (stable) 2024-11-26 12:09:40 CHR |
| lldp | ethernet-1/2 | core-srl1 | ethernet-1/2 | 172.20.20.21 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl1 6.17.0-1022-azur |
| lldp | ethernet-1/3 | dist-frr1 | eth2 | 172.20.20.31 | Debian GNU/Linux 12 (bookworm) Linux 6.17.0-1022-azure #22-U |
| lldp | ethernet-1/4 | srv2 | eth1 | 172.20.20.42 | Debian GNU/Linux 12 (bookworm) Linux 6.17.0-1022-azure #22-U |
| lldp | mgmt0 | core-srl1 | mgmt0 | 172.20.20.21 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl1 6.17.0-1022-azur |
