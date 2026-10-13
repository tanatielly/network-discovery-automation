---
title: Mapa de Rede em laboratório
kicker: Relatório de gestão técnica · 2ª avaliação
lede: A versão 0.2.0 corrigiu os 14 defeitos da primeira avaliação, passou a lembrar da rede entre execuções e a limitar a carga nos equipamentos. No mesmo laboratório, agora com 17 cenários e critério automático de aceite, a ferramenta não cometeu nenhum erro.
other_label: Relatório técnico completo
toc: false
tag:
  Documento: NT-AVL-2026-01 · rev. 2
  Versão avaliada: Mapa de Rede 0.2.0 · 7586686
  Execução: run 38434923523 (suíte completa)
  Comparada com: v0.1.0 · run 36256925269
  Data: 13/10/2026
  Ambiente: GitHub Actions + Containerlab
  Público: Gestão técnica de redes
data:
  kpis:
    - ["0", "erros em 17 cenários", "qualquer erro em relação ao gabarito reprova a rodada"]
    - ["7 de 7", "equipamentos coletados", "partindo de um único IP, com varredura, memória ou DNS"]
    - ["9 de 9", "links, nenhum a mais", "portas corretas nas duas pontas em todos os cenários"]
    - ["3,3 s", "para reconfirmar a rede inteira", "2ª execução, contra 33,6 s da descoberta inicial"]
    - ["500 ms", "entre requisições no perfil conservador", "e 1 sessão por equipamento, medidos em todos"]
    - ["6 min 54 s", "por rodada a cada mudança", "antes 16 min; suíte completa diária: 11 min 58 s"]
  compare:
    - ["Equipamentos coletados a partir de um IP", "4 de 7", "7 de 7", "com varredura, memória ou DNS; sem nenhum deles, 6 de 7 e o 7º aparece com o motivo"]
    - ["Modo só SSH (sem SNMP)", "0 de 7 em 118 s", "7 de 7 em 16,5 s", "fabricante identificado pelo banner e pelo prompt"]
    - ["Modo só SNMP", "1 de 7", "7 de 7", "com a varredura da rede de gerência"]
    - ["Links desenhados que não existem", "2 de 11", "0", "em todos os cenários"]
    - ["Equipamentos fundidos indevidamente", "3 hosts em 1", "nenhum", "série genérica de VM deixou de identificar o host"]
    - ["Portas corretas nos links", "50 a 89%", "100%", "em todos os cenários"]
    - ["Vizinhos OSPF/BGP", "OSPF em 0 de 11 cenários", "OSPF e BGP detectados", "em todos os cenários que alcançam as bordas"]
    - ["Mesmo resultado ao repetir", "não", "sim", "cenário 13 idêntico ao 02"]
    - ["Segunda descoberta da mesma rede", "recoleta tudo", "3,3 s", "7 de 7 confirmados ativos, sem recoleta"]
    - ["Equipamento que caiu", "só uma linha em falhas", "inacessível + histórico", "links removidos marcados; volta a ativo ao restaurar"]
    - ["Proteção contra sobrecarga", "nenhuma", "rate limit por equipamento", "três perfis e ajustes por rede, fabricante ou nome"]
    - ["Senhas", "digitadas a cada execução", "cofre cifrado local", "nenhum segredo gravado em disco (verificado)"]
    - ["Tempo de uma rodada no GitHub", "16 min a cada push", "6 min 54 s a cada push", "suíte completa diária às 06:00: 11 min 58 s"]
    - ["Defeitos de alta severidade", "4 abertos", "0", "14 de 14 corrigidos; 11 com teste de regressão próprio, todos verificados no laboratório"]
---

## Resumo

A primeira avaliação (26/09) mostrou que a arquitetura funcionava, mas que o resultado não era confiável:
servidores fundidos num só, links duplicados, equipamentos que ficavam de fora e o modo só-SSH inoperante.
A recomendação foi um ciclo curto de correção com este mesmo laboratório como critério de aceite.

A versão 0.2.0 fechou os 14 defeitos e trouxe o que faltava para uso contínuo: a ferramenta **guarda o
inventário** e, na execução seguinte, **confirma em segundos** que cada equipamento continua ativo e com os
mesmos vizinhos, recoletando só o que mudou. Ela também **limita a carga** em cada equipamento, para não
pesar em equipamentos antigos, e guarda as **senhas num cofre cifrado**.

O laboratório passou a reprovar automaticamente qualquer divergência em relação ao gabarito. Na suíte
completa (17 cenários: métodos isolados, credenciais erradas, escopo, SNMPv3, carga conservadora,
repetição, falha injetada, API, interface web e linha de comando), o resultado foi **zero erros**.

<!-- viz:kpis -->

| Indicador | Valor |
|---|---|
| Erros em relação ao gabarito, 17 cenários | 0 |
| Equipamentos coletados, partindo de um único IP | 7 de 7 |
| Links encontrados, sem nenhum a mais | 9 de 9 |
| Reconfirmar a rede inteira na 2ª execução | 3,3 s (descoberta inicial: 33,6 s) |
| Intervalo entre requisições no perfil conservador | 500 ms, 1 sessão por equipamento |
| Rodada do laboratório a cada mudança | 6 min 54 s (antes 16 min) |

