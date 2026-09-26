---
title: NetTopo em laboratório
kicker: Relatório de gestão técnica
lede: Primeira rodada de testes da ferramenta NetTopo contra sistemas de rede reais, executada inteiramente na nuvem do GitHub. O documento resume o que funcionou, o que impede o uso em produção hoje e o que fazer a seguir.
other_label: Relatório técnico completo
toc: false
tag:
  Documento: NT-AVL-2026-01
  Versão avaliada: NetTopo 0.1.0 · f2823ea
  Execução: run 36256925269
  Data: 26/09/2026
  Ambiente: GitHub Actions + Containerlab
  Público: Gestão técnica de redes
data:
  high_defects: 4
  run_minutes: "16 min"
---

## Resumo

Montamos um laboratório virtual com 8 equipamentos de três famílias de sistemas (MikroTik RouterOS,
Nokia SR Linux e Linux com FRR) e rodamos a ferramenta em 11 cenários de descoberta, além da API, da
interface web e da linha de comando. Cada resultado foi comparado automaticamente com um gabarito do
que a ferramenta deveria encontrar.

A arquitetura se provou. A ferramenta conversou com os três sistemas por SNMP, SSH, NETCONF e API REST,
montou o diagrama, gerou os cinco formatos de documentação e não gravou nenhuma senha no banco de dados. Na melhor
configuração, coletou 6 dos 7 equipamentos e encontrou os 9 links reais.

O resultado ainda não é confiável o bastante para virar documentação oficial. Quatro defeitos de alta
severidade distorcem o inventário e o desenho: servidores diferentes fundidos num só, links duplicados,
equipamentos que ficam de fora quando anunciam um IP que o servidor não alcança e o modo só-SSH, que não
identifica nenhum equipamento.

<!-- viz:kpis -->

| Indicador | Valor |
|---|---|
| Equipamentos coletados na melhor configuração (APIs + SNMP para identificar) | 6 de 7 |
| Equipamentos coletados na configuração padrão, partindo de um único IP | 4 de 7 |
| Links reais encontrados na melhor configuração | 9 de 9 |
| Links desenhados que não existem (melhor configuração) | 2 de 11 |
| Defeitos de alta severidade em aberto | 4 |
| Tempo de uma rodada completa na nuvem | 16 min |

<!-- /viz -->

<div class="callout decision" markdown="1">
**Recomendação:** não usar ainda como fonte oficial de documentação. Aprovar um ciclo curto de correção
dos quatro defeitos de alta severidade (cerca de 2 semanas de uma pessoa, estimativa) e repetir este
mesmo laboratório como critério de aceite. Com o aceite atingido, seguir para um piloto somente leitura
numa rede real de escopo limitado.
</div>

## O que foi testado

- **Laboratório:** 8 equipamentos e 9 links. Dois roteadores MikroTik CHR 7.16 rodando como máquinas
  virtuais reais, dois switches Nokia SR Linux 25.10, um roteador Linux com FRR, dois servidores Linux e
  um roteador de operadora propositalmente sem credenciais, que deveria aparecer como "não coletado".
  Há OSPF entre as bordas e BGP com a operadora.
- **Cenários:** descoberta com todos os métodos, só SNMP (v2c e v3), só SSH, só APIs, credenciais erradas
  testadas primeiro, escopo limitado, execução sequencial, falha injetada (servidor desligado e link
  derrubado) e partida por um único IP ou por um inventário de IPs de gerência.
- **Produto completo:** API REST com acompanhamento em tempo real, interface web (com capturas de tela) e
  os quatro comandos da linha de comando.
- **Custo e hardware:** nenhum. Tudo roda num servidor temporário do GitHub Actions (4 vCPU, 16 GB).
  Uma rodada completa leva 16 minutos: monta o laboratório, executa os testes, publica os resultados no
  repositório e destrói o ambiente.

## Resultados por cenário

<!-- viz:scenarios -->

| Cenário | Equipamentos coletados | Links encontrados | Portas corretas | Tempo (s) |
|---|---|---|---|---|
| 01 Semente única, todos os métodos | 4/7 | 7/9 | 86% | 24,5 |
| 02 Semente única + DNS | 4/7 | 6/9 | 67% | 23,9 |
| 03 Inventário de IPs de gerência | 5/7 | 6/9 | 50% | 24,2 |
| 04 Somente SNMP v2c | 1/7 | 3/9 | 67% | 0,8 |
| 05 Somente SNMPv3 | 3/7 | 4/9 | 100% | 10,9 |
| 06 Somente SSH | 0/7 | 0/9 | — | 118,1 |
| 07 Somente APIs (REST/NETCONF) | 6/7 | 9/9 | 89% | 13,6 |
| 08 Credenciais erradas primeiro | 4/7 | 7/9 | 86% | 44,0 |
| 09 Profundidade 1 + exclusão | 2/7 | 5/9 | 80% | 23,7 |
| 10 Inventário sequencial | 5/7 | 7/9 | 71% | 41,7 |
| 11 Após falha injetada | 5/7 | 6/9 | 67% | 24,3 |

<!-- /viz -->

- **Melhor combinação:** APIs (REST no MikroTik, NETCONF no SR Linux) com SNMP só para identificar o
  fabricante. Foi também a mais rápida entre as completas: 13,6 s.
- **Configuração padrão a partir de um IP:** 4 de 7. O segundo MikroTik anuncia aos vizinhos um IP de
  interface que o servidor de descoberta não alcança, e a ferramenta não tenta outra forma de chegar
  nele. Resolver nomes por DNS não mudou o resultado.
- **Partindo do inventário de IPs:** alcança todos os equipamentos, mas os três servidores Linux são
  fundidos num só registro, por isso o resultado para em 5 de 7.
