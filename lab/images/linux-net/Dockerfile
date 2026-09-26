# Nó Linux do laboratório: FRR (roteamento) + lldpd (LLDP com LLDP-MIB via AgentX) + net-snmp + OpenSSH.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        frr frr-snmp lldpd snmpd snmp openssh-server iproute2 iputils-ping procps tcpdump ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
