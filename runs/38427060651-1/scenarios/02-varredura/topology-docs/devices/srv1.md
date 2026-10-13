# srv1

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.41 |
| Papel | Servidor/Host |
| Camada | Endpoints |
| Fabricante | Linux |
| Sistema | Linux (lldpd) |
| Versão | 6.17.0-1022-azure |
| Modelo | Virtual Machine |
| Uptime | 0d 0h 2m |
| Localização | Containerlab NetTopo Lab |
| Contato | lab@nettopo.local |
| Coletado via | ssh, snmp |
| Descrição | Linux srv1 6.17.0-1022-azure #22-Ubuntu SMP Mon Jul 27 17:24:03 UTC 2026 x86_64 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| eth1 | [dist-frr1](dist-frr1.md) | eth3 | physical | lldp |  | 192.168.10.0/24 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| eth0 |  | 172.20.20.41/24 | up | up |  | 1500 |  |
| eth1 |  | 192.168.10.10/24 | up | up |  | 9500 |  |
| lo |  |  |  |  |  |  |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | eth1 | dist-frr1 | eth3 | 172.20.20.31 | Debian GNU/Linux 12 (bookworm) Linux 6.17.0-1022-azure #22-U |

## Rotas (3)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 0.0.0.0/0 | 172.20.20.1 | eth0 |  |  |
| 172.20.20.0/24 |  | eth0 | kernel |  |
| 192.168.10.0/24 |  | eth1 | kernel |  |

## ARP (1)

| IP | MAC | Interface |
|---|---|---|
| 172.20.20.1 | be:4a:d3:c9:19:12 | eth0 |
