# edge-mk1

[← Visão geral](../README.md)

| Campo | Valor |
|---|---|
| IP de gerência | 172.20.20.11 |
| Papel | Roteador |
| Camada | Borda / Roteamento |
| Fabricante | MikroTik |
| Sistema | RouterOS |
| Versão | 7.16.2 (stable) |
| Modelo | CHR QEMU Standard PC (i440FX + PIIX, 1996) |
| Serial | H1GQLYHA4RK |
| Uptime | 2m23s |
| Localização | Borda - Rack A |
| Contato | noc@nettopo.lab |
| Coletado via | rest, snmp |
| Descrição | RouterOS CHR |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| ether4 | [core-srl1](core-srl1.md) | ethernet-1/1 | physical | lldp | 25000 Mbps | 10.10.1.0/30 |
| ether2 | isp-pe | eth1 | physical | bgp, lldp |  | 200.200.10.0/30 |
| ether3 | [edge-mk2](edge-mk2.md) | ether3 | physical | lldp, ospf |  | 10.255.0.0/30 |

## Interfaces

| Interface | Descrição | IPv4 | Admin | Oper | Velocidade | MTU | LAG |
|---|---|---|---|---|---|---|---|
| ether1 |  | 172.31.255.30/30 | up | up |  | 1500 |  |
| ether2 | Uplink operadora | 200.200.10.2/30 | up | up |  | 1500 |  |
| ether3 | Interlink edge-mk2 | 10.255.0.1/30 | up | up |  | 1500 |  |
| ether4 | Core SRL1 | 10.10.1.1/30 | up | up |  | 1500 |  |
| lo |  |  | up | up |  | 65536 |  |

## Vizinhos anunciados

| Protocolo | Interface local | Vizinho | Interface remota | IP | Plataforma |
|---|---|---|---|---|---|
| lldp | ether2 | isp-pe | eth1 | 172.20.20.2 |  |
| lldp | ether3 | edge-mk2 | ether3 | 10.255.0.2 | MikroTik CHR |
| lldp | ether4 | core-srl1 | to edge-mk1 ether4 | 172.20.20.21 |  |
| ospf |  |  |  | 10.255.0.2 |  |
| bgp |  |  |  | 200.200.10.1 |  |

## Rotas (6)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 10.10.0.0/16 | 10.10.1.2 |  | static | main |
| 10.10.1.0/30 |  | ether4 | connected | main |
| 10.255.0.0/30 |  | ether3 | connected | main |
| 172.31.255.28/30 |  | ether1 | connected | main |
| 200.200.10.0/30 |  | ether2 | connected | main |
| 203.0.113.0/24 | 200.200.10.1 |  | bgp | main |

## ARP (3)

| IP | MAC | Interface |
|---|---|---|
| 172.31.255.29 | fe:eb:a3:dc:88:63 | ether1 |
| 10.255.0.2 | 0c:00:46:a4:db:02 | ether3 |
| 200.200.10.1 | aa:c1:ab:11:5b:bd | ether2 |
