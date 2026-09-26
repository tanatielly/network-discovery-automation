---
title: NetTopo contra sistemas reais
kicker: Relatório técnico
lede: Metodologia, resultados por cenário, análise por fabricante e protocolo, defeitos com localização no código, desempenho, qualidade, segurança e plano de melhorias da primeira simulação do NetTopo em laboratório Containerlab.
other_label: Relatório de gestão técnica
toc: true
tag:
  Documento: NT-AVL-2026-02
  Versão avaliada: NetTopo 0.1.0 · f2823ea
  Execução: run 36256925269
  Data: 26/09/2026
  Runner: ubuntu-24.04 · 4 vCPU · 16 GB · KVM
  Público: Engenharia de redes e desenvolvimento
---

## Objetivo e escopo

Validar a ferramenta contra sistemas operacionais de rede reais, e não mais contra o coletor simulado
usado nos testes unitários. A avaliação cobre descoberta, identificação de fabricante, leitura dos dados
(parsing), montagem do grafo, saídas, API, interface web e linha de comando.

A versão 0.1.0 foi avaliada **como está**. Houve uma única correção durante a simulação, porque impedia a
execução (defeito D0, abaixo). Todas as demais falhas estão registradas como recomendação, sem correção.

## Ambiente

| Item | Versão / configuração |
|---|---|
| Execução | GitHub Actions, `ubuntu-24.04`, 4 vCPU, 15 GiB, `/dev/kvm` habilitado |
| Orquestração | Containerlab 0.79.0 |
| MikroTik | RouterOS 7.16.2 CHR em VM QEMU/KVM, imagem gerada com vrnetlab v0.21.0 |
| Nokia | SR Linux 25.10.5 (`ghcr.io/nokia/srlinux`), NETCONF + OpenConfig habilitados |
| Linux | Debian 12, FRR, lldpd com AgentX (LLDP-MIB via net-snmp), OpenSSH |
| NetTopo | 0.1.0, Python 3.12, commit `f2823ea` |

```
                 isp-pe (Linux/FRR, BGP AS64500, sem credenciais do NetTopo)
                    | eth1 — ether2
   edge-mk1 (RouterOS 7.16) —— ether3/ether3 (OSPF) —— edge-mk2 (RouterOS 7.16)
        | ether4                                            | ether4
   core-srl1 (SR Linux 25.10) —— e1-2/e1-2 —— core-srl2 (SR Linux 25.10)
        | e1-3                                 | e1-3          | e1-4
        +——————————— dist-frr1 (Linux+FRR) ————+              srv2 (Linux)
                         | eth3
                       srv1 (Linux)
```

Gerência em `172.20.20.0/24`, alcançável pelo servidor de descoberta. Os endereços dos links de dados
(`10.x`, `192.168.x`, `200.200.10.0/30`) **não** são alcançáveis por ele, como costuma acontecer com
interfaces de trânsito numa rede real.

Uma rodada completa levou 16 min 19 s: build do CHR 2 min 55 s, deploy 1 min 37 s, boot e
configuração 52 s, cenários 9 min 08 s e qualidade de código 48 s.

## Metodologia

O arquivo `lab/ground_truth.yaml` descreve o que deveria ser encontrado: 7 equipamentos coletáveis, 1
roteador de operadora que deve aparecer como "não coletado", 9 links físicos com as interfaces nativas de
cada lado e 2 adjacências de roteamento. O script `lab/scripts/score.py` compara cada descoberta com
esse gabarito:

- **Equipamentos coletados:** equipamentos coletáveis presentes e coletados (não apenas vistos por vizinhos).
- **Links encontrados:** pares de equipamentos do gabarito ligados por ao menos um link físico.
- **Precisão de links:** links corretos ÷ links desenhados. Links a mais entre o mesmo par (duplicados ou da
  rede de gerência) e links para pares inexistentes contam como erro.
