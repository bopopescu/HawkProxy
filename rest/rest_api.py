#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4


import os
import sys
import syslogger as syslog
import logging
import gflags
import gettext
import eventlet
import yurl
import ujson
import requests

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

FLAGS = gflags.FLAGS
import utils.cloud_utils as cloud_utils
from utils.underscore import _

LOG = logging.getLogger('hawk-rpc')
gettext.install('cloudflow')

logging.getLogger('requests').setLevel(logging.WARNING)

# proxies = {
#  "http": "http://192.168.228.206:8888",
#  "https": "http://192.168.228.206:8888",
# }
#
# proxies = None

# proxies = {
#  "http": "http://localhost:8888",
#  "https": "http://localhost:8888",
# }


def get_rest(url, params=None, headers=None, timeout=60.0):
    try:
        if headers is None:
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        # LOG.debug(_("Get:%s with headers:%s  ") % (url, headers))
        response = requests.get(url, params=params, headers=headers, proxies=ujson.loads(FLAGS.rest_proxy),
                                timeout=timeout)
        # Check for HTTP codes other than 200
        if response.status_code != 200:
            LOG.critical(_("GET Response code:%s URL:%s " % (response.status_code, url)))
            return {"http_status_code": response.status_code}

            # Decode the JSON response into a dictionary and use the data
        #        return dict(response.json(), **{"http_status_code": response.status_code})
        return dict(ujson.loads(response.text), **{"http_status_code": response.status_code})
    except:
        cloud_utils.log_normal_exception(sys.exc_info())
        LOG.critical("Error in executing a GET  : %s" % url)
        # 500 is internal server error
        return {"http_status_code": 408}


def post_rest(url, payload, headers=None, timeout=60.0):
    try:
        if headers is None:
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        response = requests.post(url, data=ujson.dumps(payload), headers=headers, proxies=ujson.loads(FLAGS.rest_proxy),
                                 timeout=timeout)
        # Check for HTTP codes other than 200
        if response.status_code != 200 and response.status_code != 201:
            LOG.critical(_("POST Response code:%s URL:%s payload:%s" % (response.status_code, url, payload)))
            return {"http_status_code": response.status_code}
        if response.text:
            # Decode the JSON response into a dictionary and use the data
            return dict(ujson.loads(response.text),
                        **{"http_status_code": response.status_code, "response_headers": dict(response.headers)})
        else:
            return dict(**{"http_status_code": response.status_code, "response_headers": dict(response.headers)})
    except:
        cloud_utils.log_exception(sys.exc_info())
        LOG.critical("Error in executing a POST : %s" % url)
        # 500 is internal server error
        return {"http_status_code": 500}


def put_rest(url, payload, headers=None, timeout=60.0):
    try:
        if headers is None:
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        response = requests.put(url, data=ujson.dumps(payload), headers=headers, proxies=ujson.loads(FLAGS.rest_proxy),
                                timeout=timeout)
        # Check for HTTP codes other than 200
        if response.status_code != 200 and response.status_code != 204:
            LOG.critical(_("PUT Response code:%s URL:%s payload:%s" % (response.status_code, url, payload)))
            return {"http_status_code": response.status_code}

        if response.content:
            # Decode the JSON response into a dictionary and use the data
            return dict(ujson.loads(response.text), **{"http_status_code": response.status_code})
        else:
            return {"http_status_code": response.status_code}
    except:
        cloud_utils.log_exception(sys.exc_info())
        LOG.critical("Error in executing a PUT:%s payload:%s" % (url, payload))
        if 'resoponse' in vars() and response and response.content:
            LOG.critical("Error in executing a PUT: Response:%s " % (response.text))
        # 500 is internal server error
        return {"http_status_code": 500}


def patch_rest(url, payload, headers=None, timeout=60.0):
    try:
        if headers is None:
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        response = requests.patch(url, data=ujson.dumps(payload), headers=headers,
                                  proxies=ujson.loads(FLAGS.rest_proxy), timeout=timeout)
        # Check for HTTP codes other than 200
        if response.status_code != 200:
            LOG.critical(_("PUT Response code:%s URL:%s payload:%s" % (response.status_code, url, payload)))
            return {"http_status_code": response.status_code}

        # Decode the JSON response into a dictionary and use the data
        return dict(response.json(), **{"http_status_code": response.status_code})
    except:
        cloud_utils.log_exception(sys.exc_info())
        LOG.critical("Error in executing a PUT : %s" % url)
        # 500 is internal server error
        return {"http_status_code": 500}


def delete_rest(url, headers=None, timeout=60.0):
    try:
        if headers is None:
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        response = requests.delete(url, headers=headers, proxies=ujson.loads(FLAGS.rest_proxy), timeout=timeout)
        # Check for HTTP codes other than 200
        if response.status_code != 200 and response.status_code != 204:
            LOG.critical(_("Problem with the request - Response code: %s" % response.status_code))
        return {"http_status_code": response.status_code}
    except:
        cloud_utils.log_exception(sys.exc_info())
        LOG.critical("Error in executing a DELETE url:%s headers:%s" % (url, headers))
        # 500 is internal server error
        return {"http_status_code": 500}


def is_json(myjson):
    try:
        son_object = ujson.loads(myjson)
    except ValueError, e:
        return False
    return True
