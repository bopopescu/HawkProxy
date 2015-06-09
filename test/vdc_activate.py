#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time

'''
s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
print "Delete Department1", s.genericPhptoPy("department", 29, "delete", None)
sys.exit()
'''
slice = {"name": "labSlice", "url": "http://cloudflow.dyndns.biz:8220",
         "description": "first slice @ http://cloudflow.dyndns.biz:8200"}

s2dbid = 0

print "calling RPC Server",
s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
# Print list of available methods
print s.system.listMethods()

# print "Create Slice2",
# response = json.loads(s.genericPhptoPy("slice", 0, "create", json.dumps(slice2)))
# if "dbid" in response:
#    s2dbid = response["dbid"]
# print response
# slice2updated = {"name": "labSlice2222", "url": "http://192.168.227.2:8220", "description": "Slice @ hasasasasasttp://192.168.227.2:8220"}
# response = json.loads(s.genericPhptoPy("slice", s2dbid, "update", json.dumps(slice2updated)))
# print "update Slice", response
# sys.exit()
sdbid = 0
# Create Slice
print "Create Slice1",
response = json.loads(s.genericPhptoPy("slice", 0, "create", json.dumps(slice)))
if "dbid" in response:
    sdbid = response["dbid"]
print response

# Delete Slice
# if s2dbid != 0:
#    print "Delete Slice2", s.genericPhptoPy("slice", s2dbid, "delete", None)


organization = {"name": "westcoast", "description": "first test organization - before update", "email": "a@b.com",
                "DefaultSliceEntityId": sdbid,
                "resources": [
                    {"catagory": "compute", "type": "default", "cpu": 10, "ram": 20, "network": 200},
                    {"catagory": "storage", "type": "gold", "capacity": 22, "iops": 333, "network": 200},
                    {"catagory": "network", "type": "vpn", "throughput": 220},
                    {"catagory": "network", "type": "nat", "throughput": 300}
                ]
                }

department = {"name": "aDept", "description": "first test department - before update", "email": "a@b.com",
              "DefaultSliceEntityId": sdbid,
              "ParentEntityName": "westcoast",
              "resources": [
                  {"catagory": "compute", "type": "default", "cpu": 10, "ram": 20, "network": 200},
                  {"catagory": "storage", "type": "gold", "capacity": 22, "iops": 333, "network": 200},
                  {"catagory": "network", "type": "vpn", "throughput": 220},
                  {"catagory": "network", "type": "nat", "throughput": 300}
              ]
              }

print "Create Organization",
odbid = 0
response = json.loads(s.genericPhptoPy("organization", 0, "create", json.dumps(organization)))
print response
if "dbid" in response:
    odbid = response["dbid"]

ddbid = 0
print "Create Department...",
response = json.loads(s.genericPhptoPy("department", 0, "create", json.dumps(department)))
print  response
if "dbid" in response:
    ddbid = response["dbid"]

vn = {"entitytype": "virtual_network", "name": "network1", "description": "first network", "parententityid": odbid,
      "throughput": 100, "networktype": "shared",
      "attached_entities": [{"entitytype": "departments", "entities": [{"attachedentityid": ddbid},
                                                                       ]}]
      }
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(vn)))
if "dbid" in response:
    vndbid1 = response["dbid"]
print "Create network....", response

vdbid = 0
vdc1 = {"name": "vdc2", "description": "first test vdc", "parententityid": ddbid,
        "vdcperformancepoliy": "Best Effort (VDC overrides device)",
        "highavailabilityoptions": "Full redundancy",
        "selectedsliceentityid": sdbid,
        "slicepreferencepolicy": "Device overrides VDC",
        "vdcperformancepolicy": "Best effort"
        }
print "Create VDC....",

response = json.loads(s.genericPhptoPy("vdc", 0, "create", json.dumps(vdc1)))
print response
if "dbid" in response:
    vdbid = response["dbid"]

vdc1u = {"name": "vdc1", "description": "first test vdcUPDATED", "parententityid": ddbid}
print "Update VDC....", s.genericPhptoPy("vdc", vdbid, "update", json.dumps(vdc1u))

print "Command deprovision VDC", json.loads(
    s.genericPhptoPy("entity", vdbid, "command", json.dumps({"command": "deprovision"})))

cdbid = 0
cont = {"entitytype": "container", "name": "firstcontainer", "description": "first container", "parententityid": vdbid,
        "capacity": 11, "iops": 22}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(cont)))
if "dbid" in response:
    cdbid = response["dbid"]
print "Create container....", response