- **Portas corretas:** links encontrados com o nome de interface certo nas duas pontas.
- **Fabricante e papel:** acerto sobre os equipamentos coletados.
- **Coletas repetidas:** eventos de coleta concluída atribuídos ao mesmo equipamento final.

Antes dos cenários, `lab/scripts/dump_raw.py` executa em cada equipamento os comandos do perfil de
fabricante do NetTopo e mede quantos registros cada parser extrai das saídas reais.

## Resultados por cenário

<!-- viz:scenarios -->

| Cenário | Coletados | Links | Precisão | Portas | Tempo (s) |
|---|---|---|---|---|---|
| 01 Semente única, todos os métodos | 4/7 | 7/9 | 70% | 86% | 24,5 |
| 02 Semente única + DNS | 4/7 | 6/9 | 60% | 67% | 23,9 |
| 03 Inventário de IPs de gerência | 5/7 | 6/9 | 55% | 50% | 24,2 |
| 04 Somente SNMP v2c | 1/7 | 3/9 | 100% | 67% | 0,8 |
| 05 Somente SNMPv3 | 3/7 | 4/9 | 100% | 100% | 10,9 |
| 06 Somente SSH | 0/7 | 0/9 | — | — | 118,1 |
| 07 Somente APIs (REST/NETCONF) | 6/7 | 9/9 | 82% | 89% | 13,6 |
| 08 Credenciais erradas primeiro | 4/7 | 7/9 | 70% | 86% | 44,0 |
| 09 Profundidade 1 + exclusão | 2/7 | 5/9 | 71% | 80% | 23,7 |
| 10 Inventário sequencial | 5/7 | 7/9 | 64% | 71% | 41,7 |
| 11 Após falha injetada | 5/7 | 6/9 | 67% | 67% | 24,3 |

<!-- /viz -->

Leitura dos cenários:

- **01 e 02.** `edge-mk2` só é anunciado com o IP da interface de trânsito `10.255.0.2` (MNDP/LLDP do
  RouterOS). A ferramenta tenta esse IP, falha e não tenta o nome. Com DNS configurado o resultado é o
  mesmo, porque o nome só é resolvido quando o vizinho não anuncia IP nenhum (D3).
- **03.** Com todos os IPs de gerência como sementes, todos os equipamentos respondem, mas `dist-frr1`,
  `srv1` e `srv2` viram um único registro (D1). Os links desses hosts passam a apontar para o registro
  fundido, o que derruba a precisão para 55% e o acerto de portas para 50%.
- **04.** O RouterOS não preenche o endereço de gerência na LLDP-MIB. Sem IP, a descoberta para no
  primeiro salto (D9), mas é muito rápida: 0,8 s.
- **05.** SNMPv3 authPriv (SHA/AES) funcionou nos três hosts Linux, os únicos com usuário v3 no
  laboratório. Como no 07, os hosts Linux não se fundem: a série falsa só aparece na coleta por SSH (D1).
- **06.** O autodetect do Netmiko não reconhece o RouterOS. Sem perfil, o coletor SSH desiste da semente
  e nada é descoberto após 118 s de tentativas (D4).
- **07.** Melhor resultado: REST no RouterOS, NETCONF/OpenConfig no SR Linux e SNMP nos hosts Linux, com
  SNMP apenas para identificar o fabricante. Sem a coleta SSH dos hosts Linux, não há fusão.
- **08.** Três credenciais erradas antes das corretas custaram 19,5 s e não mudaram o resultado. Depois do
  primeiro acerto, a credencial que funcionou passa para o início da lista.
- **09.** Profundidade 1 e exclusão da rede dos servidores funcionaram como configurado.
- **10.** Sequencial (1 coleta por vez) levou 41,7 s contra 24,2 s com 16 em paralelo (1,7×).
- **11.** `srv2` desligado aparece em falhas e o link `core-srl2:e1-3 ↔ dist-frr1:eth2` derrubado some
  como link físico, mas volta como link L3 inferido, porque a sub-rede /30 continua configurada.

