#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time

print "calling RPC Server",
s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
# Print list of available methods
print s.system.listMethods()




# print "Create User Group....",
# ugdbid = 0
# sgrp = {"entitytype": "user_group", "name": "UserGroup",  "parententityid": 1}
# response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(sgrp)))
# if "dbid" in response:
#    ugdbid = response["dbid"]

# print response
for x in xrange(5):
    print "Create User....",
    uugdbid = 0
    sgrp = {"entitytype": "user", "name": "admin%s" % str(x),
            "parententityid": 2, "loginid": "admin%s" % str(x), "password": "admin%s" % str(x),
            "email": "a@b.com",
            "aclrole": "IT", "acl_dbids": [1]}

    response = json.loads(s.genericPhptoPy("entity", 0, "create", json.dumps(sgrp)))
    if "dbid" in response:
        uugdbid = response["dbid"]
    print response
