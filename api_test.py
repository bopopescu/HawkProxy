__author__ = 'vkoro_000'

import requests
import ujson as json

admin_token = "fd01bd1ad68847d1bed4b3127376a9cc"
osa_token = "255f300cc33646e7afed8c60bb8462d3"
dsa_token = "efac710ad3b646e28412d922d0a66263"
vdcuser_token = "e5bcd0fd498045ea9859dce16e2c37c6"

URL = "http://localhost:8091/v2/"

department_uuid = "ae5175ea-9194-4d7e-9e0b-595183d468e2"

head = {"X-Auth-Token": admin_token, "Content-Type": "application/json"}

def post_req(url, json):
    return requests.post(url, json=json, headers=head)
def put_req(url, json):
    return requests.put(url, json=json, headers=head)
def get_req(url):
    return requests.get(url, headers=head)

def provision(url):
    r = post_req(url + "/actions", {"provision": "null"})
    stat = ""
    while stat != "Provisioned":
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

def activate(url):
    r = post_req(url + "/actions", {"activate": "null"})
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


r = post_req(URL + "departments/" + department_uuid + "/vdcs", {"Name": "Vadim-VDC_auto"})
vdc_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/server-farms", {"uuid":"b4b78ea1-1bef-4751-97d6-bcc21acbe860","name":"Cluster-1","min":1,"max":5,"initial":3,"user_data":"","volumes":[],"scale_option":"Disabled","dynamic_option":{"bandwidth":[60,80],"ram":[50,80],"cpu":[60,75]},"compute_service":"Compute-1","sequence_number":100,"ssh_keys":[]})
serverfarm_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + serverfarm_uuid + "/servers", {"boot_storage_type":"Ephemeral","name":"Server-1","weight":0,"hypervisor":"KVM","ephemeral_storage":10,"user_data":"","volumes":[],"memory":1024,"server_boot":{"boot_image":{"hierarchy":{"slice":"my23Slice","system":"System"},"library_name":"ImageLibrary-with-Tools","image_name":"aCentos-6-with-Tools"}},"cpu":["2","2048"],"sequence_number":100,"ssh_keys":[]})

r = post_req(URL + vdc_uuid + "/subnets", {"Name":"Subnet-1"})
r = post_req(URL + vdc_uuid + "/subnets", {"Name":"Subnet-2"})

r = post_req(URL + vdc_uuid + "/external-network-services", {"interfaces":[{"subnet":"Subnet-1","interface_type":"Default","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":0,"securityzone":"Untrusted"},"name":"Subnet-1"}],"params":{"external_network":"public"},"name":"E1","sequence_number":100})
ext_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/nats", {"nat_static_address":"0.0.0.0","params":{"qos":"Default","default_gateway":"default","availability_option":"Default","max_instances_count":1,"begin_instances_count":1,"throughput":100,"throughputinc":100,"northbound":"E1"},"name":"NAT-1","nat_address_type":"dynamic","policy":{"sla_policy":"Default","sla":"Default"},"autoscale":{"ram_enabled":0,"compute_red":75,"ram_red":80,"compute_green":60,"ram_green":50,"throughput_green":60,"cooldown_remove":120,"cooldown_add":90,"compute_enabled":0,"throughput_red":80,"throughput_enabled":0},"interfaces":[{"subnet":"Subnet-1","interface_type":"north_bound","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":100,"securityzone":"Untrusted"},"name":"Subnet-1"},{"subnet":"Subnet-2","interface_type":"south_bound","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":100,"securityzone":"Untrusted"},"name":"Subnet-2"}],"pat_mode":"Disabled","sequence_number":100,"uuid":"b5467197-2a21-4ce6-9e66-99e6e1c06868"})
nat_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = post_req(URL + vdc_uuid + "/compute-services", {"uuid":"402b8f94-81ed-431f-9fc6-303d4f19ae5e","params":{"qos":"Default","default_gateway":"default","availability_option":"Default","max_instances_count":1,"begin_instances_count":1,"throughput":500,"northbound":"Subnet-2"},"name":"Compute-1","serverfarm":["Cluster-1"],"policy":{"sla_policy":"Default","sla":"Default"},"interfaces":[{"subnet":"Subnet-2","interface_type":"Default","params":{"guaranteed_iops":0,"qos":"Normal","mtu":1450,"maximum_bandwidth":0,"maximum_iops":0,"guaranteed_bandwidth":100,"securityzone":"Untrusted"},"name":"Subnet-2"}],"user_data":"","sequence_number":100,"ssh_keys":[]})
compute_uuid = json.loads(r.text)["HAWK-DB"]["UUID"]

r = put_req(URL + "server-farms/" + serverfarm_uuid, {"name":"Cluster-1","min":1,"max":5,"initial":3,"user_data":"","volumes":[],"scale_option":"Disabled","dynamic_option":{"bandwidth":[60,80],"ram":[50,80],"cpu":[60,75]},"compute_service":"Compute-1","sequence_number":100,"ssh_keys":[]})

# vdc_uuid = "52e262d0-bd49-47c5-8439-32249fb77d9a" #TODO remove
# nat_uuid = "e6b0deba-006f-4c14-a245-0c323a640d63"
# ext_uuid = "a8a6f5ee-3333-465a-ae70-7f3361ab2b26"
# compute_uuid = "4f41a82b-723a-4f54-a558-93437a928c0c"

r = post_req(URL + "vdcs/" + vdc_uuid + "/actions", {"validate": "null"})
str = ""
while str != "Reserved":
    r = post_req(URL + "vdcs/" + vdc_uuid + "/actions", {"validate": "null"})
    str = json.loads(r.text)["validation"]

r = post_req(URL + "vdcs/" + vdc_uuid + "/actions", {"reserve-resources": "null"})

print "PROV VDC: " + provision(URL + "vdcs/" + vdc_uuid)
print "PROV NAT: " + provision(URL + "nats/" + nat_uuid)
print "PROV EXT: " + provision(URL + "external-networks/" + ext_uuid)
print "PROV COMPUTE: " + provision(URL + "compute-services/" + compute_uuid)

print "ACTIVATE VDC: " + activate(URL + "vdcs/" + vdc_uuid)

#
# REM curl -s -S -i -X POST http://localhost:8091/v2/vdcs/%vdc_uuid%/actions -d "{\"activate\":\"null\"}" --header "X-Auth-Token: %admin_token%" --header "Content-Type: application/json"
#
# REM curl -s -S -i -X POST http://localhost:8091/v2/vdcs/5ac6ea76-fdee-4b7f-b91a-369ae1c07d83/actions -d "{\"deprovision\":\"null\"}" --header "X-Auth-Token: %admin_token%" --header "Content-Type: application/json"