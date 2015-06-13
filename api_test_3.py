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
    return requests.post(url, json=json, headers=head)
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

vdc_uuid = "bcb06c32-0ce6-4cda-8a3e-d0d35cce3870"

# print "DEPROVISION VDC: " + deprovision(URL + "vdcs/" + vdc_uuid)
print "DESTROY VDC: " + destroy(URL + "vdcs/" + vdc_uuid)

# while True:
#     print "GET NAT: " + get_req(URL + "nats/" + nat_uuid).text
#     print "GET EXT: " + get_req(URL + "external-networks/" + ext_uuid).text
#     print "GET COMPUTE: " + get_req(URL + "compute-services/" + compute_uuid).text
#     print "GET SUBNET: " + get_req(URL + "subnets/" + subnet_uuid).text