<!-- viz:shot relatorio-diagrama | Relatório HTML gerado no cenário 03. O registro "srv2" representa três hosts Linux fundidos; há duas linhas entre edge-mk1 e core-srl1 e entre edge-mk2 e core-srl2, e um link mgmt0 entre os switches. -->

## Matriz fabricante × método

<!-- viz:matrix -->

| Sistema | SNMP v2c | SNMPv3 | SSH/CLI | APIs |
|---|---|---|---|---|
| MikroTik CHR 7.16 | 1 de 2 coletados | não se aplica | falha | 1 de 2 coletados |
| Nokia SR Linux 25.10 | falha | não se aplica | falha | funciona |
| Linux / FRR | falha | funciona | falha | não se aplica |

<!-- /viz -->

A matriz considera só os cenários de método isolado (04 a 07), a partir da mesma semente `edge-mk1`,
exceto o 05, que parte do inventário. "Falha" em SNMP v2c para SR Linux e Linux não significa que o SNMP
desses sistemas não funcione. Eles nem chegaram a ser consultados, porque a descoberta parou no
primeiro salto (D9). Nos cenários completos, o SNMP complementou os dados dos três sistemas.

## Parsing com saídas reais

<!-- viz:parse -->

| Equipamento | Identificação | Hostname | Interfaces | IPs | LLDP | MNDP/LLDP | ARP | Rotas |
|---|---|---|---|---|---|---|---|---|
| edge-mk1 | ok | ok | ok (5) | ok (4) | — | ok (3) | ok (3) | 1 de 6 |
| core-srl1 | ok | — | — | falha | falha | — | ok (1) | — |
| dist-frr1 | ok | ok | ok (4) | ok (4) | falha | — | ok (1) | ok (5) |

<!-- /viz -->

- **RouterOS 7:** os parsers próprios leem quase tudo. Rotas: 1 de 6, porque o `print terse` do RouterOS 7
  não numera rotas dinâmicas e o agrupador de registros só inicia um registro novo numa linha com índice
  (D7).
- **SR Linux:** as saídas de `show system lldp neighbor` e `show interface brief` são tabelas com bordas
  ASCII; nenhum template TextFSM existe para a plataforma e o parser genérico espera "chave: valor" (D8).
  Nos cenários completos isso não aparece porque o SR Linux foi coletado por NETCONF.
- **Linux:** `lldpctl` não está no `PATH` de usuários sem privilégio no Debian (fica em `/usr/sbin`), e a
  saída é `command not found` (D11). O LLDP dos hosts Linux veio pela LLDP-MIB via SNMP.

## Defeitos encontrados

Severidade **alta**: distorce o inventário ou o desenho, ou impede um modo de uso. **Média**: dado
incompleto ou errado com contorno. **Baixa**: cosmético ou de mensagem.

<div class="defects" markdown="1">

