# srv2

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.42 |
| Papel | Servidor/Host |
| Camada | Endpoints |
| Fabricante | Linux |
| Sistema | Linux (lldpd) |
| Versão | 7.0.0-1017-azure |
| Modelo | Virtual Machine |
| Uptime | 0d 0h 2m |
| Localização | Laboratório Containerlab |
| Contato | lab@nettopo.local |
| Coletado via | ssh, snmp |
| Descrição | Linux srv2 7.0.0-1017-azure #17~24.04.1-Ubuntu SMP PREEMPT Thu Sep 24 18:46:57 UTC 2026 x86_64 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| eth1 | [core-srl2](core-srl2.md) | ethernet-1/4 | physical | lldp | 25000 Mbps | 192.168.20.0/24 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| eth0 |  | 172.20.20.42/24 | up | up |  | 1500 |  |
| eth1 |  | 192.168.20.10/24 | up | up |  | 9500 |  |
| lo |  |  |  |  |  |  |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | eth1 | core-srl2 | ethernet-1/4 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 7.0.0-1017-azure |

## Rotas (3)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 0.0.0.0/0 | 172.20.20.1 | eth0 |  |  |
| 172.20.20.0/24 |  | eth0 | kernel |  |
| 192.168.20.0/24 |  | eth1 | kernel |  |

## ARP (1)

| IP | MAC | Interface |
|---|---|---|
| 172.20.20.1 | 12:5b:7a:d1:46:60 | eth0 |
