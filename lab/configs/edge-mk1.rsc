# edge-mk1 - MikroTik CHR (borda / BGP com a operadora / OSPF com edge-mk2)
/system identity set name=edge-mk1
/ip address add address=200.200.10.2/30 interface=ether2 comment=ISP-PE
/ip address add address=10.255.0.1/30 interface=ether3 comment=EDGE-MK2
/ip address add address=10.10.1.1/30 interface=ether4 comment=CORE-SRL1
/interface ethernet set [find default-name=ether2] comment="Uplink operadora"
/interface ethernet set [find default-name=ether3] comment="Interlink edge-mk2"
/interface ethernet set [find default-name=ether4] comment="Core SRL1"
/ip neighbor discovery-settings set discover-interface-list=all protocol=cdp,lldp,mndp
/snmp set enabled=yes contact="noc@nettopo.lab" location="Borda - Rack A"
/ip service set www disabled=no port=80
/ip route add dst-address=10.10.0.0/16 gateway=10.10.1.2
/routing ospf instance add name=ospf-lab version=2 router-id=10.255.255.1
/routing ospf area add name=backbone area-id=0.0.0.0 instance=ospf-lab
/routing ospf interface-template add area=backbone interfaces=ether3 type=ptp
/routing bgp connection add name=operadora as=65001 local.role=ebgp remote.address=200.200.10.1 remote.as=64500 router-id=10.255.255.1
