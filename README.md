# Mapa de Rede

Descoberta automática de topologia de rede **multi-vendor**. A partir de um ponto de
partida (ex.: um roteador), o Mapa de Rede percorre a rede pelos vizinhos LLDP/CDP/MNDP e
pelas adjacências OSPF/BGP, coleta os dados de cada equipamento e gera:

- **Diagrama interativo em HTML** (arquivo único): camadas hierárquicas, busca,
  filtros, painel de detalhes e exportação para PNG;
- **draw.io (.drawio)** editável, com páginas "Física" e "L3 / Roteamento"
  (abre no diagrams.net e pode ser importado no Visio);
- **Excel** com inventário, links, interfaces, vizinhos, VLANs, endereçamento IP,
  ARP, rotas e falhas;
- **Markdown** com visão geral, diagrama Mermaid e uma página por equipamento;
- **JSON** (snapshot) para regenerar relatórios e comparar descobertas.

Funciona pela linha de comando (`nettopo`) e por uma **API REST + interface web**, que dispara
descobertas, acompanha o progresso em tempo real e baixa os resultados.

Desde a 0.2 a ferramenta **lembra da rede**: cada descoberta grava um inventário local e, na
próxima execução, confirma rapidamente que cada equipamento continua ativo e com os mesmos
vizinhos, recoletando só o que mudou. Tem **rate limit por equipamento** (para não sobrecarregar
equipamentos antigos) e um **cofre local** para as credenciais.

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
| `nettopo verificar -c config.yaml` | Só confirma o inventário conhecido (ativo, mudou ou inacessível), sem seguir vizinhos novos |
| `nettopo inventario` | Lista o inventário com status, última confirmação e eventos recentes |
| `nettopo cred add\|list\|remove\|import` | Gerencia o cofre de credenciais |
| `nettopo vendors` | Lista fabricantes suportados e métodos de coleta |
| `nettopo report snapshot.json -o out/` | Regenera diagramas/documentação a partir do JSON |
| `nettopo diff antes.json depois.json` | Mostra equipamentos e links adicionados/removidos/alterados |

Opções úteis do `discover`: `--carga conservador|equilibrado|rapido`, `--completo` (recoleta
tudo, ignorando dados já confirmados), `--sem-memoria` (não lê nem grava o inventário) e
`--dados DIR` (onde ficam inventário e cofre; padrão `NETTOPO_DATA` ou `./nettopo_data`).

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
4. **Descoberta recursiva** – vizinhos dentro do escopo entram na fila (BFS com profundidade
   máxima e concorrência configurável). Cada vizinho tem uma lista de **IPs candidatos**,
   tentados em ordem: inventário/memória → IP anunciado → DNS do hostname → IP pelo MAC do
   chassis nas tabelas ARP já coletadas. IPs sem resposta ficam num cache negativo (6 h).
5. **Grafo** – deduplicação por serial / MAC do chassis / hostname / IPs (séries genéricas de
   VMs são ignoradas); cada ponta do link usa o nome de porta do próprio equipamento; LLDP
   recebido em interface de gerência é ignorado; vizinhos não acessíveis viram nós "não
   coletados" **com o motivo**; links L3 inferidos por sub-redes /30-/31; adjacências OSPF/BGP;
   LAGs e velocidades. A ordem do grafo é determinística.
6. **Classificação** – papel (roteador, switch L3, switch, firewall, AP, servidor,
   telefone, externo) e camada (borda, segurança, núcleo, distribuição, acesso,
   endpoints), usada no layout hierárquico dos diagramas.

## Memória persistente e revalidação

Toda descoberta grava o inventário no diretório de dados (equipamentos, links, acesso que
funcionou e histórico). Na execução seguinte, antes de seguir vizinhos, o Mapa de Rede faz uma
**checagem leve** de cada equipamento conhecido usando o acesso salvo (identidade + lista de
vizinhos LLDP/CDP):

| Resultado da checagem | O que acontece |
|---|---|
| mesma identidade e mesmos vizinhos | dados reaproveitados, marcado "confirmado agora" |
| vizinhança mudou ou dados com mais de 24 h | coleta completa |
| não responde | nó "inacessível desde ..." (evento no histórico); volta a "ativo" quando responder |

