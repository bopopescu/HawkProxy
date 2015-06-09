#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time
import datetime

import jsonrpclib

server = jsonrpclib.Server('http://localhost:8080')
retry = 1000
t1 = datetime.datetime.now()
for i in xrange(retry):
    server.echo_rpc()
t2 = datetime.datetime.now()

print "time delta is: %s.  Per RPC is:%s, Per second: %s" % (
    (t2 - t1), (t2 - t1) / retry, retry / (t2 - t1).total_seconds())
