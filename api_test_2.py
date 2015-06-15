__author__ = 'vkoro_000'

import requests
import ujson as json
import time

admin_token = "fd01bd1ad68847d1bed4b3127376a9cc"
osa_token = "255f300cc33646e7afed8c60bb8462d3"
dsa_token = "efac710ad3b646e28412d922d0a66263"
vdcuser_token = "e5bcd0fd498045ea9859dce16e2c37c6"

URL = "http://localhost:8091/v2/"

department_uuid = "ae5175ea-9194-4d7e-9e0b-595183d468e2"

head = {"X-Auth-Token": admin_token, "Content-Type": "application/json"}

def post_req(url, json):
    r = requests.post(url, json=json, headers=head)
    if "error" in str(r.text).lower():
        print "ERROR IN POST REQUEST"
        print r.text
        quit()
    #print r.text
    return r
def put_req(url, json):
    return requests.put(url, json=json, headers=head)
def get_req(url):
    return requests.get(url, headers=head)

def provision(url):
    r = put_req(url + "/actions", {"provision": "null"})
    stat = ""
    while stat != "Provisioned":
        r = get_req(url)
        details = json.loads(r.text)
        if "CFD" in details.viewkeys():
            details = details["CFD"]
        if len(details.viewkeys()) == 1:
            details = details[details.iterkeys().next()]
        print details
        if "entitystatus" in details.viewkeys():
            stat = details["entitystatus"]
        else:
            stat = details["resource_state"]["state"]
        print url + ": " + stat
    return stat

def activate(url):
    r = put_req(url + "/actions", {"activate": "null"})
    stat = ""
    while stat != "Active":
        r = get_req(url)
        details = json.loads(r.text)
        if "CFD" in details.viewkeys():
            details = details["CFD"]
        if len(details.viewkeys()) == 1:
            details = details[details.iterkeys().next()]
        if "entitystatus" in details.viewkeys():
            stat = details["entitystatus"]
        else:
            stat = details["resource_state"]["state"]
        print url + ": " + stat
    return stat

def deprovision(url):
    #http://localhost:8091/v2/vdcs/vdcuuid/actions -d {"deprovision":"null"}
    r = put_req(url + "/actions", {"deprovision": "null"})
    return r.text

def destroy(url):
    #http://localhost:8091/v2/vdcs/vdcuuid/actions -d {"deprovision":"null"}
    r = put_req(url + "/actions", {"destroy": "null"})
    return r.text

# s_uuid = "4dc5fd71-6387-421f-b17f-c0379b485059"
# print get_req(URL + "servers/" + s_uuid).text
# quit()

starttime = time.clock()
print "BEGIN ENTITY CREATION"
r = post_req(URL + "departments/" + department_uuid + "/vdcs", {"Name": "Vadim-VDC_auto"})
vdc_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/server-farms", {"uuid":"b4b78ea1-1bef-4751-97d6-bcc21acbe860","name":"Cluster-1","min":1,"max":5,"initial":3,"user_data":"","volumes":[],"scale_option":"Disabled","dynamic_option":{"bandwidth":[60,80],"ram":[50,80],"cpu":[60,75]},"compute_service":"Compute-1","sequence_number":100,"ssh_keys":[]})
serverfarm_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + serverfarm_uuid + "/servers", {"boot_storage_type":"Ephemeral","name":"Server-1","weight":0,"hypervisor":"KVM","ephemeral_storage":10,"user_data":"","volumes":[],"memory":1024,"server_boot":{"boot_image":{"hierarchy":{"slice":"my23Slice","system":"System"},"library_name":"ImageLibrary-with-Tools","image_name":"aCentos-6-with-Tools"}},"cpu":["2","2048"],"sequence_number":100,"ssh_keys":[]})