cont1 = {"entitytype": "container", "name": "2ndcontainer", "description": "first containerUPDATED",
         "parententityid": vdbid, "capactiy": 33, "iops": 44}
response = json.loads(s.genericPhptoPy("entity", cdbid, "update", json.dumps(cont1)))
print "Update container....", response

vldbid1 = 0
volume = {"entitytype": "volume", "name": "volume1", "description": "first volumer", "parententityid": cdbid,
          "capacity": 8,
          "snapshotpolicy": "enabled", "snpoliytype": "recurring", "snpolicyhrs": "1,5,7,12,20,22",
          "backuppolicy": "enabled", "bkpoliytype": "recurring", "bkpolicyweekdays": "mon,wed,fri,sun",
          "bkpolicytime": "00:05:06",
          "archivepolicy": "enabled", "arpoliytype": "recurring", "arpolicymonthdays": "1,7,14,21,27",
          "arpolicytime": "04:05:06"
          }
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(volume)))
if "dbid" in response:
    vldbid1 = response["dbid"]
print "Create volume....", response

volume1 = {"entitytype": "volume", "name": "volume1", "description": "first volumeUPDATED", "capacity": 8}
response = json.loads(s.genericPhptoPy("entity", vldbid1, "update", json.dumps(volume1)))
print "Update volume....", response
for x in xrange(1):
    print "Volume Status", json.loads(s.genericPhptoPy("entity", vldbid1, "status", None))

print "Command Volume Command", json.loads(s.genericPhptoPy("entity", vldbid1, "command",
                                                            json.dumps({"command": "provision"})))

vldbid2 = 0
volume2 = {"entitytype": "volume", "name": "volume2", "description": "2nd volume", "parententityid": cdbid,
           "capacity": 8}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(volume2)))
if "dbid" in response:
    vldbid2 = response["dbid"]
print "Create volume....", response

sfdbid = 0
farm = {"entitytype": "serverfarm", "name": "farm", "description": "first farm", "parententityid": vdbid,
        "attached_entities": [{"entitytype": "volume", "entities": [{"attachedentityid": vldbid1},
                                                                    {"attachedentityid": vldbid2}]}]
        }

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(farm)))
if "dbid" in response:
    sfdbid = response["dbid"]
print "Create server farm....", response

# b  "volumes": [vldbid1, vldbid2]


farm1 = {"entitytype": "serverfarm", "name": "farm", "description": "first farmUpdate",
         "attached_entities": [{"entitytype": "volume", "entities": [{"attachedentityid": vldbid1},
                                                                     {"attachedentityid": vldbid2}]}]

         }
print "Update ServerFarm", json.loads(s.genericPhptoPy("entity", sfdbid, "update", json.dumps(farm1)))
#        "volumes": [vldbid1, vldbid2],


svdbid = 0
srvc = {"entitytype": "server", "name": "server1", "description": "first server", "parententityid": sfdbid,
        "attached_entities": [{"entitytype": "volume", "entities": [{"attachedentityid": vldbid1},
                                                                    {"attachedentityid": vldbid2}]}],
        "bootvolumeentityid": vldbid1, "bootimageentityid": 2,
        "boot_image": {"image_name": "lib1image7", "library_name": "SystemLibrary"},
        "user_data": "this is a textual user data",
        "metadata": [{"thekey": "firstkey", "thevalue": "firstvalue"}, {"thekey": "2ndkey", "thevalue": "2ndvalue"}]}

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(srvc)))
if "dbid" in response:
    svdbid = response["dbid"]
print "Create server....", response

srvc1 = {"entitytype": "server", "name": "server1Updated", "description": "first serverUpdate"}
print "Update Server", json.loads(s.genericPhptoPy("entity", svdbid, "update", json.dumps(srvc1)))

sgdbid = 0
sgrp = {"entitytype": "security_group", "name": "sg1", "description": "first sg", "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(sgrp)))
if "dbid" in response:
    sgdbid = response["dbid"]
print "Create Security Group....", response

srdbid = 0

sgrpRule = {"entitytype": "security_rule", "name": "sg1", "description": "first rule", "parententityid": sgdbid,
            "action": "allow", "alram_threashold": 10, "source_ip": "0.0.0.0", "destination_ip": "0.0.0.0",
            "from_port": 0, "to_port": 80,
            "fw_application": "http", "protocol": "tcp", "track": "None", "traffic_direction": "both",
            "start_time": "10:00:00", "stop_time": "18:00:00"}

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(sgrpRule)))
if "dbid" in response:
    srdbid = response["dbid"]
print "Create Security Rule....", response

