# srv2

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.42 |
| Papel | Roteador |
| Camada | Borda / Roteamento |
| Fabricante | Linux |
| Sistema | Linux (lldpd) |
| Versão | 6.17.0-1022-azure |
| Modelo | Debian GNU/Linux 12 (bookworm) |
| Serial | Virtual Machine |
| Uptime | 0d 0h 3m |
| Localização | Containerlab NetTopo Lab |
| Contato | lab@nettopo.local |
| MAC do chassis | aa:c1:ab:c6:1a:3f |
| Coletado via | ssh, snmp |
| Descrição | Linux srv2 6.17.0-1022-azure #22-Ubuntu SMP Mon Jul 27 17:24:03 UTC 2026 x86_64 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| eth1 | [core-srl1](core-srl1.md) | ethernet-1/3 | physical | lldp | 10000 Mbps | 10.10.3.0/30 |
| eth2 | [core-srl2](core-srl2.md) | ethernet-1/3 | physical | lldp | 10000 Mbps | 10.10.4.0/30 |
| eth1 | [core-srl2](core-srl2.md) | ethernet-1/4 | physical | lldp | 10000 Mbps | 192.168.20.0/24 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| eth0 |  | 172.20.20.42/24 172.20.20.41/24 172.20.20.31/24 | up | up | 10000 Mbps | 1500 |  |
| eth1 |  | 192.168.20.10/24 192.168.10.10/24 10.10.3.2/30 | up | up | 10000 Mbps | 9500 |  |
| lo |  | 127.0.0.1/8 | up | up | 10 Mbps | 65536 |  |
| eth3 |  | 192.168.10.1/24 | up | up | 10000 Mbps | 9500 |  |
| eth2 |  | 10.10.4.2/30 | up | up | 10000 Mbps | 9500 |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | eth1 | core-srl2 | ethernet-1/4 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 6.17.0-1022-azur |
| lldp | eth1 | dist-frr1 | eth3 | 172.20.20.31 | Debian GNU/Linux 12 (bookworm) Linux 6.17.0-1022-azure #22-U |
| lldp | eth3 | srv1 | eth1 | 172.20.20.41 | Debian GNU/Linux 12 (bookworm) Linux 6.17.0-1022-azure #22-U |
| lldp | eth2 | core-srl2 | ethernet-1/3 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 6.17.0-1022-azur |
| lldp | eth1 | core-srl1 | ethernet-1/3 | 172.20.20.21 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl1 6.17.0-1022-azur |

## Rotas (6)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 0.0.0.0/0 | 172.20.20.1 | eth0 |  |  |
| 172.20.20.0/24 |  | eth0 | kernel |  |
| 192.168.20.0/24 |  | eth1 | kernel |  |
| 192.168.10.0/24 |  | eth1 | kernel |  |
| 10.10.3.0/30 |  | eth1 | kernel |  |
| 10.10.4.0/30 |  | eth2 | kernel |  |

## ARP (1)

| IP | MAC | Interface |
|---|---|---|
| 172.20.20.1 | 9a:2a:d1:1d:53:fa | eth0 |
