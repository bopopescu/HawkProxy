#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import gflags
import gettext
import time
import eventlet
# import traceback
import json
import syslog
import string
import threading

from signal import SIGTERM
# from time import sleep
import datetime
import yurl

currentDir = os.path.dirname(os.path.abspath(__file__))

# if os.path.abspath('%s/../dist_packages' % currentDir) not in sys.path:
#    sys.path.insert(0,os.path.abspath('%s/../dist_packages' % currentDir))

# if os.path.abspath('%s/..' % currentDir) not in sys.path:
#    sys.path.insert(0,os.path.abspath('%s/..' % currentDir))

sys.path.insert(0, os.path.abspath('%s/..' % currentDir))
# sys.path.insert(0,os.path.abspath('%s/../dist_packages' % currentDir))

# import eventlet.debug
# eventlet.debug.hub_prevent_multiple_readers(False)


# import utils.gflags_collection
from utils.daemon import Daemon
import utils.cloud_utils as cloud_utils
# import utils.uuid_utils as uuid_utils



# import entity.validate_entity as validate
# import entity.provision_entity as provision
import entity.entity_commands as entity_commands
import entity.entity_functions as entity_functions

# import entity.entity_manager as entity_manager



import entity.rpcResync

import web_app.rpcWebSocket

import cfd_keystone.cfd_keystone

from utils.underscore import _

import utils.cache_utils as cache_utils

import multiprocessing

eventlet.monkey_patch()

FLAGS = gflags.FLAGS
LOG = logging.getLogger('hawk-rpc')
gettext.install('cloudflow')

import utils.publish_utils

hawk_current_version = ""

import SocketServer
from SimpleXMLRPCServer import SimpleXMLRPCServer
from SimpleXMLRPCServer import SimpleXMLRPCRequestHandler

import BaseHTTPServer


def not_insane_address_string(self):
    host, port = self.client_address[:2]
    return '%s (no getfqdn)' % host  # used to call: socket.getfqdn(host)


BaseHTTPServer.BaseHTTPRequestHandler.address_string = not_insane_address_string

bg_lock = threading.Lock()


class AsyncXMLRPCServer(SocketServer.ThreadingMixIn, SimpleXMLRPCServer): pass


# Restrict to a particular path.
class RequestHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ('/RPC2',)


