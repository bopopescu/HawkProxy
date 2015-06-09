#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time

print "calling RPC Server",
s = xmlrpclib.ServerProxy('http://0.0.0.0:8000', allow_none=True)
# Print list of available methods
print s.system.listMethods()
