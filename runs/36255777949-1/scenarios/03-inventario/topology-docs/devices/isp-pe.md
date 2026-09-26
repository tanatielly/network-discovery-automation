# isp-pe

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.2 |
| Papel | Roteador |
| Camada | Borda / Roteamento |
| Fabricante | Linux |
| Sistema | Linux (lldpd) |
| Versão | 6.17.0-1022-azure |
| Uptime | 0d 0h 3m |
| Localização | Containerlab NetTopo Lab |
| Contato | lab@nettopo.local |
| MAC do chassis | aa:c1:ab:7c:4c:59 |
| Coletado via | snmp |
| Descrição | Linux isp-pe 6.17.0-1022-azure #22-Ubuntu SMP Mon Jul 27 17:24:03 UTC 2026 x86_64 |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| eth1 | [edge-mk1](edge-mk1.md) | ether2 | physical | lldp, bgp | 10000 Mbps | 200.200.10.0/30 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| lo |  | 127.0.0.1/8 | up | up | 10 Mbps | 65536 |  |
| eth0 |  | 172.20.20.2/24 | up | up | 10000 Mbps | 1500 |  |
| eth1 |  | 200.200.10.1/30 | up | up | 10000 Mbps | 9500 |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | eth1 | edge-mk1 | ether2 | 200.200.10.2 | MikroTik RouterOS 7.16.2 (stable) 2024-11-26 12:09:40 CHR |
| bgp |  |  |  | 200.200.10.2 |  |

## Rotas (4)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 0.0.0.0/0 | 172.20.20.1 | eth0 | connected |  |
| 172.20.20.0/24 |  | eth0 | connected |  |
| 200.200.10.0/30 |  | eth1 | connected |  |
| 203.0.113.0/24 |  |  | connected |  |

## ARP (2)

| IP | MAC | Interface |
|---|---|---|
| 172.20.20.1 | 12:72:54:fa:30:6d | eth0 |
| 200.200.10.2 | 0c:00:b2:69:a7:01 | eth1 |

## Avisos de coleta

- ssh[ssh-mikrotik]: NetmikoAuthenticationException: Authentication to device failed.
- ssh[ssh-srlinux]: NetmikoAuthenticationException: Authentication to device failed.
- ssh[ssh-linux]: NetmikoAuthenticationException: Authentication to device failed.