class LogRequestHandler(SimpleXMLRPCRequestHandler):
    """Overides the default SimpleXMLRPCRequestHander to support logging.  Logs
    client IP and the XML request and response.
    """

    def do_POST(self):
        clientIP, port = self.client_address
        # Log client IP and Port
        LOG.info(_('Client IP: %s - Port: %s' % (clientIP, port)))
        try:
            # get arguments
            data = self.rfile.read(int(self.headers["content-length"]))
            # Log client request
            LOG.info(_('Client request: \n%s\n' % data))

            response = self.server._marshaled_dispatch(
                data, getattr(self, '_dispatch', None)
            )
            # Log server response
            LOG.info(_('Server response: \n%s\n' % response))

        except:  # This should only happen if the module is buggy
            # internal error, report as HTTP server error
            self.send_response(500)
            self.end_headers()
        else:
            # got a valid XML RPC response
            self.send_response(200)
            self.send_header("Content-type", "text/xml")
            self.send_header("Content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

            # shut down the connection
            self.wfile.flush()
            self.connection.shutdown(1)


class RPCDaemon(Daemon):
    def __init__(self, *args, **kwargs):
        super(RPCDaemon, self).__init__(*args, **kwargs)

    def run(self):
        syslog.syslog("Hawk Server is activated")
        start_hawk_server()
        try:
            LOG.info(_("RPC daemon has started"))
        except Exception:
            cloud_utils.log_exception(sys.exc_info())
        LOG.info(_("RPC daemon has ended"))
        self.exit()


def genericPhptoPy(entity, dbid, function, json_options, user_id):
    db = None
    try:
        #        with bg_lock:
        if not user_id:
            user_id = 0
        db = cloud_utils.CloudGlobalBase(log=False)
        options = {}
        if json_options is not None:
            try:
                o = json.loads(json_options)
                if o and isinstance(o, dict):
                    options = dict(zip(map(string.lower, o.keys()), o.values()))
                elif o:
                    options = {}
                    LOG.warn(_("genericCtoPy invalid options format: entity=%s id=%s function=%s options=%s" % (
                        entity, dbid, function, json_options)))
            except:
                cloud_utils.log_exception(sys.exc_info())
                return

        LOG.info(_("genericCtoPy entity=%s id=%s function=%s options=%s" % (entity, dbid, function, json_options)))
        id = cloud_utils.insert_db(db, "tblAPILogs",
                                   {"entity": entity, "dbid": dbid, "function": function, "options": json_options,
                                    "user_id": user_id})
        if entity != "extend_log_time":
            if user_id != 0:
                #            user_row = cache_utils.get_cache("userid-%s" % user_id, "db.get_row(\"tblEntities\", \"id='%s' AND deleted = 0\")" % user_id, db_in=db)
                options["user_row"] = cache_utils.get_cache("db|tblEntities|id|%s" % user_id, None, db_in=db)
            response = entity_commands.rpc_functions(db, entity, dbid, function, options)
        else:
            response = json.dumps({"result_code": 0, "result_message": "success", "dbid": 0})
        db.execute_db(
            "UPDATE tblAPILogs SET elapsed_time=TIME_TO_SEC(TIMEDIFF(now(), created_at)), response='%s'  WHERE id = '%s' " % (
                response, id))

        #        return response
        if user_id != 0:
            db.execute_db(
                "UPDATE tblUsers SET TokenExpiresAt=DATE_ADD(TokenExpiresAt, INTERVAL 30 MINUTE)  "
                "WHERE tblEntities = '%s'  and TIMESTAMPDIFF(MINUTE,now(),TokenExpiresAt) < 15   " % user_id)
        LOG.info(_("genericCtoPy entity=%s id=%s function=%s response=%s" % (entity, dbid, function, response)))
        return response
    except:
        cloud_utils.log_exception(sys.exc_info())
    finally:
        if db:
            db.close()


def echo_rpc():
    return


def timeout_rpc():
    time.sleep(200)


def rpc_server():
    #    server = AsyncXMLRPCServer(("0.0.0.0", 8000),
    #                               requestHandler=LogRequestHandler, allow_none=True, logRequests=True)

    server = AsyncXMLRPCServer(("0.0.0.0", 8000), allow_none=True, logRequests=False)
    server.register_introspection_functions()
    server.register_function(genericPhptoPy)
    server.register_function(echo_rpc)
    server.register_function(timeout_rpc)

    #    server.register_instance(compute_server.ComputeVDC(db, vdcid, nova))
    # Run the server's main loop
    LOG.info(_("RPC Server is ready"))
    server.serve_forever()


def slice_resync():
    while True:
        try:
            LOG.info(_("Start background syste, resync physical resources"))
            while True:
                t1 = datetime.datetime.now()
                db = cloud_utils.CloudGlobalBase(log=False)
                eve = entity_functions.SystemFunctions(db)
                eve.do(db, "initialize")
                db.close(log=None)
                print "System resynced in : %s seconds" % (datetime.datetime.now() - t1)
                LOG.info(_("System resynced in : %s seconds" % (datetime.datetime.now() - t1)))
                time.sleep(1 * 60 * 60)
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


import resource

import traceback


def active_threads():
    try:
        LOG.info(_("Start background monitor to check on active threads"))
        while True:
            try:
                cloud_utils.bash_command("free -lm")
                print "Memory usage: %s (kb) at:%s" % (
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, datetime.datetime.now())
                LOG.info(_("Memory usage: %s (kb" % resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
                #            LOG.info(_("mem_top: %s " % mem_tests.mem_top()))
                LOG.info(_(">>>>>>Active Thread Count is %s" % threading.activeCount()))
                for t in threading.enumerate():
                    LOG.info(_("Active thread is %s with id %s" % (t.name, t.ident)))
                    #                id2name = dict((th.ident, th.name) for th in threading.enumerate())
                    #                for threadId, stack in sys._current_frames().items():
                    #                    if threadId in id2name:
                    #                        print "id: %s name:%s" %(threadId,id2name[threadId])
                    #                    else:
                    #                        print "id: %s " %(threadId)
                    #                    traceback.print_stack(f=stack)
            except:
                cloud_utils.log_exception(sys.exc_info())
            finally:
                time.sleep(300)
    except:
        cloud_utils.log_exception(sys.exc_info())
        return None


def cache_thread():
    cache_utils.cache_manager(LOG=LOG)


threads = [rpc_server,
           slice_resync,
           active_threads,
           cache_thread
           ]


def start_hawk_server():
    if FLAGS.pycharm == "False":
        n = multiprocessing.Process(name='web_socket', target=web_app.rpcWebSocket.run_web_socket)
        n.daemon = True
        n.start()
        time.sleep(0.01)

        n = multiprocessing.Process(name='vdc_status', target=entity.rpcResync.run_vdc_status)
        n.daemon = True
        n.start()
        time.sleep(0.01)
    else:
        LOG.warn(_("Running under pycharm -- not running web_socket as a process"))

    rpc_thread_manager()


def rpc_thread_manager():
    utils.publish_utils.setup_publisher()
    syslog.syslog("rpc thread manager is running")
    db = cloud_utils.CloudGlobalBase()
    timezone = db.execute_db("select @@global.time_zone;")

    if timezone[0]["@@global.time_zone"] != "+00:00":
        max = db.execute_db("SET GLOBAL time_zone = '+00:00'")

    system_dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                               {"name": "System", "description": "Root system entity",
                                                "entitytype": "system", "parententityid": 0, "entitystatus": "Ready"},
                                               {"entitytype": "system"}, child_table="tblSystem")

    cfd_keystone.cfd_keystone.system_initialization(db)
    db.close()

    instances = []
    for t in threads:
        instances.append(cloud_utils.RunForEverThread(target=t, name=t.func_name, LOG=LOG))
    for t in instances:
        t.start()
    for t in instances:
        t.join()


if __name__ == '__main__':
    try:
        syslog.syslog("%s at Pid %s is started" % (os.path.basename(__file__), os.getpid()))
        cloud_utils.kill_priors(os.path.basename(__file__))
        cloud_utils.bash_command_no_exception("mkdir -p  /var/log/cloudflow")
        cloud_utils.bash_command_no_exception("mkdir -p /var/log/cloudflow/previous")
        cloud_utils.bash_command_no_exception("chown root:keystone /var/log/cloudflow")
        cloud_utils.bash_command_no_exception("chmod 0775 /var/log/cloudflow")
        #        cloud_utils.bash_command_no_exception("logrotate -f /etc/logrotate.d/cloudflow")
        cloud_utils.bash_command_no_exception("service ntp stop;ntpdate ntp.ubuntu.com")
        syslog.syslog("rpcServer at Pid %s  - all previous service instances removed" % os.getpid())
        hawk_current_version = cloud_utils.get_hawk_version()
        print "Starting Hawk Service -Version: %s - with initial pid %s" % (hawk_current_version, os.getpid())
        cloud_utils.setup_flags_logs('hawk-rpc.log')
        LOG.info(_("Starting Hawk Service -Version: %s - with initial pid %s" % (hawk_current_version, os.getpid())))

        cloud_utils.bash_command_no_exception("chown www-data:root /etc/cloudflow")
        cloud_utils.bash_command_no_exception("chown www-data:root /etc/cloudflow/secret.key")
        while True:
            try:
                rpc_thread_manager()
            except:
                syslog.syslog("rpcServer at Pid %s is being restarted " % os.getpid())
                cloud_utils.sys_log_exception(sys.exc_info())
            time.sleep(5)

    except:
        syslog.syslog("rpcServer at Pid %s is aborted" % os.getpid())
        cloud_utils.sys_log_exception(sys.exc_info())
    sys.exit()

    '''
        pidfile = FLAGS.pid_directory + "/RPCFuncs.pid"
        pidMon  = FLAGS.pid_directory + "/RPCFuncsMon.pid"
        try:
            kill_old_process(pidMon)
            kill_old_process(pidfile)
        except:
            pass

        if FLAGS.rpc_daemon == "true":
            daemon = RPCDaemon(pidfile, monitorPidFile=pidMon)
            daemon.start()
        else:
            # write pidfile
            pid = str(os.getpid())
            try:
                file(FLAGS.pid_directory + pidfile, 'w+').write("%s\n" % pid)
            except IOError:
                syslog.syslog("Unable to create pid file %s" % (FLAGS.pid_directory + pidfile))
            start_hawk_server()
    '''
