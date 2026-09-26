# edge-mk2 - MikroTik CHR (borda secundária / OSPF com edge-mk1)
/system identity set name=edge-mk2
/ip address add address=10.255.0.2/30 interface=ether3 comment=EDGE-MK1
/ip address add address=10.10.2.1/30 interface=ether4 comment=CORE-SRL2
/interface ethernet set [find default-name=ether3] comment="Interlink edge-mk1"
/interface ethernet set [find default-name=ether4] comment="Core SRL2"
/ip neighbor discovery-settings set discover-interface-list=all protocol=cdp,lldp,mndp
/snmp set enabled=yes contact="noc@nettopo.lab" location="Borda - Rack B"
/ip service set www disabled=no port=80
/ip route add dst-address=10.10.0.0/16 gateway=10.10.2.2
/routing ospf instance add name=ospf-lab version=2 router-id=10.255.255.2
/routing ospf area add name=backbone area-id=0.0.0.0 instance=ospf-lab
/routing ospf interface-template add area=backbone interfaces=ether3 type=ptp