<!-- /viz -->

<div class="callout decision" markdown="1">
**Recomendação:** o critério de aceite definido na primeira avaliação foi atingido. Liberar um **piloto
somente leitura** numa rede real de escopo limitado (um site ou um bloco de gerência), com o perfil de
carga **conservador** nos equipamentos antigos e o laboratório diário mantido como proteção contra
regressões. Em paralelo, ampliar o laboratório para os fabricantes mais comuns no Brasil (Huawei, Cisco,
Fortinet), que ainda não foram testados com equipamentos reais.
</div>

## Antes e depois

<!-- viz:compare -->

| Indicador | v0.1.0 | v0.2.0 | Observação |
|---|---|---|---|
| Equipamentos coletados a partir de um IP | 4 de 7 | 7 de 7 | com varredura, memória ou DNS; sem nenhum deles, 6 de 7 e o 7º aparece com o motivo |
| Modo só SSH (sem SNMP) | 0 de 7 em 118 s | 7 de 7 em 16,5 s | fabricante identificado pelo banner e pelo prompt |
| Modo só SNMP | 1 de 7 | 7 de 7 | com a varredura da rede de gerência |
| Links desenhados que não existem | 2 de 11 | 0 | em todos os cenários |
| Equipamentos fundidos indevidamente | 3 hosts em 1 | nenhum | série genérica de VM deixou de identificar o host |
| Portas corretas nos links | 50 a 89% | 100% | em todos os cenários |
| Vizinhos OSPF/BGP | OSPF em 0 de 11 cenários | OSPF e BGP detectados | em todos os cenários que alcançam as bordas |
| Mesmo resultado ao repetir | não | sim | cenário 13 idêntico ao 02 |
| Segunda descoberta da mesma rede | recoleta tudo | 3,3 s | 7 de 7 confirmados ativos, sem recoleta |
| Equipamento que caiu | só uma linha em falhas | inacessível + histórico | links removidos marcados; volta a ativo ao restaurar |
| Proteção contra sobrecarga | nenhuma | rate limit por equipamento | três perfis e ajustes por rede, fabricante ou nome |
| Senhas | digitadas a cada execução | cofre cifrado local | nenhum segredo gravado em disco (verificado) |
| Tempo de uma rodada no GitHub | 16 min a cada push | 6 min 54 s a cada push | suíte completa diária às 06:00: 11 min 58 s |
| Defeitos de alta severidade | 4 abertos | 0 | 14 de 14 corrigidos; 11 com teste de regressão próprio, todos verificados no laboratório |

<!-- /viz -->

## O que muda para quem usa

- **Memória da rede.** A primeira descoberta grava o inventário. Nas seguintes, cada equipamento conhecido
  passa por uma checagem leve (quem é e quem são seus vizinhos). Se nada mudou, os dados são reaproveitados e
  marcados "confirmado agora"; se mudou, só ele é recoletado; se não responde, aparece como "inacessível
  desde..." e o histórico registra o evento. O comando `nettopo verificar` faz só essa confirmação e pode ser
  agendado.
- **Carga controlada.** Três perfis (conservador, equilibrado, rápido) definem o intervalo mínimo entre
  requisições, quantas sessões abrir por equipamento e quantas tentativas de login aceitar, para não bloquear
  contas no servidor de autenticação. Dá para aplicar um perfil mais cuidadoso só a uma rede, a um fabricante
  ou a nomes de equipamentos. A carga aplicada fica registrada em cada equipamento do relatório.
- **Senhas fora dos arquivos.** As credenciais ficam no cofre do sistema operacional ou num arquivo cifrado,
  são referenciadas pelo nome e nunca aparecem no banco, nos logs ou na API.
- **Equipamentos que ninguém anuncia.** Uma varredura opcional da rede de gerência encontra equipamentos que
  os vizinhos anunciam com um IP inalcançável. Fica desligada por padrão.
- **Menos peso nos equipamentos.** O SNMP passou a complementar só o que a API ou o SSH não trouxeram: as
  requisições por equipamento caíram de cerca de 95 para 27 a 44 no laboratório.

## Resultados por cenário

<!-- viz:scenarios -->

