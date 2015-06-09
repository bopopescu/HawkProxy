#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import gflags

gflags.DEFINE_string('cloudflow_connection', None, 'Cloudflow database connection string')
gflags.DEFINE_string('pid_directory', '/var/log/cloudflow', 'location of pid files')
gflags.DEFINE_string('log_directory', '/var/log/cloudflow', 'location of log files')
gflags.DEFINE_string('rest_proxy', '{}', 'proxy to be used - mostly for debugging')
gflags.DEFINE_string('db_tables_dict', None, 'Database tables dictionay as a string')
gflags.DEFINE_string('rpc_daemon', 'false', 'Run as daemon')
gflags.DEFINE_string('pycharm', 'True', 'running under pycharm')