r = post_req(URL + vdc_uuid + "/subnets", {"Name":"Subnet-2"})
subnet_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/external-network-services", {"interfaces":[{"subnet":"NAT-1","interface_type":"Default","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":0,"securityzone":"Untrusted"},"name":"NAT-1"}],"params":{"external_network":"public"},"name":"E1","sequence_number":100})
ext_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/nats", {"nat_static_address":"0.0.0.0","params":{"qos":"Default","default_gateway":"default","availability_option":"Default","max_instances_count":1,"begin_instances_count":1,"throughput":100,"throughputinc":100,"northbound":"E1"},"name":"NAT-1","nat_address_type":"dynamic","policy":{"sla_policy":"Default","sla":"Default"},"autoscale":{"ram_enabled":0,"compute_red":75,"ram_red":80,"compute_green":60,"ram_green":50,"throughput_green":60,"cooldown_remove":120,"cooldown_add":90,"compute_enabled":0,"throughput_red":80,"throughput_enabled":0},"interfaces":[{"subnet":"E1","interface_type":"north_bound","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":100,"securityzone":"Untrusted"},"name":"E1"},{"subnet":"Subnet-2","interface_type":"south_bound","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":100,"securityzone":"Untrusted"},"name":"Subnet-2"}],"pat_mode":"Disabled","sequence_number":100,"uuid":"b5467197-2a21-4ce6-9e66-99e6e1c06868"})
nat_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/compute-services", {"uuid":"402b8f94-81ed-431f-9fc6-303d4f19ae5e","params":{"qos":"Default","default_gateway":"default","availability_option":"Default","max_instances_count":1,"begin_instances_count":1,"throughput":500,"northbound":"Subnet-2"},"name":"Compute-1","serverfarm":["Cluster-1"],"policy":{"sla_policy":"Default","sla":"Default"},"interfaces":[{"subnet":"Subnet-2","interface_type":"Default","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":100,"securityzone":"Untrusted"},"name":"Subnet-2"}],"user_data":"","sequence_number":100,"ssh_keys":[]})
compute_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = put_req(URL + "server-farms/" + serverfarm_uuid, {"name":"Cluster-1","min":1,"max":5,"initial":3,"user_data":"","volumes":[],"scale_option":"Disabled","dynamic_option":{"bandwidth":[60,80],"ram":[50,80],"cpu":[60,75]},"compute_service":"Compute-1","sequence_number":100,"ssh_keys":[]})



print "CREATION/CONFIGURATION OF ENTITIES COMPLETE"

r = put_req(URL + "vdcs/" + vdc_uuid + "/actions", {"validate": "null"})
stri = ""
while stri != "Reserved":
    r = put_req(URL + "vdcs/" + vdc_uuid + "/actions", {"validate": "null"})
    stri = json.loads(r.text)["validation"]
    print "Validating: " + stri

print "RESERVING RESOURCES"
r = put_req(URL + "vdcs/" + vdc_uuid + "/actions", {"reserve-resources": "null"})
print "RESOURCES RESERVED"

print "PROV VDC: " + provision(URL + "vdcs/" + vdc_uuid)
print "PROV NAT: " + provision(URL + "nats/" + nat_uuid)
print "PROV EXT: " + provision(URL + "external-networks/" + ext_uuid)
print "PROV COMPUTE: " + provision(URL + "compute-services/" + compute_uuid)
print "PROV SUBNET: " + provision(URL + "subnets/" + subnet_uuid)

print "ACTIVATE VDC: " + activate(URL + "vdcs/" + vdc_uuid)

endtime = time.clock()
elapsedtime = endtime - starttime
print "COMPLETE ACTIVATION TOOK: " + str(elapsedtime) + " seconds."

# vdc_uuid = "1a01f8d8-6a02-4703-a6cd-6a9e888bae27" #TODO remove
# nat_uuid = "df871da7-1213-4f12-8071-c40d5278f375"
# ext_uuid = "aa6fc147-9f75-4f92-932b-7e17ba3e7791"
# compute_uuid = "cf5560f9-5a8d-48b1-947f-cd699d142db6"
# subnet_uuid = "789132ff-65f7-4538-8352-7905bfee6fa2"

raw_input()

# print "DEPROVISION VDC: " + deprovision(URL + "vdcs/" + vdc_uuid)
print "DESTROY VDC: " + destroy(URL + "vdcs/" + vdc_uuid)

# while True:
#     print "GET NAT: " + get_req(URL + "nats/" + nat_uuid).text
#     print "GET EXT: " + get_req(URL + "external-networks/" + ext_uuid).text
#     print "GET COMPUTE: " + get_req(URL + "compute-services/" + compute_uuid).text
#     print "GET SUBNET: " + get_req(URL + "subnets/" + subnet_uuid).text