| ID | Sev. | Defeito | Onde | Evidência |
|---|---|---|---|---|
| D0 | <span class="sev alta">alta</span> | `.gitignore` com `output/` excluía `src/nettopo/output`; quem clonasse o repositório teria a ferramenta sem o pacote de saídas. **Corrigido** (`/output/`). | `.gitignore` | Run 36255328422: `ModuleNotFoundError: nettopo.output` |
| D1 | <span class="sev alta">alta</span> | Hosts Linux fundidos: o parser usa o nome do produto DMI ("Virtual Machine") como número de série quando a série não pode ser lida, e a deduplicação confia na série. | `src/nettopo/vendors/parsers/linux.py:103`, `src/nettopo/discovery/identity.py:73` | 3 hosts em 1 registro em 01, 02, 03, 08 e 10; 2 em 1 no 11 |
| D2 | <span class="sev alta">alta</span> | Links duplicados: o RouterOS expõe em `interface-name` a descrição da porta do vizinho (SR Linux: "to edge-mk1 ether4"), e a fusão de links não reconhece que é a mesma porta. | `src/nettopo/vendors/parsers/mikrotik.py:65`, `src/nettopo/collectors/rest.py` (driver MikroTik), `src/nettopo/topology/builder.py` (`merge_links`) | Link a mais RouterOS ↔ SR Linux em 8 dos 11 cenários (todos em que os dois foram coletados) |
| D3 | <span class="sev alta">alta</span> | Sem alternativa quando o IP anunciado não responde; o nome só é resolvido quando nenhum IP é anunciado. | `src/nettopo/discovery/scope.py:65-67` | `edge-mk2` não coletado em 01 e 02 (DNS sem efeito) |
| D4 | <span class="sev alta">alta</span> | Identificação de fabricante depende de SNMP ou do autodetect do Netmiko, que não reconhece o RouterOS; sem perfil, o coletor SSH desiste. | `src/nettopo/collectors/orchestrator.py:60-62`, `src/nettopo/collectors/ssh.py:106` | Cenário 06: 0/7 em 118 s |
| D5 | <span class="sev media">média</span> | LLDP recebido em interfaces de gerência (mgmt0) vira link físico. | `src/nettopo/topology/builder.py:170` | Link `core-srl1:mgmt0 ↔ core-srl2:mgmt0` em 8 dos 11 cenários (todos em que os SR Linux foram coletados) |
| D6 | <span class="sev media">média</span> | Inferência L3 aceita dois equipamentos com o **mesmo** IP numa /30 (gerência interna NAT do CHR, `172.31.255.30/30`) e grava a sub-rede errada no link. | `src/nettopo/topology/enrich.py:29-50` | Sub-rede `172.31.255.28/30` no link `edge-mk1 ↔ edge-mk2` nos cenários 03, 10 e 11 |
| D7 | <span class="sev media">média</span> | Rotas do RouterOS 7 sem índice são descartadas. | `src/nettopo/vendors/parsers/mikrotik.py:12,24` | 1 de 6 rotas |
| D8 | <span class="sev media">média</span> | SR Linux por CLI sem parser para tabelas. | `src/nettopo/vendors/profiles/datacenter_campus.yaml:144` | LLDP e interfaces: 0 registros |
| D9 | <span class="sev media">média</span> | Vizinho sem IP de gerência (LLDP-MIB do RouterOS) não é seguido; o MAC do chassis poderia ser resolvido pela tabela ARP já coletada. | `src/nettopo/discovery/scope.py` | Cenário 04: 1/7 |
| D10 | <span class="sev media">média</span> | Adjacência OSPF nunca detectada: o driver REST do RouterOS não consulta vizinhos OSPF/BGP e o RouterOS não os expõe por SNMP no laboratório. | `src/nettopo/collectors/rest.py` (`MikrotikRestDriver.paths`) | 0 de 11 cenários |
| D11 | <span class="sev baixa">baixa</span> | Comando `lldpctl` fora do `PATH` de usuários comuns. | `src/nettopo/vendors/profiles/brasil_linux.yaml:70` | `command not found` |
| D12 | <span class="sev baixa">baixa</span> | O vizinho BGP da operadora vira um nó separado ("AS64500 200.200.10.1") em vez de se juntar ao nó já visto por LLDP. | `src/nettopo/topology/enrich.py` (`routing_adjacencies`) | Nó inesperado em 8 dos 11 cenários |
| D13 | <span class="sev baixa">baixa</span> | Inventário incompleto: série e modelo ausentes para SR Linux e série ausente para o CHR. | coletores NETCONF/REST | Campos vazios no inventário |
| D14 | <span class="sev baixa">baixa</span> | Mensagem enganosa: falha de autenticação SSH é reportada como "perfil sem driver Netmiko". | `src/nettopo/collectors/orchestrator.py` | `isp-pe` em 7 dos 11 cenários |

</div>

Consequência de D1 que merece destaque: o equipamento que "sobrevive" à fusão depende da ordem de
chegada das coletas (`dist-frr1` em 01, `srv2` em 02 e 03). O mesmo laboratório produz inventários
diferentes a cada execução, e a comparação entre descobertas (`nettopo diff`) acusa equipamentos
"adicionados" e "removidos" que não mudaram.

