#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time

k1 = {"a": 1, "b": "2", "dict": "k1"}
k2 = {"a": 10, "b": "22", "dict1": "k2"}
kc = {}
kc.update(k1)
kc.update(k2)

s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
tap = {"entitytype": "storage_class", "parententityid": 1}
tapdbid = 0
response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(tap), 0))
if "dbid" in response:
    tapdbid = response["dbid"]
print "Create storage_class ....", response
sys.exit()
