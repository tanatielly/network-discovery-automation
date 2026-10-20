# dist-frr1

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.31 |
| Papel | Roteador |
| Camada | Distribuição |
| Fabricante | Linux |
| Sistema | Linux (lldpd) |
| Versão | 7.0.0-1017-azure |
| Modelo | Virtual Machine |
| Uptime | 0d 0h 2m |
| Localização | Laboratório Containerlab |
| Contato | lab@nettopo.local |
| Coletado via | ssh, snmp |
| Descrição | Linux dist-frr1 7.0.0-1017-azure #17~24.04.1-Ubuntu SMP PREEMPT Thu Sep 24 18:46:57 UTC 2026 x86_64 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| eth1 | [core-srl1](core-srl1.md) | ethernet-1/3 | physical | lldp | 25000 Mbps | 10.10.3.0/30 |
| eth2 | [core-srl2](core-srl2.md) | ethernet-1/3 | physical | lldp | 25000 Mbps | 10.10.4.0/30 |
| eth3 | [srv1](srv1.md) | eth1 | physical | lldp |  | 192.168.10.0/24 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| eth0 |  | 172.20.20.31/24 | up | up |  | 1500 |  |
| eth1 |  | 10.10.3.2/30 | up | up |  | 9500 |  |
| eth2 |  | 10.10.4.2/30 | up | up |  | 9500 |  |
| eth3 |  | 192.168.10.1/24 | up | up |  | 9500 |  |
| lo |  |  |  |  |  |  |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | eth1 | core-srl1 | ethernet-1/3 | 172.20.20.21 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl1 7.0.0-1017-azure |
| lldp | eth2 | core-srl2 | ethernet-1/3 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 7.0.0-1017-azure |
| lldp | eth3 | srv1 | eth1 | 172.20.20.41 | Debian GNU/Linux 12 (bookworm) Linux 7.0.0-1017-azure #17~24 |

## Rotas (5)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 0.0.0.0/0 | 172.20.20.1 | eth0 |  |  |
| 10.10.3.0/30 |  | eth1 | kernel |  |
| 10.10.4.0/30 |  | eth2 | kernel |  |
| 172.20.20.0/24 |  | eth0 | kernel |  |
| 192.168.10.0/24 |  | eth3 | kernel |  |

## ARP (1)

| IP | MAC | Interface |
|---|---|---|
| 172.20.20.1 | 12:5b:7a:d1:46:60 | eth0 |