lbsgdbid = 0
lgrp = {"entitytype": "lbs_group", "name": "lbd1", "description": "first lbs", "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(lgrp)))
if "dbid" in response:
    lbsgdbid = response["dbid"]
print "Create LBS Group....", response

lbssdbid = 0

lbsService = {"entitytype": "lbs_service", "name": "lbs1ser", "description": "first lbs service",
              "parententityid": lbsgdbid,
              "method": "round robin", "port": 80, "protocol": "tcp", "health_monitor": "icmp",
              "health_check_interval": 200,
              "health_check_retries": 5}

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(lbsService)))
if "dbid" in response:
    lbssdbid = response["dbid"]
print "Create LBS Service....", response

acdbid = 0
acgrp = {"entitytype": "acl_group", "name": "acg1", "description": "first acl grp", "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(acgrp)))
if "dbid" in response:
    acdbid = response["dbid"]
print "Create ACL Group....", response

acrdbid = 0
aclRule = {"entitytype": "acl_rule", "name": "aclr1", "description": "first acl rule", "parententityid": acdbid,
           "action": "allow", "source_ip": "0.0.0.0", "destination_ip": "0.0.0.0",
           "from_port": 0, "to_port": 80,
           "service": "http", "protocol": "tcp", "traffic_direction": "both"}

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(aclRule)))
if "dbid" in response:
    acrdbid = response["dbid"]
print "Create ACL Rule....", response

vpndbid = 0
vpngrp = {"entitytype": "vpn_group", "name": "vpn1", "description": "first vpn grp", "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(vpngrp)))
if "dbid" in response:
    vpndbid = response["dbid"]
print "Create VPN Group....", response

vpncdbid = 0
vpnCon = {"entitytype": "vpn_connection", "name": "vpn connecton", "description": "first vpn connection",
          "parententityid": vpndbid,
          "AuthenticationMode": "Preshared_Key", "P1Authentication": "SHA1", "P1Encryption": "AES_128",
          "P1IKEMode": "Main", "P1NatTraversal": "No", "P1PFS": "2",
          "P2ActiveProtocol": "ESP", "P2Authentication": "SHA1", "P2EncapsulatioProtocol": "Tunnel",
          "P2Encryption": "AES_128", "P2PFS": "No", "P2ReplayDetection": "No", "PSK": "EnterNewKey",
          "PeerAddress": "0.0.0.0", "PeerSubnets": "0.0.0.0", }

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(vpnCon)))
if "dbid" in response:
    vpncdbid = response["dbid"]
print "Create VPN Connection....", response

nsswdbid = 0
subnet = {"entitytype": "switch_network_service", "name": "switch1", "description": "first subnet",
          "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(subnet)))
if "dbid" in response:
    nsswdbid = response["dbid"]
print "Create subnet....", response

nsextdbid = 0
ext = {"entitytype": "externalnetwork", "name": "externalNetwork", "description": "first external network",
       "parententityid": vdbid,
       "network": {"slice": sdbid, "name": "public"}}

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(ext)))
if "dbid" in response:
    nsextdbid = response["dbid"]
print "Create External Network....", response

'''
nsextdbid = 0
ext = {"entitytype": "externalnetwork", "parententityid": vdbid }

response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(ext)))
if "dbid" in response:
    nsextdbid = response["dbid"]
print "Create External Network....", response
'''

nsnatdbid = 0
nsnat = {"entitytype": "nat_network_service", "name": "nat1", "description": "first nat", "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(nsnat)))
if "dbid" in response:
    nsnatdbid = response["dbid"]
print "Create nat....", response

nsfwsdbid = 0
nsfws = {"entitytype": "fws_network_service", "name": "fws1", "description": "first fws", "parententityid": vdbid
         }
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(nsfws)))
if "dbid" in response:
    nsfwsdbid = response["dbid"]
print "Create fws....", response

nslbsdbid = 0
nslbs = {"entitytype": "lbs_network_service", "name": "lbs1", "description": "first lbs", "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(nslbs)))
if "dbid" in response:
    nslbsdbid = response["dbid"]
print "Create lbs....", response

nscnsdbid = 0
nscns = {"entitytype": "compute_network_service", "name": "cns1", "description": "first compute service",
         "parententityid": vdbid}
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(nscns)))
if "dbid" in response:
    nscnsdbid = response["dbid"]
print "Create compute service....", response

attach1 = {"attached_entities": [{"entitytype": "serverfarm", "entities": [{"attachedentityid": sfdbid}]}]}

print "Attach server farm to compute service", json.loads(
    s.genericPhptoPy("entity", nscnsdbid, "update", json.dumps(attach1)))

