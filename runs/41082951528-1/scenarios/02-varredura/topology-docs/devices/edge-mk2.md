# edge-mk2

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.12 |
| Papel | Roteador |
| Camada | Borda / Roteamento |
| Fabricante | MikroTik |
| Sistema | RouterOS |
| Versão | 7.16.2 (stable) |
| Modelo | CHR QEMU Standard PC (i440FX + PIIX, 1996) |
| Serial | 800Dyv/OSDM |
| Uptime | 2m23s |
| Localização | Borda - Rack B |
| Contato | noc@nettopo.lab |
| Coletado via | rest, snmp |
| Descrição | RouterOS CHR |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| ether4 | [core-srl2](core-srl2.md) | ethernet-1/1 | physical | lldp | 25000 Mbps | 10.10.2.0/30 |
| ether3 | [edge-mk1](edge-mk1.md) | ether3 | physical | lldp, ospf |  | 10.255.0.0/30 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| ether1 |  | 172.31.255.30/30 | up | up |  | 1500 |  |
| ether2 |  |  | up | up |  | 1500 |  |
| ether3 | Interlink edge-mk1 | 10.255.0.2/30 | up | up |  | 1500 |  |
| ether4 | Core SRL2 | 10.10.2.1/30 | up | up |  | 1500 |  |
| lo |  |  | up | up |  | 65536 |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | ether3 | edge-mk1 | ether3 | 10.255.0.1 | MikroTik CHR |
| lldp | ether4 | core-srl2 | to edge-mk2 ether4 | 172.20.20.22 |  |
| ospf |  |  |  | 10.255.0.1 |  |

## Rotas (4)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 10.10.0.0/16 | 10.10.2.2 |  | static | main |
| 10.10.2.0/30 |  | ether4 | connected | main |
| 10.255.0.0/30 |  | ether3 | connected | main |
| 172.31.255.28/30 |  | ether1 | connected | main |

## ARP (2)

| IP | MAC | Interface |
|---|---|---|
| 172.31.255.29 | fe:71:51:67:e1:6e | ether1 |
| 10.255.0.1 | 0c:00:31:76:a8:02 | ether3 |
