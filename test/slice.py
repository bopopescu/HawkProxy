#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time


def create_vdc(id):
    print "Create VDC",
    response = json.loads(s.genericPhptoPy("vdc", 0, "create", json.dumps({"parententityid": id})))
    if "dbid" in response:
        dbid = response["dbid"]
    else:
        dbid = 0
    print response
    return dbid


def create_department(id):
    print "Create Deprtament",
    response = json.loads(s.genericPhptoPy("department", 0, "create", json.dumps({"parententityid": id})))
    if "dbid" in response:
        dbid = response["dbid"]
    else:
        dbid = 0
    print response
    return dbid


def create_organization():
    print "Create Organizaon",
    response = json.loads(s.genericPhptoPy("organization", 0, "create", json.dumps({})))
    if "dbid" in response:
        dbid = response["dbid"]
    else:
        dbid = 0
    print response
    return dbid


def delete_vdc(id):
    print "delete VDC",
    response = json.loads(s.genericPhptoPy("vdc", id, "delete", json.dumps({})))
    print response


def delete_department(id):
    print "delete Deprtament",
    response = json.loads(s.genericPhptoPy("department", id, "delete", json.dumps({})))
    print response


def delete_organization(id):
    print "delete Organizaon",
    response = json.loads(s.genericPhptoPy("organization", id, "delete", json.dumps({})))
    print response


if __name__ == '__main__':

    print "calling RPC Server",
    s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
    # Print list of available methods
    print s.system.listMethods()

    slice = {"name": "labSlice", "url": "http://cloudflow.dyndns.biz:8220",
             "description": "first slice @ http://cloudflow.dyndns.biz:8200"}
    for x in xrange(1, 5):
        sdbid = 0
        # Create Slice
        print "Create Slice",
        response = json.loads(s.genericPhptoPy("slice", 0, "create", json.dumps(slice)))
        if "dbid" in response:
            sdbid = response["dbid"]
        print response
        oid1 = create_organization()
        did1 = create_department(oid1)
        vid1 = create_vdc(did1)
        print "Delete Slice", s.genericPhptoPy("slice", sdbid, "delete", None)
        oid2 = create_organization()
        did2 = create_department(oid2)
        vid2 = create_vdc(did2)

        delete_vdc(vid1)
        delete_department(did1)
        delete_organization(oid1)

        delete_vdc(vid2)
        delete_department(did2)
        delete_organization(oid2)