## Desempenho

| Medida | Resultado |
|---|---|
| Descoberta completa, 8 equipamentos, 16 coletas em paralelo | 24,2 a 24,5 s |
| Mesma descoberta, 1 coleta por vez | 41,7 s (1,7×) |
| Somente SNMP v2c (1 equipamento alcançado) | 0,8 s |
| Somente APIs (6 equipamentos) | 13,6 s |
| Custo de 3 credenciais erradas antes das certas | +19,5 s |
| Custo de um alvo inacessível | porta a porta (22, 830, 443, 80) + tentativas SNMP por credencial |
| Somente SSH (autodetect falhando) | 118,1 s |

O tempo é dominado por alvos inacessíveis e autenticações que falham. Numa rede com centenas de
equipamentos, D3 (IPs não roteáveis) e D4 (autodetect) multiplicam esse custo. Sugestões: timeouts
separados para varredura de portas e SNMP, cache negativo por IP e limite de credenciais por tentativa.

## API, interface web e linha de comando

| Verificação | Resultado |
|---|---|
| `POST /api/discoveries` + WebSocket até o fim | concluída em 24,6 s; eventos recebidos: 1 início, 9 coletas iniciadas, 7 concluídas, 2 falhas, 1 fim |
| Exportações pela API | HTML 121 KB, draw.io 39 KB, Excel 30 KB, Markdown (zip) 7 KB, JSON 100 KB; todas HTTP 200 |
| Senhas no banco SQLite | nenhuma encontrada (busca pelas três senhas do laboratório) |
| CLI `vendors`, `discover`, `report`, `diff` | todos com código de saída 0 |
| Capturas da interface | 5 telas geradas pelo Chrome headless |

<!-- viz:shot relatorio-equipamento | Painel de detalhes do core-srl1 no relatório HTML: identificação, conexões e interfaces coletadas por NETCONF. Modelo e série vazios (D13). -->

## Qualidade de código

| Métrica | Resultado |
|---|---|
| Testes (`pytest`) | 46 aprovados |
| Cobertura | 71% de 3.875 instruções |
| Lint (`ruff`) | sem ocorrências |
| Tipagem (`mypy`) | 22 erros em 10 arquivos, principalmente valores opcionais (`None`) usados onde o tipo exige valor |
| `bandit` | 1 alto, 9 médios, 5 baixos |

Triagem do `bandit`:

- **Alto, B324 (MD5):** `hashlib.md5` em `collectors/simulated.py:27` gera MACs fictícios do laboratório
  simulado. Não é uso criptográfico; basta `usedforsecurity=False`.
- **Médio, B704 (`Markup`):** `output/html.py` marca como seguros o CSS/JS do próprio pacote. Os dados da
  rede entram como JSON com `</` escapado. Risco baixo, mas os nomes e descrições vindos dos
  equipamentos também chegam ao HTML da interface; vale um teste específico de XSS com hostname malicioso.
- **Médio, B104:** comparações com `0.0.0.0` em rotas, não abertura de socket. Falso positivo.
- **Baixo, B110/B406:** `except: pass` em pontos de limpeza e parser XML com `recover=True` para saídas de
  equipamento.

Os testes unitários passaram o tempo todo, mas nenhum deles pegou D0, D1, D2 ou D7. Todos dependem de
dados reais: o diretório local mascarava o `.gitignore`, e os fixtures eram escritos à mão. A
recomendação é versionar as saídas brutas deste laboratório (`raw/`) como fixtures de regressão.

## Segurança

- **API sem autenticação por padrão:** o token (`NETTOPO_API_TOKEN`) é opcional. Como a API recebe
  credenciais de rede, deveria ser obrigatório fora de `127.0.0.1`.
- **TLS e chaves de host:** `verify_ssl=False` por padrão (`config.py:44`), NETCONF com
  `hostkey_verify=False` (`netconf.py:242`) e SSH sem verificação de chave. Aceitável em laboratório, não
  em produção: permite interceptação das credenciais.
