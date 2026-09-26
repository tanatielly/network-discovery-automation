# NetTopo

Descoberta automática de topologia de rede **multi-vendor**. A partir de um ponto de
partida (ex.: um roteador), o NetTopo percorre a rede pelos vizinhos LLDP/CDP/MNDP e
pelas adjacências OSPF/BGP, coleta os dados de cada equipamento e gera:

- **Diagrama interativo em HTML** (arquivo único): camadas hierárquicas, busca,
  filtros, painel de detalhes e exportação para PNG;
- **draw.io (.drawio)** editável, com páginas "Física" e "L3 / Roteamento"
  (abre no diagrams.net e pode ser importado no Visio);
- **Excel** com inventário, links, interfaces, vizinhos, VLANs, endereçamento IP,
  ARP, rotas e falhas;
- **Markdown** com visão geral, diagrama Mermaid e uma página por equipamento;
- **JSON** (snapshot) para regenerar relatórios e comparar descobertas.

Inclui uma **API REST + interface web** para disparar descobertas, acompanhar o
progresso em tempo real e baixar os resultados.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

## Uso rápido

```bash
# 1. Veja a ferramenta funcionando numa rede simulada multi-vendor (sem acessar a rede)
nettopo demo -o output/demo

# 2. Crie a configuração e ajuste credenciais / escopo
nettopo init config.yaml

# 3. Descubra a rede a partir de uma semente
nettopo discover -c config.yaml --seed 10.0.0.1 -o output/

# Interface web + API (http://127.0.0.1:8000, documentação da API em /docs)
nettopo serve
```

Outros comandos:

| Comando | Descrição |
|---|---|
| `nettopo vendors` | Lista fabricantes suportados e métodos de coleta |
| `nettopo report snapshot.json -o out/` | Regenera diagramas/documentação a partir do JSON |
| `nettopo diff antes.json depois.json` | Mostra equipamentos e links adicionados/removidos/alterados |

Também funciona com `python -m nettopo ...`.

## Como funciona

```
semente ─► fingerprint ─► coleta ─► normalização ─► fila BFS (vizinhos) ─► grafo ─► saídas
            (SNMP sysObjectID,  (REST > NETCONF > SSH,   (modelo único       (dedup, links,
             autodetect SSH)     + SNMP complementar)     vendor-agnóstico)    papéis, camadas)
```

1. **Fingerprint** – identifica fabricante/SO por SNMP (`sysObjectID`/`sysDescr`) ou
   autodetecção SSH do Netmiko.
2. **Coleta** – usa o melhor método disponível para o perfil: API REST, NETCONF ou
   SSH/CLI; o SNMP complementa (serial, ifIndex, LLDP-MIB...) ou atua sozinho.
3. **Normalização** – saídas CLI são interpretadas por parsers próprios, templates
   TextFSM do *ntc-templates* ou parsers genéricos tolerantes; tudo vira o mesmo modelo
   (`Device`, `Interface`, `Neighbor`, `Link`...).
4. **Descoberta recursiva** – vizinhos com IP de gerência dentro do escopo entram na
   fila (BFS com profundidade máxima e concorrência configurável). Hostnames sem IP são
   resolvidos via DNS.
5. **Grafo** – deduplicação por serial / MAC do chassis / hostname / IPs; links
   bidirecionais consolidados; vizinhos não acessíveis viram nós "não coletados";
   links L3 inferidos por sub-redes /30-/31; adjacências OSPF/BGP; LAGs e velocidades.
6. **Classificação** – papel (roteador, switch L3, switch, firewall, AP, servidor,
   telefone, externo) e camada (borda, segurança, núcleo, distribuição, acesso,
   endpoints), usada no layout hierárquico dos diagramas.

## Fabricantes suportados

| Fabricante | Sistemas | Métodos |
|---|---|---|
| Cisco | IOS/IOS-XE, NX-OS, IOS-XR, ASA, SMB | SNMP, SSH, NETCONF, RESTCONF (IOS-XE), NX-API |
| Juniper | Junos | SNMP, SSH, NETCONF |
| Arista | EOS | SNMP, SSH, eAPI, NETCONF |
| HPE / Aruba / H3C | ArubaOS-CX, ProCurve/ArubaOS-Switch, Comware | SNMP, SSH |
| Huawei | VRP | SNMP, SSH, NETCONF |
| MikroTik | RouterOS | SNMP, SSH, REST (v7) |
| Fortinet | FortiOS | SNMP, SSH, REST |
| Palo Alto / Check Point / SonicWall | PAN-OS, Gaia, SonicOS | SNMP, SSH |
| Dell | OS10, OS6/PowerConnect | SNMP, SSH |
| Extreme | EXOS, VOSS | SNMP, SSH |
| Nokia | SR OS, SR Linux | SNMP, SSH, NETCONF |
| Ruckus/Brocade, Allied Telesis, TP-Link, ZTE, Ubiquiti | diversos | SNMP, SSH |
| Datacom, Furukawa, Intelbras | DmOS e outros | SNMP (+ SSH no DmOS) |
| Linux / VyOS | lldpd, iproute2 | SNMP, SSH |

**Qualquer equipamento com SNMP e LLDP-MIB** é descoberto mesmo sem perfil específico.
Os perfis ficam em [`src/nettopo/vendors/profiles/`](src/nettopo/vendors/profiles/)
(YAML): para adicionar um fabricante basta declarar `sysObjectID`, regex de `sysDescr`,
driver Netmiko e comandos — sem alterar código.

## Requisitos nos equipamentos

- **LLDP** (ou CDP/MNDP/EDP/FDP) habilitado para que os vizinhos sejam encontrados;
- Acesso **somente leitura** é suficiente: SNMP read-only e/ou usuário SSH com
  privilégio de *show*;
- Para APIs: eAPI/NX-API/RESTCONF/REST habilitados conforme o fabricante.

O NetTopo **não altera configuração** — apenas executa comandos de leitura.

## API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/discoveries` | Inicia descoberta (corpo = mesma estrutura do YAML) |
| `POST` | `/api/demo` | Inicia descoberta na rede simulada |
| `GET` | `/api/discoveries` | Histórico |
| `GET` | `/api/discoveries/{id}` | Status e estatísticas |
| `GET` | `/api/discoveries/{id}/view` | Dados do diagrama/documentação (JSON) |
| `GET` | `/api/discoveries/{id}/export/{html\|drawio\|xlsx\|md\|json}` | Download |
| `WS` | `/api/discoveries/{id}/events` | Progresso em tempo real |
| `GET` | `/api/vendors` | Perfis suportados |

As credenciais enviadas à API são usadas apenas em memória e **não são gravadas** no
banco (SQLite em `./nettopo_data`, configurável por `NETTOPO_DATA`). Defina
`NETTOPO_API_TOKEN` para exigir o cabeçalho `Authorization: Bearer <token>`.

## Desenvolvimento

```bash
pytest            # testes (parsers, SNMP real via snmpsim, REST, NETCONF, motor, grafo, saídas, API)
ruff check src tests
```

Para testar contra equipamentos reais, laboratórios com **Containerlab** (Arista cEOS,
Nokia SR Linux, FRR) ou **EVE-NG/GNS3** (Cisco, Juniper, MikroTik CHR) funcionam bem.
