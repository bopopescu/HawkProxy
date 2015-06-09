#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import gflags

import time
import string
import threading
from dateutil.relativedelta import *

import urlparse

import eventlet
import eventlet.corolocal
from eventlet import event
from eventlet import wsgi
from eventlet import websocket
import datetime

eventlet.monkey_patch()

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

# import random
import multiprocessing

# import utils.gflags_collection
import utils.cloud_utils as cloud_utils
from utils.underscore import _
import utils.cache_utils as cache_utils

import ujson

LOG = logging.getLogger('web-socket')
FLAGS = gflags.FLAGS

import zmq
from random import randrange


def run_mq_socket():
    cloud_utils.create_logger("web-socket", FLAGS.log_directory + '/mq-client.log')

    # set up DB pool
    db = cloud_utils.CloudGlobalBase(LOG=LOG)
    db.close()

    #  Socket to talk to server
    context = zmq.Context()
    socket = context.socket(zmq.SUB)

    socket.connect("tcp://localhost:5556")

    # Subscribe to zipcode, default is NYC, 10001
    zip_filter = sys.argv[1] if len(sys.argv) > 1 else "10001"

    # Python 2 - ascii bytes to unicode str
    if isinstance(zip_filter, bytes):
        zip_filter = zip_filter.decode('ascii')
    socket.setsockopt_string(zmq.SUBSCRIBE, zip_filter)

    # Process 5 updates
    total_temp = 0
    for update_nbr in range(5):
        string = socket.recv_string()
        zipcode, temperature, relhumidity = string.split()
        total_temp += int(temperature)

        print("Average temperature for zipcode '%s' was %dF" % (zip_filter, total_temp / update_nbr))


if __name__ == "__main__":
    cloud_utils.setup_flags_logs('hawk-ws.log')
    run_mq_socket()