- **Segredos:** as credenciais ficam só em memória e não são gravadas (verificado no cenário 12). Falta
  integração com cofre (Vault, keyring) para uso agendado.
- **Dependência externa no relatório:** o HTML carrega o Cytoscape.js de CDN; em redes isoladas o
  diagrama não abre (as abas de documentação continuam funcionando).

## Limitações desta avaliação

- Três famílias de sistema: não há Cisco, Juniper, Huawei, Arista ou Fortinet reais neste laboratório.
- Escala pequena (8 equipamentos, 9 links); não mede comportamento com centenas de nós.
- SR Linux em contêiner e CHR em VM, não hardware físico; o NAT de gerência do CHR é específico do
  vrnetlab e causa D6.
- Uma execução por cenário; como D1 mostrou, o resultado não é determinístico e merece repetição.
- Na primeira rodada, o `isp-pe` compartilhava o usuário SNMPv3 com os demais hosts e foi coletado
  indevidamente. Foi um erro de configuração do laboratório, corrigido antes da rodada final analisada aqui.

## Plano de melhorias

| Prioridade | Ação | Resolve | Esforço (estimativa) |
|---|---|---|---|
| 1 | Série só de fontes confiáveis; lista de valores genéricos ("Virtual Machine", "To Be Filled", "Default string"); exigir duas chaves fortes para fundir | D1 | 1 dia |
| 1 | Normalizar porta por `port-id` e não por descrição; fundir links pelo lado que coletou a própria interface; ignorar LLDP de `mgmt*`/OOB | D2, D5 | 2 dias |
| 1 | Quando o IP anunciado falhar: resolver o hostname, procurar o MAC do chassis nas tabelas ARP coletadas e cruzar com o inventário | D3, D9 | 3 dias |
| 1 | Identificar fabricante por banner/prompt SSH e testar drivers candidatos; mensagem de erro fiel | D4, D14 | 2 dias |
| 2 | Parsers: registros RouterOS sem índice; SR Linux via `\| as json` ou JSON-RPC; `lldpcli` com caminho completo | D7, D8, D11 | 2 dias |
| 2 | Ignorar IPs idênticos e interfaces de gerência na inferência L3; juntar vizinho BGP ao nó que tem aquele IP | D6, D12 | 1 dia |
| 2 | Vizinhos OSPF/BGP por REST (`/routing/ospf/neighbor`, `/routing/bgp/session`) e série/modelo via OpenConfig `platform` | D10, D13 | 2 dias |
| 2 | Fixtures de regressão com as saídas reais deste laboratório; laboratório rodando em cada pull request | qualidade | 2 dias |
| 3 | Token obrigatório, verificação de TLS e de chaves de host, cofre de credenciais | segurança | 1 semana |
| 3 | Laboratórios Huawei/Fortinet/VyOS (Redes Brasil) e Cisco (DevNet); teste de escala com 50-100 nós FRR | cobertura | 2 semanas |
| 3 | Cytoscape embutido no HTML, layout para redes grandes, IPv6 e VRF | produto | 3-4 semanas |

## Reprodução

```bash
# No GitHub: Actions → "Simulação em laboratório (Containerlab)" → Run workflow
# Resultados: artefato lab-results ou branch lab-results (runs/<id>/)
git clone -b lab-results https://github.com/tanatielly/network-discovery-automation resultados
python lab/scripts/score.py resultados/runs/36256925269-1          # métricas a partir dos JSONs
python docs/relatorios/build.py resultados/runs/36256925269-1 --pdf  # regenera estes relatórios
```

Arquivos do run: `metrics.json` (métricas por cenário), `raw/` (saídas brutas e `parse-matrix.json`),
`scenarios/<id>/` (topologia, eventos, logs e relatórios), `lab-state/` (estado dos equipamentos),
`quality/` (testes, cobertura, mypy, bandit) e `logs/` (cada etapa do workflow).