interface1 = {"entitytype": "network_interface", "parententityid": vdbid,
              "interfaceindex": 0, "inteface_type": "regular",
              "beginserviceentityid": nsswdbid, "endserviceentityid": nsnatdbid,
              "ports": [
                  {"serviceentityid": nsswdbid, "guarbandwidth": 100, "maxbandwidth": 200, "nattype": "static",
                   "securityzone": "trusted",
                   "attached_entities": [
                       {"entitytype": "acl_group", "entities": [{"attachedentityid": acdbid}]
                        }]},
                  {"serviceentityid": nsnatdbid, "guarbandwidth": 300, "maxbandwidth": 500, "nattype": "dynamic",
                   "securityzone": "untrusted",
                   "attached_entities": [
                       {"entitytype": "acl_group", "entities": [{"attachedentityid": acdbid}]
                        }]}]}

int1dbid = 0
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(interface1)))
if "dbid" in response:
    int1dbid = response["dbid"]
print "Create Interface1....", response

interface2 = {"entitytype": "network_interface", "parententityid": vdbid,
              "interfaceindex": 0, "inteface_type": "regular",
              "beginserviceentityid": nsextdbid, "endserviceentityid": nsnatdbid,
              "ports": [{"serviceentityid": nsextdbid,
                         "guarbandwidth": 100, "maxbandwidth": 200, "nattype": "static", "securityzone": "trusted"},
                        {"serviceentityid": nsnatdbid,
                         "guarbandwidth": 300, "maxbandwidth": 500, "nattype": "dynamic", "securityzone": "untrusted"
                         }]
              }

int2dbid = 0
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(interface2)))
if "dbid" in response:
    int2dbid = response["dbid"]
print "Create Interface 2 ....", response

interface3 = {"entitytype": "network_interface", "parententityid": vdbid,
              "interfaceindex": 0, "inteface_type": "regular",
              "beginserviceentityid": nsnatdbid, "endserviceentityid": nsfwsdbid,
              "ports": [{"serviceentityid": nsnatdbid,
                         "guarbandwidth": 100, "maxbandwidth": 200, "nattype": "static", "securityzone": "trusted"},
                        {"serviceentityid": nsfwsdbid,
                         "guarbandwidth": 300, "maxbandwidth": 500, "nattype": "dynamic", "securityzone": "untrusted"
                         }]
              }

int3dbid = 0
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(interface3)))
if "dbid" in response:
    int3dbid = response["dbid"]
print "Create Interface 3 ....", response

interface4 = {"entitytype": "network_interface", "parententityid": vdbid,
              "interfaceindex": 0, "inteface_type": "regular",
              "beginserviceentityid": nsfwsdbid, "endserviceentityid": nslbsdbid,
              "ports": [{"serviceentityid": nsfwsdbid,
                         "guarbandwidth": 100, "maxbandwidth": 200, "nattype": "static", "securityzone": "trusted",

                         "attached_entities": [
                             {"entitytype": "security_group", "entities": [{"attachedentityid": sgdbid}]}]
                         },
                        {"serviceentityid": nslbsdbid,
                         "guarbandwidth": 300, "maxbandwidth": 500, "nattype": "dynamic", "securityzone": "untrusted",
                         "attached_entities": [
                             {"entitytype": "lbs_group", "entities": [{"attachedentityid": lbsgdbid}]},
                             {"entitytype": "nat_network_service",
                              "entities": [{"attachedentityid": nsnatdbid, "ipaddresstype": "static",
                                            "staticipaddress": "192.168.228.90"}]
                              }]

                         }]
              }

int4dbid = 0
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(interface4)))
if "dbid" in response:
    int4dbid = response["dbid"]
print "Create Interface 4 ....", response

interface5 = {"entitytype": "network_interface", "parententityid": vdbid,
              "interfaceindex": 0, "inteface_type": "regular",
              "beginserviceentityid": nslbsdbid, "endserviceentityid": nscnsdbid,
              "ports": [{"serviceentityid": nslbsdbid,
                         "guarbandwidth": 100, "maxbandwidth": 200, "nattype": "static", "securityzone": "trusted"

                         },
                        {"serviceentityid": nscnsdbid,
                         "guarbandwidth": 300, "maxbandwidth": 500, "nattype": "dynamic", "securityzone": "untrusted",
                         "attached_entities": [
                             {"entitytype": "lbs_group", "entities": [{"attachedentityid": lbsgdbid}]}]
                         }]
              }

int5dbid = 0
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(interface5)))
if "dbid" in response:
    int5dbid = response["dbid"]
print "Create Interface 5 ....", response