Equipamentos novos continuam sendo descobertos normalmente. `nettopo verificar` faz só a
checagem (útil em agendamentos); o relatório HTML, a UI e o Excel mostram status e "verificado em".

## Rate limit (carga nos equipamentos)

```yaml
carga:
  perfil: equilibrado        # conservador | equilibrado | rapido
  overrides:                 # mais cuidado com equipamentos antigos
    - {fabricante: hp_procurve, perfil: conservador}
    - {cidr: 10.20.0.0/16, intervalo_min_ms: 1000}
```

| Perfil | Intervalo entre requisições | Sessões por equipamento | SNMP (max-repetitions / walks) | Atraso SSH | Falhas de login | Equipamentos em paralelo |
|---|---|---|---|---|---|---|
| conservador | 500 ms | 1 | 10 / 1 | 1,0 s | 2 | 4 |
| equilibrado (padrão) | 100 ms | 1 | 25 / 2 | 0,2 s | 3 | 16 |
| rapido | 0 | 2 | 50 / 4 | 0 | 5 | 64 |

O limite vale para SNMP (cada PDU), REST, NETCONF, comandos SSH, teste de portas e tentativas de
login (para não bloquear a conta no AAA). A carga aplicada fica registrada em cada equipamento.

## Cofre de credenciais

```bash
nettopo cred add ssh-noc --tipo ssh -u noc        # a senha é pedida sem eco
nettopo cred add snmp-ro --tipo snmp --versao 2c
nettopo cred import config.yaml                   # move as credenciais do YAML para o cofre
```

No config, use `credentials: [{ref: ssh-noc}]` ou `usar_cofre: true` (todas as do cofre). Os segredos
ficam no cofre do sistema (Windows Credential Manager, Keychain, Secret Service) ou, sem ele, num
arquivo cifrado (`vault.enc`, Fernet + scrypt) com a senha em `NETTOPO_VAULT_PASSWORD`. Nem o
inventário nem os logs guardam segredos.

## Varredura opcional

`varredura: [10.0.0.0/24]` testa cada IP da rede de gerência (portas 22/80/443/830 e SNMP, com o
rate limit) para achar equipamentos que nenhum vizinho anuncia com IP alcançável. Desligada por padrão.

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

O Mapa de Rede **não altera configuração** — apenas executa comandos de leitura.

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
| `POST` | `/api/verify` | Só revalida o inventário conhecido |
| `GET` | `/api/inventory` · `/api/inventory/events` | Inventário com status e histórico |
| `GET` `POST` `DELETE` | `/api/credentials` | Cofre (nunca devolve segredos) |
| `GET` | `/api/vendors` | Perfis suportados |

`POST /api/discoveries` aceita `?completo=true` e `?memoria=false`. Credenciais digitadas na UI
são usadas apenas em memória; para reutilizá-las, salve no cofre. Dados em `./nettopo_data`
(`NETTOPO_DATA`). Defina `NETTOPO_API_TOKEN` para exigir `Authorization: Bearer <token>` — o
token é **obrigatório** para servir fora de `127.0.0.1`.

## Laboratório e avaliação

A ferramenta é testada contra sistemas reais (MikroTik RouterOS 7, Nokia SR Linux, Linux/FRR) num
laboratório Containerlab que roda no GitHub Actions, sem hardware local. Detalhes em
[`lab/README.md`](lab/README.md).

Relatórios da primeira avaliação (26/09/2026):

- [Gestão técnica](docs/relatorios/gestao-tecnica.md) · [PDF](docs/relatorios/gestao-tecnica.pdf)
- [Técnico](docs/relatorios/tecnico.md) · [PDF](docs/relatorios/tecnico.pdf)

## Desenvolvimento

```bash
pytest            # testes (parsers, SNMP real via snmpsim, REST, NETCONF, motor, grafo, saídas, API)
ruff check src tests
```

Para testar contra equipamentos reais, laboratórios com **Containerlab** (Arista cEOS,
Nokia SR Linux, FRR) ou **EVE-NG/GNS3** (Cisco, Juniper, MikroTik CHR) funcionam bem.
