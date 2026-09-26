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
| Uptime | 2m38s |
| Localização | Borda - Rack B |
| Contato | noc@nettopo.lab |
| Coletado via | rest, snmp |
| Descrição | RouterOS CHR |

## Conexões

| Interface local | Vizinho | Interface remota | Tipo | Protocolos | Velocidade | Sub-rede |
|---|---|---|---|---|---|---|
| ether3 | [edge-mk1](edge-mk1.md) | ether3 | physical | lldp |  | 172.31.255.28/30 |
| ether4 | [core-srl2](core-srl2.md) | to edge-mk2 ether4 | physical | lldp |  | 10.10.2.0/30 |
| ether4 | [core-srl2](core-srl2.md) | ethernet-1/1 | physical | lldp | 25000 Mbps | 10.10.2.0/30 |

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
| lldp | ether4 | core-srl2 | to edge-mk2 ether4 | 172.20.20.22 | SRLinux-v25.10.5-111-g6fbddec84ef core-srl2 6.17.0-1022-azur |

## Rotas (8)

| Prefixo | Next-hop | Interface | Protocolo | VRF |
|---|---|---|---|---|
| 10.10.0.0/16 | 10.10.2.2 |  | static | main |
| 10.10.2.0/30 |  | ether4 | connected | main |
| 10.255.0.0/30 |  | ether3 | connected | main |
| 172.31.255.28/30 |  | ether1 | connected | main |
| 10.10.0.0/16 | 10.10.2.2 |  | static |  |
| 10.10.2.0/30 |  | ether4 | connected |  |
| 10.255.0.0/30 |  | ether3 | connected |  |
| 172.31.255.28/30 |  | ether1 | connected |  |

## ARP (2)

| IP | MAC | Interface |
|---|---|---|
| 10.255.0.1 | 0c:00:58:47:88:02 | ether3 |
| 172.31.255.29 | fe:aa:ea:1f:86:45 | ether1 |
