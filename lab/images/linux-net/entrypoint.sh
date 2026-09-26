#!/bin/bash
# Inicializa SSH, SNMP (v2c + v3), lldpd e, em roteadores, o FRR.
# Credenciais de LABORATÓRIO (não são segredos reais).
set -u

NODE_ROLE="${NODE_ROLE:-host}"
SSH_USER="${SSH_USER:-nettopo}"
SSH_PASS="${SSH_PASS:-NetTopo#2026}"
SNMP_COMMUNITY="${SNMP_COMMUNITY:-public}"
SNMPV3_USER="${SNMPV3_USER:-nettopo}"
SNMPV3_AUTH="${SNMPV3_AUTH:-authpass2026}"
SNMPV3_PRIV="${SNMPV3_PRIV:-privpass2026}"
MGMT_PATTERN="${MGMT_PATTERN:-172.20.20.*}"

log() { echo "[entrypoint] $*"; }

# ---------------------------------------------------------------- SSH
id "$SSH_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$SSH_USER"
echo "$SSH_USER:$SSH_PASS" | chpasswd
mkdir -p /run/sshd
ssh-keygen -A >/dev/null 2>&1
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
/usr/sbin/sshd && log "sshd ok"

# ---------------------------------------------------------------- SNMP
mkdir -p /var/agentx /var/lib/snmp
cat > /etc/snmp/snmpd.conf <<EOF
agentAddress udp:161
rocommunity ${SNMP_COMMUNITY} default
rouser ${SNMPV3_USER} priv
view all included .1
master agentx
agentXSocket /var/agentx/master
agentXPerms 0777 0777
sysLocation Containerlab NetTopo Lab
sysContact lab@nettopo.local
EOF
echo "createUser ${SNMPV3_USER} SHA \"${SNMPV3_AUTH}\" AES \"${SNMPV3_PRIV}\"" >> /var/lib/snmp/snmpd.conf
/usr/sbin/snmpd -Lsd -p /run/snmpd.pid && log "snmpd ok"
sleep 1

# ---------------------------------------------------------------- Roteamento
if [ "$NODE_ROLE" = "router" ]; then
    sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || log "aviso: ip_forward não alterado"
    cat > /etc/frr/daemons <<EOF
zebra=yes
bgpd=yes
ospfd=yes
staticd=yes
vtysh_enable=yes
zebra_options="  -A 127.0.0.1 -s 90000000 -M snmp"
bgpd_options="   -A 127.0.0.1 -M snmp"
ospfd_options="  -A 127.0.0.1 -M snmp"
staticd_options="-A 127.0.0.1"
EOF
    chown -R frr:frr /etc/frr 2>/dev/null || true
    /usr/lib/frr/frrinit.sh start && log "frr ok"
fi

# ---------------------------------------------------------------- LLDP
# Só nas interfaces de dados (eth1..), anunciando o IP de gerência; LLDP-MIB exportada via AgentX.
lldpd -x -X /var/agentx/master -I 'eth[1-9]*' -m "${MGMT_PATTERN}" && log "lldpd ok"

exec sleep infinity
