#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import xmlrpclib
import json
import sys
import time
import datetime
import eventlet

eventlet.monkey_patch()

from jsonrpclib.SimpleJSONRPCServer import SimpleJSONRPCServer

server = SimpleJSONRPCServer(('localhost', 8080))


def echo_rpc():
    return


server.register_function(echo_rpc)
server.register_function(pow)
server.register_function(lambda x, y: x + y, 'add')
server.register_function(lambda x: x, 'ping')
server.serve_forever()
