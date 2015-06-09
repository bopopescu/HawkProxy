#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from eventlet.green import zmq

from utils.underscore import _
import logging

LOG = logging.getLogger('hawk-rpc')

import time
import sys
import utils.cloud_utils as cloud_utils
import ujson
import threading

publisher = None
publisher_context = None


def setup_publisher():
    global publisher
    global publisher_context

    try:
        publisher_context = zmq.Context()
        publisher = publisher_context.socket(zmq.PUB)
        publisher.set(zmq.LINGER, 0)
        publisher.bind("tcp://127.0.0.1:5556")
        LOG.info(_("Publish: tcp://127.0.0.1:5556"))
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def end_publisher():
    global publisher
    global publisher_context
    try:
        publisher.close()
        publisher_context.term()
        LOG.info(_("Publish ended: tcp://127.0.0.1:5556"))
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


publish_lock = threading.RLock()


def publish(topic, python_object):
    global publisher
    try:
        LOG.info(_("Publish: %s:%s" % (topic, python_object)))
        with publish_lock:
            publisher.send_multipart([str(topic), ujson.dumps(python_object)])
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


if __name__ == '__main__':

    api = {"command": "status_update"}
    for x in xrange(1000):
        publish("2345", ujson.dumps(api))
        time.sleep(1)
    print "done"