print "Command provision VDC", json.loads(
    s.genericPhptoPy("entity", vdbid, "command", json.dumps({"commands": ["provision", "activate"]})))
sys.exit()

time.sleep(50)
print "Command cancel provision VDC", json.loads(
    s.genericPhptoPy("entity", vdbid, "command", json.dumps({"command": "cancel"})))

time.sleep(30)

sys.exit()

print "Command deprovision VDC", json.loads(
    s.genericPhptoPy("entity", vdbid, "command", json.dumps({"command": "deprovision"})))

print "Delete Subnet", s.genericPhptoPy("entity", nsswdbid, "delete", None)
print "Delete External Network", s.genericPhptoPy("entity", nsextdbid, "delete", None)
print "Delete Nat", s.genericPhptoPy("entity", nsnatdbid, "delete", None)
print "Delete LBS", s.genericPhptoPy("entity", nslbsdbid, "delete", None)

print "Delete Interface 1", s.genericPhptoPy("entity", int1dbid, "delete", None)
print "Delete Interface 2", s.genericPhptoPy("entity", int2dbid, "delete", None)

print "Delete User", s.genericPhptoPy("entity", uugdbid, "delete", None)
print "Delete User Group", s.genericPhptoPy("entity", ugdbid, "delete", None)

print "Delete VPN Connection", s.genericPhptoPy("entity", vpncdbid, "delete", None)
print "Delete VPN Group", s.genericPhptoPy("entity", vpndbid, "delete", None)

print "Delete ACL Rule", s.genericPhptoPy("entity", acrdbid, "delete", None)
print "Delete ACL Group", s.genericPhptoPy("entity", acdbid, "delete", None)
print "Delete LBS Servuce", s.genericPhptoPy("entity", lbssdbid, "delete", None)
print "Delete LBS Group", s.genericPhptoPy("entity", lbsgdbid, "delete", None)
print "Delete Security Rule", s.genericPhptoPy("entity", srdbid, "delete", None)
print "Delete Security Group", s.genericPhptoPy("entity", sgdbid, "delete", None)
print "Delete Server", s.genericPhptoPy("entity", svdbid, "delete", None)
print "Delete Farm", s.genericPhptoPy("entity", sfdbid, "delete", None)
print "Delete Volume", s.genericPhptoPy("entity", vldbid2, "delete", None)
print "Delete Volume", s.genericPhptoPy("entity", vldbid1, "delete", None)
print "Delete Container", s.genericPhptoPy("entity", cdbid, "delete", None)
print "Delete VDC....", s.genericPhptoPy("vdc", vdbid, "delete", None)
print "Delete Department", s.genericPhptoPy("department", ddbid, "delete", None)
print "Delete Department1", s.genericPhptoPy("department", ddbid1, "delete", None)
print "Delete Organization", s.genericPhptoPy("organization", odbid, "delete", None)

sys.exit()

# Delete Slice
print "Delete Slice", s.genericPhptoPy("slice", sdbid, "delete", None)

container_ids = []
for i in range(0, 10):
    c = {"entitytype": "container", "name": "container%s" % len(container_ids), "description": "a container",
         "parententityid": odbid,
         "capacity": 11, "iops": 22}
    response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(c)))
    if "dbid" in response:
        container_ids.append(response["dbid"])

bulkDelete = {"dbid": container_ids, "return_option": "immediately"}
response = json.loads(s.genericPhptoPy("entity", 0, "delete_multiple", json.dumps(bulkDelete)))

## wait a few seconds for the last delete to complete
time.sleep(10)

container_ids = []
for i in range(0, 10):
    c = {"entitytype": "container", "name": "container%s" % len(container_ids), "description": "a container",
         "parententityid": odbid,
         "capacity": 11, "iops": 22}
    response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(c)))
    if "dbid" in response:
        container_ids.append(response["dbid"])

bulkDelete = {"dbid": container_ids, "return_option": "upon_completion"}
response = json.loads(s.genericPhptoPy("entity", 0, "delete_multiple", json.dumps(bulkDelete)))

container_ids = []
for i in range(0, 10):
    c = {"entitytype": "container", "name": "container%s" % len(container_ids), "description": "a container",
         "parententityid": odbid,
         "capacity": 11, "iops": 22}
    response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(c)))
    if "dbid" in response:
        container_ids.append({"id": response["dbid"], "sortsequenceid": "%s" % (response["dbid"] * 5)})

bulkUpdate = {"entities": container_ids, "return_option": "upon_completion"}
print json.loads(s.genericPhptoPy("entity", 0, "update_multiple", json.dumps(bulkUpdate)))
