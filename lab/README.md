# Laboratório NetTopo (Containerlab no GitHub Actions)

Laboratório virtual para testar o NetTopo contra sistemas de rede reais **sem usar hardware local**:
tudo roda num runner do GitHub Actions (`ubuntu-24.04`, 4 vCPU, 16 GB, KVM habilitado).

## Topologia

```
                 isp-pe (Linux/FRR, BGP AS64500 — sem credenciais do NetTopo)
                    | eth1 — ether2
   edge-mk1 (MikroTik CHR 7.16.2) —— ether3/ether3 (OSPF) —— edge-mk2 (MikroTik CHR 7.16.2)
        | ether4                                                   | ether4
   core-srl1 (Nokia SR Linux 25.10.5) —— e1-2/e1-2 —— core-srl2 (Nokia SR Linux 25.10.5)
        | e1-3                                        | e1-3          | e1-4
        +—————————————— dist-frr1 (Linux + FRR) ——————+              srv2 (Linux)
                          | eth3
                        srv1 (Linux)
```

| Nó | Sistema | Gerência | Acesso configurado |
|---|---|---|---|
| edge-mk1, edge-mk2 | MikroTik RouterOS 7.16.2 (CHR em VM/KVM via vrnetlab) | 172.20.20.11-12 | SSH, SNMP v2c, REST (HTTP), LLDP/CDP/MNDP |
| core-srl1, core-srl2 | Nokia SR Linux 25.10.5 | 172.20.20.21-22 | SSH, SNMP v2c, NETCONF + OpenConfig, LLDP |
| dist-frr1 | Debian 12 + FRR + lldpd | 172.20.20.31 | SSH, SNMP v2c/v3 (LLDP-MIB via AgentX) |
| srv1, srv2 | Debian 12 + lldpd | 172.20.20.41-42 | SSH, SNMP v2c/v3 |
| isp-pe | Debian 12 + FRR (BGP) | 172.20.20.2 | credenciais diferentes (deve virar "não coletado") |

As senhas nos arquivos são as padrão de laboratório (containerlab / imagens do lab), não segredos.

## Arquivos

| Arquivo | Função |
|---|---|
| `nettopo-lab.clab.yml` | Topologia Containerlab |
| `configs/` | Configuração de cada equipamento (SR Linux `.cfg`, MikroTik `.rsc`, FRR) |
| `images/linux-net/` | Imagem Linux com FRR, lldpd, net-snmp e OpenSSH |
| `ground_truth.yaml` | Gabarito: o que a ferramenta deve encontrar, com expectativa por cenário |
| `scripts/configure.py` | Espera o boot, garante a configuração e registra o estado real |
| `scripts/dump_raw.py` | Saídas brutas dos comandos + matriz de parsing |
| `scripts/run_scenarios.py` | Cenários das suítes `rapida` e `completa` |
| `scripts/score.py` | Conta os erros de cada cenário contra o gabarito → `metrics.json`, `summary.md` |

## Suítes e critério de aceite

| Suíte | Quando | Cenários |
|---|---|---|
| `rapida` | a cada push em `lab/`, `src/` ou no workflow | semente única; semente + varredura (cria a memória); segunda execução com memória; só SSH; só SNMP; APIs; falha injetada + `verificar`; restauração |
| `completa` | todo dia às 06:00 (Brasília), manual ou num push com `[lab completa]` na mensagem do commit | a rápida + DNS, credenciais erradas primeiro, escopo, sequencial, SNMPv3, carga conservadora, determinismo, API/UI com cofre, CLI |

Tempo típico do job com a imagem do CHR em cache: rápida ~7 min (8 cenários), completa ~13 min (17 cenários +
testes, cobertura, mypy e bandit). Sem cache, o build do CHR soma ~4 min uma única vez.

O job **falha se qualquer cenário tiver um erro**: link falso, duplicado ou faltando, porta errada,
equipamento duplicado/inesperado, fabricante ou papel errado, adjacência OSPF/BGP não detectada,
coleta repetida, memória que não reaproveitou, evento esperado ausente, carga acima do limite ou
resultado diferente entre execuções. Um equipamento que nenhuma informação disponível permite
alcançar (ex.: `edge-mk2` anunciado só pelo IP de trânsito, sem DNS nem memória) deve aparecer como
"não coletado" **com o motivo** — isso está no gabarito e não conta como erro.

A falha injetada congela o `srv2` (`docker pause`) e derruba o link `core-srl2`–`dist-frr1`; o LLDP
do lab anuncia a cada 5 s (TTL 20 s) para que a mudança apareça rápido.

## Como executar

- **No GitHub:** aba *Actions* → *Simulação em laboratório (Containerlab)* → *Run workflow*
  (escolha a suíte). A imagem do MikroTik CHR fica em cache entre execuções.
- **Resultados:** artefato `lab-results` do run e branch [`lab-results`](https://github.com/tanatielly/network-discovery-automation/tree/lab-results)
  (`runs/<id>/`: logs por etapa, saídas brutas, cenários, `metrics.json`, capturas de tela).
- **Métricas localmente** (sobre resultados baixados): `python lab/scripts/score.py <pasta-do-run> [--strict]`.
- **Numa máquina Linux com Docker e KVM:** siga os passos do workflow
  `.github/workflows/lab-simulation.yml` (containerlab, build do CHR, `containerlab deploy`, scripts).