| Cenário | Erros | Coletados | Links | Tempo (s) |
|---|---|---|---|---|
| 01 Semente única, sem DNS nem memória | 0 | 6/6 | 9/9 | 30,3 |
| 02 Semente única + varredura da gerência | 0 | 7/7 | 9/9 | 33,6 |
| 03 Segunda execução, usando a memória | 0 | 7/7 | 9/9 | 3,3 |
| 04 Somente SSH | 0 | 7/7 | 9/9 | 16,5 |
| 05 Somente SNMP v2c + varredura | 0 | 7/7 | 9/9 | 22,3 |
| 06 APIs (REST, JSON-RPC, NETCONF) | 0 | 7/7 | 9/9 | 17,2 |
| 07 Semente única + DNS | 0 | 7/7 | 9/9 | 29,8 |
| 08 Credenciais erradas primeiro | 0 | 7/7 | 9/9 | 19,3 |
| 09 Profundidade 1 + exclusão | 0 | 2/2 | 5/5 | 14,7 |
| 10 Inventário, 1 coleta por vez | 0 | 7/7 | 9/9 | 55,9 |
| 11 Somente SNMPv3 | 0 | 3/3 | 4/4 | 8,3 |
| 12 Carga conservadora (500 ms, 1 sessão) | 0 | 7/7 | 9/9 | 68,7 |
| 13 Repetição sem memória (determinismo) | 0 | 7/7 | 9/9 | 33,6 |
| 14 Verificação após falha injetada | 0 | 6/6 | 7/7 | 25,2 |
| 15 Verificação após restaurar | 0 | 7/7 | 9/9 | 11,9 |
| 16-api-ui API, cofre e interface web | 0 | — | — | 13,4 |
| cli Comandos da CLI | 0 | — | — | — |

<!-- /viz -->

- **01, sem DNS, memória nem varredura:** `edge-mk2` só é anunciado pelo IP do link de trânsito, que o servidor
  de descoberta não alcança. Nenhum protocolo revela outro endereço, então o resultado correto é "não coletado"
  com o motivo explícito, e é isso que aparece. Com DNS (07), varredura (02) ou memória (03), ele é coletado.
- **03, segunda execução:** os 7 equipamentos foram confirmados ativos em 3,3 s, sem recoleta.
- **14 e 15, falha e restauração:** com o `srv2` congelado e um link derrubado, a verificação marcou o `srv2`
  como inacessível e os dois links como removidos. Depois da restauração, ele voltou a ativo e o desenho
  voltou a ter os 9 links.
- **12, carga conservadora:** a telemetria de cada equipamento mostrou intervalo mínimo de 500 ms e no máximo
  uma sessão simultânea, como configurado.

<!-- viz:shot relatorio-diagrama | Relatório HTML da descoberta com varredura (cenário 02): operadora, bordas MikroTik, núcleo SR Linux, roteador Linux na distribuição e servidores, com as portas de cada lado. -->

<!-- viz:shot ui-inventario | Tela de inventário da interface web: status de cada equipamento, quando foi confirmado e qual acesso funcionou, além das mudanças recentes. -->

## Riscos que permanecem

| Risco | Por que importa | Como tratar |
|---|---|---|
| Fabricantes ainda não testados com equipamento real | Cisco, Huawei, Juniper, Fortinet e outros têm perfis, mas só MikroTik, Nokia SR Linux e Linux passaram pelo laboratório | Laboratórios Huawei/Fortinet (Redes Brasil) e Cisco (DevNet) antes de ampliar o piloto |
| Escala | O laboratório tem 8 equipamentos; não sabemos o tempo e a memória com centenas | Teste com 50 a 100 roteadores Linux/FRR no próprio GitHub |
| Certificados e chaves de host | Verificação de TLS e de chave SSH segue desligada por padrão | Ligar por padrão no piloto, com lista de exceções |
| Equipamento sem IP alcançável anunciado | Sem DNS, inventário ou varredura, ele fica como "não coletado" | Cadastrar DNS ou ligar a varredura na rede de gerência |

## Próximos passos

| Quando | O quê | Resultado esperado |
|---|---|---|
| Próximas 2 semanas | Piloto somente leitura em um site, perfil conservador, `nettopo verificar` agendado diariamente | Inventário confirmado todo dia e histórico de mudanças |
| Mês 1 | Laboratórios Huawei, Fortinet e Cisco | Cobertura dos fabricantes mais usados no Brasil |
| Mês 1 | Verificação de TLS e chaves SSH ligada por padrão | Uso seguro em rede corporativa |
| Mês 2 | Teste de escala com 50 a 100 nós | Tempo e memória conhecidos para redes grandes |
| Trimestre | Integração com NetBox, IPv6 e VRF | Documentação como fonte oficial |

## Critério de aceite da primeira avaliação

| Critério | Resultado |
|---|---|
| 7 de 7 equipamentos a partir de um IP e a partir do inventário | atingido (varredura, memória, DNS ou inventário) |
| 9 de 9 links, nenhum a mais, portas corretas | atingido em todos os cenários |
| Nenhum equipamento fundido e mesmo resultado em duas execuções | atingido (cenário 13) |
| Modo só-SSH coletando MikroTik, SR Linux e Linux | atingido: 7 de 7 |
| Operadora sem credenciais aparecendo como "não coletado" | atingido, com o motivo |

Os resultados brutos, os logs e o laboratório estão no repositório
[network-discovery-automation](https://github.com/tanatielly/network-discovery-automation), branch
`lab-results`. O relatório técnico detalha cada correção, a memória, o rate limit, o desempenho e a qualidade
do código.