- **Só SSH:** 0 de 7 em 118 s. Sem SNMP, a ferramenta não reconhece o fabricante e desiste.
- **Credenciais erradas primeiro:** mesmo resultado do cenário padrão, com 19,5 s a mais. A ferramenta
  aprende qual credencial funciona e passa a usá-la primeiro.
- **Falha injetada:** o servidor desligado aparece na lista de falhas e os links perdidos somem do
  desenho. A comparação entre as duas descobertas ficou poluída pela fusão dos servidores.

<!-- viz:shot ui-resultado | Interface web com a descoberta disparada pela API. Os defeitos aparecem no próprio desenho: um único "srv1" no lugar de três hosts Linux, linhas duplas entre edge-mk1 e core-srl1 e um link mgmt0 entre os dois switches que não existe na rede de dados. -->

<div class="grid-2" markdown="1">
<div class="pro" markdown="1">

### Pontos fortes

- Funciona com três sistemas diferentes e quatro protocolos, escolhendo o melhor disponível em cada
  equipamento.
- Diagrama por camadas (borda, núcleo, acesso) legível e editável no draw.io.
- Documentação completa em HTML, Excel, Markdown e JSON gerada em segundos.
- Equipamentos sem acesso aparecem no desenho pelo que os vizinhos anunciam.
- Nenhuma senha gravada no banco de dados (verificado).
- Perfis de fabricante em arquivos de configuração: incluir um fabricante não exige programar.
- Laboratório automatizado e reproduzível, sem custo, pronto para rodar a cada mudança.

</div>
<div class="con" markdown="1">

### Pontos fracos

- Servidores e VMs podem ser fundidos num único equipamento no inventário.
- Links duplicados quando os dois lados descrevem a porta de formas diferentes.
- Não alcança equipamentos que anunciam um IP não roteável para o servidor.
- Modo só-SSH não funciona sem SNMP.
- LLDP da rede de gerência cria links que não existem.
- Leitura por linha de comando falha em parte das saídas do SR Linux e nas rotas do RouterOS 7.
- Vizinhos OSPF não aparecem; o vizinho BGP da operadora vira um equipamento duplicado.

</div>
</div>

## Riscos se usada hoje em produção

| Risco | Como aparece na documentação | Causa |
|---|---|---|
| Inventário menor que o real | Vários servidores ou VMs viram um só equipamento | Número de série lido errado em Linux e usado para identificar o equipamento |
| Desenho com cabos que não existem | Links duplicados e ligações pela rede de gerência | Nomes de porta diferentes entre os lados; LLDP ligado na gerência |
| Partes da rede ausentes | Equipamentos aparecem como "não coletados" mesmo com acesso liberado | Sem alternativa quando o IP anunciado pelo vizinho não responde |
| Resultado varia entre execuções | Nome do equipamento fundido muda de uma rodada para outra | Consequência do primeiro risco |
| Dependência de SNMP | Em redes só com SSH, nada é descoberto | Identificação do fabricante depende de SNMP |

## Plano de ação

| Quando | O quê | Resultado esperado | Esforço (estimativa) |
|---|---|---|---|
| Semanas 1-2 | Corrigir identificação de equipamentos (não usar modelo como número de série) | Fim das fusões indevidas | 1 dia |
| Semanas 1-2 | Unificar nomes de porta e ignorar LLDP da rede de gerência | Fim dos links duplicados e falsos | 2 dias |
| Semanas 1-2 | Tentar DNS, inventário e tabela ARP quando o IP anunciado não responde | Descoberta completa a partir de um IP | 3 dias |
| Semanas 1-2 | Identificar o fabricante por SSH sem depender de SNMP | Modo só-SSH funcional | 2 dias |
| Semanas 1-2 | Ajustar leitura de rotas RouterOS 7 e saídas do SR Linux | Dados completos por CLI | 2 dias |
| Semana 3 | Repetir o laboratório e validar o critério de aceite | Liberação para piloto | 1 dia |
| Mês 2 | Laboratórios Huawei, Fortinet, VyOS e Cisco; vizinhos OSPF/BGP por API | Cobertura dos fabricantes mais usados no Brasil | 2 semanas |
| Mês 2 | Autenticação obrigatória na API e validação de certificados e chaves SSH | Uso seguro em rede corporativa | 1 semana |
| Trimestre | Descoberta agendada com histórico, integração com NetBox, IPv6 e redes grandes | Documentação sempre atualizada | 4-6 semanas |

## Critério de aceite para o piloto

Na mesma simulação, que roda automaticamente a cada mudança:

- 7 de 7 equipamentos coletáveis a partir de um único IP e a partir do inventário;
- 9 de 9 links, nenhum link a mais e as duas portas corretas em todos;
- nenhum equipamento fundido e o mesmo resultado em duas execuções seguidas;
- modo só-SSH coletando MikroTik, SR Linux e Linux;
- operadora sem credenciais aparecendo como "não coletado".

## Próximos laboratórios

- **Lab em Nuvem Redes Brasil** (assinatura paga, acesso pelo navegador): Huawei, Fortinet, VyOS e Nokia
  SR OS, relevantes para provedores brasileiros e ausentes deste laboratório.
- **Cisco DevNet Sandbox** (gratuito com conta Cisco): IOS-XE e NX-OS reais para validar SSH, RESTCONF,
  NETCONF e NX-API.
- **Teste de escala** no próprio GitHub: 50 a 100 roteadores Linux/FRR para medir tempo e memória.

Os resultados brutos, os logs e o laboratório estão no repositório
[network-discovery-automation](https://github.com/tanatielly/network-discovery-automation), branch
`lab-results`. O relatório técnico detalha cada defeito com arquivo e linha do código.
