#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import socket
import MySQLdb
import traceback
import cStringIO
import logging
import gflags

import datetime
from dateutil import tz
import string

import eventlet

import logging.handlers
import time
from utils.underscore import _
import uuid

import eventlet.corolocal
import eventlet.db_pool

import threading
import yurl

eventlet.monkey_patch()

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

LOG = logging.getLogger()
FLAGS = gflags.FLAGS

import utils.uuid_utils as uuid_utils
import utils.cache_utils
import subprocess


class RunForEverThread(threading.Thread):
    ''' Runs the thread forever - restarts if there is an exception in either run or join method '''

    def __init__(self, *arg, **kwargs):
        if "LOG" in kwargs:
            self.log = kwargs["LOG"]
            del kwargs["LOG"]
        else:
            self.log = LOG
        super(RunForEverThread, self).__init__(*arg, **kwargs)

    def run(self, *arg, **kwargs):
        while True:
            try:
                super(RunForEverThread, self).run(*arg, **kwargs)
            except:
                log_exception(sys.exc_info(), LOG=self.log)
                self.log.info(_("Exception in  %s" % self._Thread__name))
            self.log.info(_("Restarting %s" % self._Thread__name))
            time.sleep(15)

    def join(self, *arg, **kwargs):
        while True:
            try:
                super(RunForEverThread, self).join(*arg, **kwargs)
            except:
                log_exception(sys.exc_info(), LOG=self.log)
                self.log.info(_("Join - Exception in  %s" % self._Thread__name))
            self.log.info(_("Restarting join %s" % self._Thread__name))
            while True:
                time.sleep(15)
                if self.isAlive():
                    break
                self.log.info(_("Waiting to join %s" % self._Thread__name))


def svnversion(path):
    p = subprocess.Popen("svnversion %s" % path, shell=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = p.communicate()
    return stdout


def get_hawk_base():
    current = currentDir
    dirname = []
    while True:
        dirname = os.path.split(current)
        if dirname[1] == "hawk":
            break
        if dirname[1] == "":
            break
        current = os.path.dirname(current)
    return current


def get_hawk_version():
    version = utils.cache_utils.get_localCache("hawk_version")
    if version:
        return version
    hawk_python_version = svnversion(currentDir).rstrip()
    hawk_php_version = svnversion(get_hawk_base() + "/php_hawk").rstrip()
    version = '1.1.0b1.dev%s.dev%s' % (hawk_python_version, hawk_php_version)
    utils.cache_utils.set_localCache("hawk_version", version)
    return version


import random
import hashlib


def get_random_string(length):
    """Get a random hex string of the specified length.

    based on Cinder library
      cinder/transfer/api.py
    """
    rndstr = ""
    random.seed(datetime.datetime.now().microsecond)
    while len(rndstr) < length:
        rndstr += hashlib.sha224(str(random.random())).hexdigest()
    return rndstr[0:length]


def bash_command(command, exception=False):
    LOG.debug(_("executing bash command:%s "), command)
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
        LOG.debug(_("bash response is:\n%s "), output)
    except subprocess.CalledProcessError as e:
        log_exception(sys.exc_info())
        LOG.critical("Last bash Command failed Output:%s Return code:%d" % (e.output, e.returncode))
        if exception:
            raise
        return e.returncode
    except:
        if exception:
            raise
        return
    return output


def bash_command_no_exception(command):
    syslog.syslog("Execute Bash: %s" % command)
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        sys_log_exception(sys.exc_info())
        return e.returncode
    except:
        return
    return output


def generate_uuid():
    return str(uuid.uuid4())


def isfloat(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def islong(value):
    try:
        long(value)
        return True
    except ValueError:
        return False


def strip_suffix(s, suf):
    if s.endswith(suf):
        return s[:-len(suf)]
    return s


def to_lower(d):
    if d:
        return dict((k.lower(), v) for k, v in d.iteritems())


def lower_key(in_dict, remove_none=False):
    if type(in_dict) is dict:
        out_dict = {}
        for key, item in in_dict.items():
            if remove_none and item is None:
                continue
            out_dict[key.lower()] = lower_key(item)
        return out_dict
    elif type(in_dict) is list:
        return [lower_key(obj) for obj in in_dict]
    else:
        return in_dict


def insert_db(db, primary_table, primary_dic, child_table=None, child_dic=None, LOG=LOG):
    dbid = _insert_db(db, primary_table, primary_dic, LOG=LOG)
    if not dbid:
        LOG.critical("Unable to insert into db:  table:%s dict:%s" % (primary_table, primary_dic))
        print "Unable to insert into db:  table:%s dict:%s" % (primary_table, primary_dic)
        return 0
    if child_table is None or primary_dic is None:
        return dbid
    if child_dic is None:
        child_dic = {}
    child_dic[primary_table.lower()] = dbid
    for key, value in primary_dic.iteritems():
        if key not in child_dic.keys():
            child_dic[key] = value
    cdbid = _insert_db(db, child_table, child_dic, LOG=LOG)
    return dbid


escape_keys = ["user_data", "rest_response", "description", "fault_details", "fault_message"]


def _insert_db(db, table, dic, LOG=LOG):
    try:
        if not dic:
            return
        columns = FLAGS.db_tables_dict[table]
        #        LOG.info("Inserting a row in %s with %s" % (table, dic))
        #        LOG.info("Table column names are %s" % columns)
        dic_lower = dict(zip(map(string.lower, dic.keys()), dic.values()))
        common = {}
        for column in columns:
            if column in dic_lower:
                if column in escape_keys:
                    common[column] = db.escape_string(dic_lower[column])
                else:
                    common[column] = dic_lower[column]

        if "uniqueid" in columns and "uniqueid" not in common:
            if "uuid" in common:
                common["uniqueid"] = common["uuid"]
            else:
                common["uniqueid"] = uuid_utils.generate_uuid()

                #        if "description" in common:
                #            common["description"] = db.escape_string(common["description"])

                #        if "user_data" in common:
                #            common["user_data"] = db.escape_string(common["user_data"])

                #        if "rest_response" in common:
                #            common["rest_response"] = db.escape_string(common["rest_response"])

        if "sortsequenceid" in columns and \
                        "sortsequenceid" not in dic_lower and \
                        "parententityid" in columns and \
                        "parententityid" in dic_lower and \
                        "entitytype" in columns and \
                        "entitytype" in dic_lower:

            vals = db.execute_db("SELECT MAX(sortsequenceid) as max FROM %s WHERE (entitytype ='%s' "
                                 "AND parententityid = '%s')" %
                                 (table, dic_lower["entitytype"], dic_lower["parententityid"]))

            if vals and vals[0]["max"]:
                common["sortsequenceid"] = vals[0]["max"] + 100
            else:
                common["sortsequenceid"] = 100
        else:
            pass

        common.pop("updated_at", None)
        common.pop("id", None)

        row_keys = []
        row_values = []
        for k, v in common.items():
            row_keys.append(k)
            if isinstance(v, unicode):
                v = v.replace('~', ' ')
            row_values.append(v)
        keys = ' ,'.join(tuple(row_keys))
        # the following conversions were done just to to get rid of "L" at the end of
        # long integers.
        valuesj = '~'.join(map(str, row_values))
        values = tuple(n for n in valuesj.split('~'))
        fvalues = ",".join(("'%s'" % n) for n in values)

        if "updated_at" in FLAGS.db_tables_dict[table]:
            msg = "INSERT INTO %s  (%s, updated_at) VALUES (%s,now()) " % (table, keys, fvalues)
        else:
            msg = "INSERT INTO %s  (%s) VALUES (%s) " % (table, keys, fvalues)

        print msg
        id = db.update_db_insert(msg)
        return id
    except:
        log_exception(sys.exc_info())
        print sys.exc_info()


def update_db_row(db, table, row, update_dict):
    try:
        if row is None:
            return
        if not update_dict:
            return row['id']
        row = dict(zip(map(string.lower, row.keys()), row.values()))

        if table == "tblEntities" and "uuid" in update_dict and \
                        "entitytype" in row and \
                (row["entitytype"] == "volume" or row["entitytype"] == "image"):
            update_dict["uniqueid"] = update_dict["uuid"]
            #    print "UPdate dict is %s" % update_dict
            #    print "row dict is %s" % row
        new_dict = {}
        for k, v in update_dict.items():
            #        print k, v
            if k.lower() in row:
                #            print k
                if isinstance(v, (long, int, float)) or isinstance(v, basestring):
                    if k in escape_keys:
                        new_dict[k] = db.escape_string(v)
                    else:
                        new_dict[k] = v
                        #            else:
                        #                print "Skipping.KV...", k, v
                        #    print "new dictuionary is %s" % new_dict
        msg = "UPDATE %s SET " % table
        if "updated_at" in FLAGS.db_tables_dict[table]:
            msg += "updated_at = now(), "

        # if "description" in new_dict:
        #            new_dict["description"] = db.escape_string(new_dict["description"])

        #        if "user_data" in new_dict:
        #            new_dict["user_data"] = db.escape_string(new_dict["user_data"])
        #
        #        if "rest_response" in new_dict:
        #            new_dict["rest_response"] = db.escape_string(new_dict["rest_response"])

        if "url" in new_dict:
            LOG.warn(_("url getting update"))

        for k, v in new_dict.items():
            msg += "%s = '%s', " % (k, v)
        msg = msg.rstrip(", ")

        msg += " WHERE id = '%s'" % row['id']
        #    print "----------DB UPDATE %s" % msg
        print msg
        db.update_db(msg)
        return row['id']
    except:
        log_exception(sys.exc_info())


def update_only(db, primary_table, primary_dic, where_dict, child_table=None, child_dic=None, LOG=LOG):
    if where_dict:
        primary_row = db.get_row_dict(primary_table, where_dict, order="ORDER BY id LIMIT 1")
        if primary_row:
            return update_or_insert(db, primary_table, primary_dic, where_dict, child_table, child_dic, primary_row,
                                    LOG=LOG)
        else:
            LOG.critical("primary row in %s table with %s is not present" % (primary_table, where_dict))
    else:
        LOG.critical("No where parameters for primary row in %s table" % primary_table)


#
#   Add or update a new row.  If a row exists that matches the "where_dict", update the row and its child row
#   if not, create a new row along with one in child table.
#


def update_or_insert(db, primary_table, primary_dic, where_dict, child_table=None, child_dic=None, primary_row=None,
                     LOG=LOG):
    try:
        child_row = None
        if not primary_row:
            if where_dict:
                primary_row = db.get_row_dict(primary_table, where_dict, order="ORDER BY id LIMIT 1")
                # print primary_row
            else:
                primary_row = None

        if primary_row is not None and child_table is not None:
            child_row = db.get_row_dict(child_table, {primary_table: primary_row["id"]}, order="ORDER BY id LIMIT 1")
            if child_row is None:
                # print "No child row found for %s for primary row %s" % (child_table, primary_table)
                LOG.critical("No child row in %s for primary row in %s - Parent deleted" % (child_table, primary_table))
                db.delete_rows_dict(primary_table, {"id": primary_row["id"]})
                primary_row = None
                # else:
                #     print "primary and child rows found!"
        if primary_row is None or primary_dic is None:
            # print "primary row not found"
            # print "primary table is %s and where claus is %s" % (primary_table, where_dict)
            # print primary_dic
            # print child_table
            return insert_db(db, primary_table, primary_dic, child_table, child_dic, LOG=LOG)
        else:
            # print "primary row found"
            update_db_row(db, primary_table, primary_row, primary_dic)
            if child_table is not None:
                if child_dic is None:
                    child_dic = {}
                child_dic[primary_table] = primary_row["id"]
                for key, value in primary_dic.iteritems():
                    if key != "id" and key not in child_dic.keys():
                        child_dic[key] = value
                update_db_row(db, child_table, child_row, child_dic)
            return primary_row['id']
    except:
        print sys.exc_info()
        log_exception(sys.exc_info())


def entity_deletion(db, table, delete_time):
    current_index = 0
    while True:
        row = db.get_row(table, "deleted = 1 AND deleted_at < '%s' AND id > '%s'" %
                         (delete_time, current_index), order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            yield lower_key(row)
        else:
            break


def log_message(db, dbid, msg, created_at=None, source="Hawk", type="Info"):
    print "ERROR: " + str(msg)
    if not created_at:
        created_at = mysql_now()

    db.execute_db("INSERT INTO tblLogs (tblentities, parententityid, created_at, field, unique_id, message, source)"
                  " VALUES ('%s', '%s', '%s', '%s', '%s','%s', '%s') " %
                  (dbid, dbid, created_at, type, datetime.datetime.utcnow().microsecond, msg, source))

    return

    msg = {"tblEntities": dbid, "ParentEntityId": dbid, "Message": msg, "field": type,
           "unique_id": datetime.datetime.utcnow().microsecond}
    if source:
        msg["source"] = source
    if created_at:
        msg["created_at"] = created_at
    else:
        msg["created_at"] = mysql_now()
    update_or_insert(db, "tblLogs", msg, None)


'''
def user_log(db, dbid, msg, created_at=None, source="Hawk", type="Info"):
    try:
        msg = {"tblEntities": dbid, "ParentEntityId": dbid,"Message": msg, "field":type}
        if source:
            msg["source"] = source
        if created_at:
            msg["created_at"] = created_at
        else:
            msg["created_at"] = mysql_now()
        update_or_insert(db, "tblLogs", msg,   None)
    except:
        log_exception(sys.exc_info())
'''


def get_network_interface_count(db, dbid):
    count = db.execute_db("SELECT COUNT(*)"
                          " FROM tblEntities JOIN tblServicesInterfaces "
                          "WHERE  (tblEntities.EntityType = 'network_interface' AND tblEntities.deleted=0 AND "
                          "tblServicesInterfaces.tblEntities = tblEntities.id AND "
                          " (tblServicesInterfaces.BeginServiceEntityId = '%s' OR "
                          "tblServicesInterfaces.EndServiceEntityId = '%s'))" % (dbid, dbid))
    return count[0].values()[0]


def network_service_interfaces(db, dbid):
    try:
        current_index = 0
        while True:
            row = db.execute_db("SELECT tblEntities.*, tblServicesInterfaces.* "
                                " FROM tblEntities JOIN tblServicesInterfaces "
                                "WHERE  (tblEntities.id > '%s' AND tblEntities.deleted=0 AND "
                                "tblEntities.EntityType = 'network_interface' AND "
                                "tblServicesInterfaces.tblEntities = tblEntities.id AND "
                                " (tblServicesInterfaces.BeginServiceEntityId = '%s' OR "
                                "tblServicesInterfaces.EndServiceEntityId = '%s')"
                                ") "
                                " ORDER BY tblEntities.id LIMIT 1" % (current_index, dbid, dbid))

            if not row:
                break
            row = row[0]
            crow = db.get_row("tblServicePorts",
                              "DestinationServiceEntityId = '%s' AND ServiceInterfaceEntityId = '%s' AND InterfacePortIndex = '%s'"
                              % (dbid, row['tblEntities'], row["InterfaceIndex"]),
                              order="ORDER BY id LIMIT 1")
            if not crow:
                break
            current_index = row['tblEntities']
            row.update({"tblServicePorts": lower_key(crow)})
            yield lower_key(row)

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        log_exception(sys.exc_info())


def network_service_ports(db, dbid):
    try:
        current_index = 0
        while True:
            row = db.execute_db("SELECT * FROM tblEntities JOIN tblServicePorts "
                                " WHERE  (tblEntities.id > '%s' AND "
                                " tblEntities.EntityType = 'service_port' AND tblEntities.deleted=0 AND "
                                " tblServicePorts.tblEntities = tblEntities.id AND tblEntities.ParentEntityId = '%s')"
                                " ORDER BY tblEntities.id LIMIT 1" % (current_index, dbid))

            if not row:
                break
            row = row[0]
            if "id" in row:
                row["child_id"] = row["id"]
            row["id"] = row['tblEntities']
            current_index = row['tblEntities']
            yield lower_key(row)

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        log_exception(sys.exc_info())


def get_entity(db, entitytype, child_table=None):
    """Given entitty type and child's entity type, returnn one child at a time.
    """
    current_index = 0
    while True:
        row = db.get_row("tblEntities", "EntityType = '%s' AND deleted=0 AND id > '%s'"
                         % (entitytype, current_index),
                         order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            if child_table:
                crow = db.get_row(child_table, "tblEntities='%s' " % row['id'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["child_id"] = crow.pop("id")
                row.update(crow)
            yield lower_key(row)
        else:
            break


def get_generic(db, table, column, value, child_table=None):
    current_index = 0
    if table == "tblEntities":
        add_str = "and deleted = 0"
    else:
        add_str = ""
    while True:
        row = db.get_row(table, "%s = '%s' AND id > '%s' %s " % (column, value, current_index, add_str),
                         order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            if child_table:
                crow = db.get_row(child_table, "tblEntities='%s' " % row['id'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["child_id"] = crow.pop("id")
                row.update(crow)
            yield lower_key(row)
        else:
            break


def get_generic_search(db, table, search_string, child_table=None):
    current_index = 0
    while True:
        row = db.get_row(table, " %s AND id > '%s' and deleted = 0" % (search_string, current_index),
                         order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            if child_table:
                crow = db.get_row(child_table, "tblEntities='%s' " % row['id'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["child_id"] = crow.pop("id")
                row.update(crow)
            yield lower_key(row)
        else:
            break


def entity_members(db, dbid, entitytype, child_table=None):
    """Given parent's entitty type and child's entity type, returnn one child at a time.
    """
    current_index = 0
    while True:
        row = db.get_row("tblEntities", "EntityType = '%s' AND deleted=0 AND ParentEntityId = '%s' AND id > '%s'"
                         % (entitytype, dbid, current_index),
                         order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            if child_table:
                crow = db.get_row(child_table, "tblEntities='%s' " % row['id'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["child_id"] = crow.pop("id")
                row.update(crow)
            yield lower_key(row)
        else:
            break


def cached_entity_members(db, dbid, entitytype, child_table=None):
    """Given parent's entitty type and child's entity type, returnn one child at a time.
    """
    current_index = 0
    while True:
        #        row = cache_utils.get_cache("db-tblEntities-EntityType-%s-ParentEntityId-%s-id-%s" % (entitytype,dbid), db_in=db)
        row = db.get_row("tblEntities", "EntityType = '%s' AND deleted=0 AND ParentEntityId = '%s' AND id > '%s'"
                         % (entitytype, dbid, current_index),
                         order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            if child_table:
                crow = db.get_row(child_table, "tblEntities='%s' " % row['id'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["child_id"] = crow.pop("id")
                row.update(crow)
            yield lower_key(row)
        else:
            break


def entity_children(db, dbid, entitytype=None, child_table=None):
    """Given parent's dbid and child's entity type, retrun one child at a time.
    :returns: A row of child
    """
    try:
        current_index = 0
        etype = ""
        if entitytype:
            etype = " AND EntityType = '%s' " % entitytype
        while True:
            row = db.get_row("tblEntities", "ParentEntityId='%s' AND deleted=0 %s AND id > '%s'"
                             % (dbid, etype, current_index),
                             order="ORDER BY id LIMIT 1")
            if row:
                current_index = row['id']
                if child_table:
                    crow = db.get_row(child_table, "tblEntities='%s' " % row['id'], order="ORDER BY id LIMIT 1")
                    if "id" in crow:
                        crow["child_id"] = crow.pop("id")
                    row.update(crow)
                yield lower_key(row)
            else:
                break

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        log_exception(sys.exc_info())


def entity_attach(db, dbid, entitytype=None):
    """Given parent's dbid and child's entity type, retrun one child at a time.
    :returns: A row of child
    """
    try:
        current_index = 0
        etype = ""
        if entitytype:
            etype = " AND tblAttachedEntities.AttachedEntityType = '%s' " % entitytype
        order = "ORDER BY tblAttachedEntities.AttachedSortSequenceId, tblAttachedEntities.id"

        rows = db.execute_db("SELECT tblEntities.*, tblAttachedEntities.id AS aid"
                             " FROM tblEntities JOIN tblAttachedEntities "
                             "WHERE  (tblAttachedEntities.tblEntities = '%s' AND "
                             "tblAttachedEntities.AttachedEntityId = tblEntities.id "
                             " %s ) "
                             " %s " % (dbid, etype, order))
        if rows:
            for row in rows:
                crow = db.get_row("tblAttachedEntities", "id='%s' " % row['aid'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["attach_id"] = crow.pop("id")
                crow.update(row)
                yield lower_key(crow)
    except:
        log_exception(sys.exc_info())


def entity_attach_old(db, dbid, entitytype=None):
    """Given parent's dbid and child's entity type, retrun one child at a time.
    :returns: A row of child
    """
    try:
        current_index = 0
        etype = ""
        if entitytype:
            etype = " AND tblEntities.EntityType = '%s' " % entitytype
        order = "ORDER BY tblAttachedEntities.AttachedSortSequenceId, tblAttachedEntities.id"
        next_row = " tblAttachedEntities.id > '%s' " % current_index
        while True:
            row = db.execute_db("SELECT tblEntities.*, tblAttachedEntities.id AS aid"
                                " FROM tblEntities JOIN tblAttachedEntities "
                                "WHERE  (tblAttachedEntities.tblEntities = '%s' AND "
                                "tblAttachedEntities.AttachedEntityId = tblEntities.id "
                                "AND %s %s) "
                                " %s LIMIT 1" % (dbid, next_row, etype, order))
            if row:
                row = row[0]
                if current_index == row['id']:
                    LOG.critical("Unable to get next row - same row being returned for dbid %s entitytype %s" %
                                 (dbid, str(entitytype)))
                    break
                if row.get("tblAttachedEntities.AttachedSortSequenceId", 0) != 0:
                    current_index = row["tblAttachedEntities.AttachedSortSequenceId"]
                    next_row = " tblAttachedEntities.AttachedSortSequenceId > '%s' " % current_index
                else:
                    current_index = row['aid']
                    next_row = " tblAttachedEntities.id > '%s' " % current_index

                crow = db.get_row("tblAttachedEntities", "id='%s' " % row['aid'], order="ORDER BY id LIMIT 1")
                row.update(crow)
                yield lower_key(row)
            else:
                break
    except:
        log_exception(sys.exc_info())


'''
def mysql_wrap(func):
    def wrapper(self, *args, **kwargs):
        try:
#            if self._conn:
#                return func(self, *args, **kwargs)
            _conn, curosr =  _get_connection()
            result = func(self, *args, **kwargs)
            self._close_connection(_conn, _cursor)
            return result
        except:
            log_exception(sys.exc_info())
    return wrapper
'''


class CloudGlobalBase(object):
    current_connection_pool = 0
    maximum_used_connections = 2
    current_threads = []
    pool_setup = 0
    db_pool = None

    def __init__(self, pool=True, log=True, LOG=LOG, **kwargs):
        self.db_specs = database_info("mysql://root:cloud2674@192.168.228.23/CloudFlowPortal")
        if self.db_specs is None:
            LOG.critical(_("Unable to decode cloudflow db connection string"))
            return

        self.log = log
        if log:
            LOG.debug(_("CloudFlow database starting ..."))

        self.pool = pool
        self.conn = None
        self.cursor = None
        self.LOG = LOG
        try:
            if self.pool:
                if not self.__class__.db_pool:
                    self.__class__.db_pool = eventlet.db_pool.ConnectionPool(MySQLdb, host=self.db_specs['address'],
                                                                             user=self.db_specs['user'],
                                                                             port=8000,
                                                                             passwd=self.db_specs['password'],
                                                                             db=self.db_specs['database'],
                                                                             max_idle=300,
                                                                             max_age=300,
                                                                             max_size=50,
                                                                             connect_timeout=15,
                                                                             )

                    if log:
                        self.LOG.debug(_("CloudFlow database started as pool"))
                else:
                    if log:
                        self.LOG.debug(_("CloudFlow database already started as pool"))
            else:
                self.conn = MySQLdb.connect(host=self.db_specs['address'],
                                            port=8000,
                                            user=self.db_specs['user'],
                                            passwd=self.db_specs['password'],
                                            db=self.db_specs['database'])
                self.conn.autocommit(True)
                self.cursor = self.conn.cursor(MySQLdb.cursors.DictCursor)
                if log:
                    self.LOG.debug(_("CloudFlow database started for single connection"))

        except MySQLdb.Error as e:
            self.LOG.critical("CloudFlow database Error - %s" % e)
            log_normal_exception(None)
        except:
            log_exception(sys.exc_info())

    def close_check(self):
        """
        Close db connection only if open
        """
        if self.conn and self.conn.open:
            self.close()

    def close(self, log=True):
        if not self.pool:
            self.cursor.close()
            self.conn.close()
        if log:
            if self.log:
                self.LOG.debug(_("CloudFlow database stopped"))

    def _get_connection(self):
        if not self.pool:
            return self.conn, self.cursor
        count = 0
        _conn = _cursor = None

        '''
        if threading.currentThread().ident in self.current_threads:
            self.LOGinfo(_("Waiting for Conn - #:%s Thread name: %s id:%s green id:%s"  % \
                    (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
            while True:
                eventlet.greenthread.sleep(0)
                if threading.currentThread().ident not in self.current_threads:
                    break
        '''
        while True:
            err = ""
            try:
                #                self.LOG.info(_("Get Conn - #:%s Thread name: %s id:%s green id:%s"  % \
                #                    (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
                #                self.current_threads.append(threading.currentThread().ident)
                _conn = self.__class__.db_pool.get()
                #                self.LOG.info(_("Get Cursor - #:%s Thread name: %s id:%s green id:%s"  % \
                #                    (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
                _cursor = _conn.cursor(MySQLdb.cursors.DictCursor)
                _conn.autocommit(True)

                #                self.LOG.info(_("DB + #: %s Thread name: %s id:%s green id:%s"  % \
                #                    (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
                break

            except MySQLdb.Error as e:
                self.LOG.critical("CloudFlow database Error - %s" % e)
                log_normal_exception(None)
            except:
                log_exception(sys.exc_info())

            # if threading.currentThread().ident in self.current_threads:
            #                self.current_threads.remove(threading.currentThread().ident)
            if count < 20:
                greenthreadid = eventlet.corolocal.get_ident()
                t = threading.currentThread()
                self.LOG.warn(_("%s - No DB connection Time %s sec thread name:%s thread id:%s greenthreadid:%s" \
                                % (err, count, t.name, t.ident, greenthreadid)))
                eventlet.greenthread.sleep(seconds=0)
                time.sleep(1)
                count += 1
                continue
            greenthreadid = eventlet.corolocal.get_ident()
            t = threading.currentThread()
            self.LOG.warn(_(
                "No DB connection for thread name:%s thread id:%s greenthreadid:%s" % (t.name, t.ident, greenthreadid)))
            self.LOG.critical(_("Unable to get DB connection afer 20 seconds"))
            log_normal_exception(None)
            raise IOError
        self.current_connection_pool += 1
        if self.current_connection_pool > self.maximum_used_connections:
            self.maximum_used_connections = self.current_connection_pool
            self.LOG.info(_("DB - New max count:%s Thread name: %s id:%s green id:%s" % \
                            (self.current_connection_pool, threading.currentThread().name,
                             threading.currentThread().ident, eventlet.corolocal.get_ident())))
        return _conn, _cursor

    def _close_connection(self, _conn, _cursor):
        if not self.pool:
            return
        # self.LOG.info(_("DB - #:%s Thread name: %s id:%s green id:%s"  % \
        #                (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
        if not _cursor or not _conn:
            self.LOG.critical("Invalid DB Close called")
            log_normal_exception(None)
            return
        self.current_connection_pool -= 1
        _cursor.close()
        self.__class__.db_pool.put(_conn)

    #        if threading.currentThread().ident in self.current_threads:
    #            self.current_threads.remove(threading.currentThread().ident)
    #            eventlet.greenthread.sleep(0)

    def get_row(self, table, dbsearch, order=""):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT * FROM %s WHERE (%s) %s" % (table, dbsearch, order))
            if self.log:
                self.LOG.debug(
                    _("%s: Get from %s where %s returned %s rows" % (caller_name(), table, dbsearch, _cursor.rowcount)))
            return _cursor.fetchone()
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing get %s \n %s" % (
                "SELECT * FROM %s WHERE (%s) %s" % (table, dbsearch, order), e.message))
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_row_dict(self, table, where_dict, order="", time_clause=None,
                     ignore_deleted=False):  # TODO THIS I VADIM CHANGED BECAUSE HAS BUG
        condition = ""
        for k, v in where_dict.items():
            condition += " %s = '%s' AND" % (k, v)
        if condition == "":
            self.LOG.critical("Must specify at least one WHERE clause in dictionary  - none found")
            return None

        if not ignore_deleted:
            if len(self.execute_db("SHOW COLUMNS FROM %s LIKE '%s'" % (table, "deleted"))) > 0:  # Vadim added this
                where_clause = condition + " deleted = 0"
            else:
                where_clause = strip_suffix(condition, "AND")
        else:
            where_clause = strip_suffix(condition, "AND")

        if time_clause is not None and "field" in time_clause and "check" in time_clause and "time" in time_clause:
            where_clause += " AND %s %s '%s'" % (time_clause["field"], time_clause["check"], time_clause['time'])

        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT * FROM %s WHERE (%s) %s" % (table, where_clause, order))
            if self.log:
                self.LOG.debug(_("%s: Get command %s where (%s) %s returned %s rows" % (
                    caller_name(), table, where_clause, order, _cursor.rowcount)))
            return _cursor.fetchone()
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing a get -%s" % e.message)
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_multiple_row(self, table, dbsearch, order=""):
        if self.log:
            self.LOG.debug(_("the get command %s where %s") % (table, dbsearch))
        _conn, _cursor = self._get_connection()
        try:
            rows = _cursor.execute("SELECT  * FROM %s WHERE (%s) %s" % (table, dbsearch, order))
            if self.log:
                self.LOG.debug(
                    _("Get command %s where (%s) %s returned %s rows" % (table, dbsearch, order, _cursor.rowcount)))
            return _cursor.fetchall()
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing a get -%s" % e.message)
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_rowcount(self, table, dbsearch):
        _conn, _cursor = self._get_connection()
        try:
            rows = _cursor.execute("SELECT  COUNT(*) FROM %s WHERE (%s) " % (table, dbsearch))
            if self.log:
                self.LOG.debug(_("Get command %s where (%s) returned %s rows" % (table, dbsearch, _cursor.rowcount)))
            rows = _cursor.fetchall()
            return rows[0].values()[0]
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing a multiple get_rowcount -%s" % e.message)
            log_normal_exception(None)
            return 0
        finally:
            self._close_connection(_conn, _cursor)

    def get_rowcount_enh(self, db, dbsearch):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT  COUNT(*) FROM CloudFlow.%s WHERE (%s) " % (db, dbsearch))
            rows = _cursor.fetchall()
            return {'error': False, 'count': rows[0].values()[0]}
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing a multiple get_rowcount -%s" % e.message)
            log_normal_exception(None)
            return {'error': True, 'count': 0}
        finally:
            self._close_connection(_conn, _cursor)

    def delete_row_id(self, table, dbid):
        _conn, _cursor = self._get_connection()
        try:
            """ delete identified row in the db"""
            if self.log:
                self.LOG.debug(_("delete row from %s id=%d ") % (table, dbid))
            if dbid is not None:
                try:
                    _cursor.execute("Delete from %s WHERE id=%d" % (table, dbid))
                    if self.log:
                        self.LOG.debug(_("Exit from delete row from %s  ") % table)
                except MySQLdb.Error as e:
                    self.LOG.critical("Error in executing delete a row in delete_uri - %s" % e.message)
                    log_normal_exception(None)
                    return
        finally:
            self._close_connection(_conn, _cursor)

    def delete_rows_dict(self, table, where_dict, time_clause=None):
        _conn, _cursor = self._get_connection()
        try:
            """ delete identified row in the db"""

            condition = ""
            for k, v in where_dict.items():
                condition += " %s = '%s' AND" % (k, v)
            if condition == "":
                self.LOG.critical("Must specify at least one WHERE clause in dictionary  - none found")
                log_normal_exception(None)
                return 0

            if "deleted" in FLAGS.db_tables_dict[table]:
                where_clause = condition + " deleted = 0"
            else:
                where_clause = strip_suffix(condition, "AND")

            if time_clause is not None and "field" in time_clause and "check" in time_clause and "time" in time_clause:
                where_clause += " AND %s %s '%s'" % (time_clause["field"], time_clause["check"], time_clause['time'])
            if self.log:
                self.LOG.debug(_("DELETE row from %s WHERE %s ") % (table, where_clause))
            query = None
            try:

                if "deleted" in FLAGS.db_tables_dict[table]:
                    query = "UPDATE %s SET deleted_at=now(), deleted = 1 WHERE %s " % (table, where_clause)
                else:
                    query = "DELETE from %s WHERE %s " % (table, where_clause)
                count = _cursor.execute(query)
                if self.log:
                    self.LOG.debug(_("exit with count of %s delete query completed: %s  ") % (count, query))
                return count
            except MySQLdb.Error as e:
                self.LOG.critical("commnd is %s " % query)
                self.LOG.critical("Error in executing delete a row in delete_rows_dict :%s" % e.message)
                log_normal_exception(None)
                return 0
        finally:
            self._close_connection(_conn, _cursor)

    def delete_rows(self, db, timeout):
        _conn, _cursor = self._get_connection()
        try:
            """ delete all destroyed entries posted "timeout" ago """
            if self.log:
                self.LOG.debug(_("delete rows from %s timeout =%s ") % (db, timeout))
            while True:
                try:
                    _cursor.execute(
                        "SELECT id, uriid FROM %s WHERE resource_state = 'DESTROYED' AND deleted_at < DATE_SUB(now(), INTERVAL %d minute) LIMIT 1" % (
                            db, timeout))

                except MySQLdb.Error as e:
                    self.LOG.critical(_("Error in executing Get in delete_rows :%s" % e.message))
                    log_normal_exception(None)
                    return
                svc = _cursor.fetchone()
                if svc == None:
                    break
                try:
                    _cursor.execute("Delete from %s WHERE id=%d" % (db, svc['id']))
                except MySQLdb.Error as e:
                    self.LOG.critical(_("Error in executing delete row in delete_rows :%s" % e.message))
                    log_normal_exception(None)
                    return
                if svc['uriid'] != 0:
                    try:
                        _cursor.execute("Delete from uris WHERE id=%d" % (svc['uriid']))
                        if self.log:
                            self.LOG.debug(_("Exit from delete rows from %s timeout =%s ") % (db, timeout))
                    except MySQLdb.Error as e:
                        self.LOG.critical("Error in executing delete uris row in delete_rows :%s" % e.message)
                        log_normal_exception(None)
                        return
        finally:
            self._close_connection(_conn, _cursor)

    def limit_table(self, table, condition, count, yellow_count=0):
        _conn, _cursor = self._get_connection()
        try:
            c = self.get_rowcount(table, condition)
            if c > (count + yellow_count):
                delta = c - count - yellow_count
                if self.log:
                    self.LOG.info(_("Removing %d entries from %s" % (delta, table)))
                _cursor.execute("DELETE FROM %s WHERE (%s) ORDER BY id ASC LIMIT %s " % (table, condition, delta))
                return None
        except MySQLdb.Error as e:
            self.LOG.critical(_("Error in executing limit table  :%s" % e.message))
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_tables(self):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SHOW TABLES")
            return _cursor.fetchall()
        except MySQLdb.Error as e:
            self.LOG.critical(_("Error in executing get tables  %s" % e.message))
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_tableDesc(self, table):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = '%s'" % table)
            return _cursor.fetchall()
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing get tabledesc :%s" % e.message)
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_database(self):
        #        _conn, _cursor =  self._get_connection()
        try:
            """ returns a dictionary where type is database table name and value is a list of all column names in the table.
            Typical usage will be:
            database = db.get_database()
            for table, columns in database.iteritems():
                print table
                print columns
            """
            tables = self.get_tables()
            Tables = {}

            if tables is None:
                return Tables
                # Get the database name by first entry's key
            dbName = tables[0].keys()[0]
            for table in tables:
                columns = self.get_tableDesc(table[dbName])
                Columns = []
                for column in columns:
                    Columns.append(column['column_name'].lower())
                Tables.update({table[dbName]: Columns})
            return Tables
        except:
            log_exception(sys.exc_info())
            #        finally:
            #            self._close_connection(_conn, _cursor)

    def update_db(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            rsp = _cursor.execute(msg)
            if self.log:
                self.LOG.debug(_("CloudManager: database update command %s"), msg)
            return rsp
        except MySQLdb.Error as e:
            self.LOG.critical("sql command is: %s" % msg)
            self.LOG.critical("Error in executing update_db  - %s" % e.message)
            log_normal_exception(None)
            return
        finally:
            self._close_connection(_conn, _cursor)

    def update_db_rowcount(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            if self.log:
                self.LOG.debug(_("CloudManager: database update command %s"), msg)
            return _conn.affected_rows()
        except MySQLdb.Error as e:
            self.LOG.critical("sql command is: %s" % msg)
            self.LOG.critical("Error in executing update_db  - %s" % e.message)
            log_normal_exception(None)
            return
        finally:
            self._close_connection(_conn, _cursor)

    def update_db_insert(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            if self.log:
                self.LOG.debug(_("CloudManager: database update command %s"), msg)
            return _cursor.lastrowid
        except MySQLdb.Error as e:
            self.LOG.critical("sql command is: %s" % msg)
            self.LOG.critical("Error in executing update_db_insert  - %s" % e.message)
            log_normal_exception(None)
            return 0
        finally:
            self._close_connection(_conn, _cursor)

    def execute_db(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            if self.log:
                self.LOG.debug(_("Execute command %s" % msg))
            response = _cursor.fetchall()
            if self.log:
                self.LOG.debug(_("Execute command response %s" % str(response)))
                self.LOG.debug(_("Updated row(s): {}".format(_cursor.rowcount)))
            return response
        except MySQLdb.Error as e:
            self.LOG.critical("sql command is: %s" % msg)
            self.LOG.critical("Error in executing exceute db  - %s" % e.message)
            log_normal_exception(None)
            return
        finally:
            self._close_connection(_conn, _cursor)

    '''
    def last_insertid(self):
        _conn, _cursor =  self._get_connection()
        try:
            return _conn.insert_id()
        finally:
            self._close_connection(_conn, _cursor)
    '''

    def get_time_stamp(self, delta):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT %s" % delta)
            msg = _cursor.fetchone()
            if self.log:
                self.LOG.debug(_("CloudManager: database time response %s"), msg)
            return {"time": "%s" % msg.values()[0]}
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing get time stamp  - %s" % e.message)
            log_normal_exception(None)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def escape_string(self, msg):
        if not msg:
            return ""
        _conn, _cursor = self._get_connection()
        try:
            esc = MySQLdb.escape_string(msg)
            return esc
        except MySQLdb.Error as e:
            self.LOG.critical("sql command is: %s" % msg)
            self.LOG.critical("Error in executing escape string  %s" % e.message)
            log_normal_exception(None)
            return
        finally:
            self._close_connection(_conn, _cursor)

    def insert_db(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            if self.log:
                self.LOG.debug(_("CloudManager: database update command %s"), msg)
            return {"id": _cursor.lastrowid}
        except MySQLdb.Error as e:
            self.LOG.critical("Error in executing update_db  - : %s" % e.message)
            log_normal_exception(None)
            return 0
        finally:
            self._close_connection(_conn, _cursor)


def log_exception(exc_info, LOG=LOG):
    """Format exception output."""
    LOG.critical(_("some exception ..."))
    stringbuffer = cStringIO.StringIO()
    traceback.print_exception(exc_info[0], exc_info[1], exc_info[2],
                              None, stringbuffer)
    lines = stringbuffer.getvalue().split('\n')
    stringbuffer.close()
    for line in lines:
        LOG.error(line)
    return lines


def log_normal_exception(exc_info, LOG=LOG):
    """Format exception output."""
    if exc_info:
        LOG.critical(_("some exception ..."))
        stringbuffer = cStringIO.StringIO()
        traceback.print_exception(exc_info[0], exc_info[1], exc_info[2], None, stringbuffer)
        lines = stringbuffer.getvalue().split('\n')
        stringbuffer.close()
        for line in lines:
            LOG.error(line)
    else:
        lines = None
    return lines


import syslogger as syslog


def sys_log_exception(exc_info):
    stringbuffer = cStringIO.StringIO()
    traceback.print_exception(exc_info[0], exc_info[1], exc_info[2],
                              None, stringbuffer)
    lines = stringbuffer.getvalue().split('\n')
    stringbuffer.close()
    for line in lines:
        syslog.syslog(line)
    return lines


def database_verify():
    """
    Connect to the database to ensure database configuration is valid
    """
    if FLAGS.cloudflow_connection is None:
        LOG.debug(_("No data base connection string specified"))
        return True
    db = CloudGlobalBase(pool=False)
    FLAGS.db_tables_dict = db.get_database()
    db.close()
    LOG.debug(_("Cloudflow primary db connection string verified"))
    return True


log_rotate = '''
/var/log/cloudflow/*.log {
         daily
         missingok
         # How many days to keep logs
         rotate 1
         compress
         delaycompress
         notifempty
         olddir previous
         postrotate
            monit reload
            endscript
         }
'''


def create_logger(log_name, log_file, log_level=logging.DEBUG, propogate=False):
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except OSError, e:
            print ("error: %s %s." % (e.filename, e.strerror))

    write_file(log_rotate, "/etc/logrotate.d/cloudflow")

    logger = logging.getLogger(log_name)
    handler = logging.handlers.WatchedFileHandler(log_file, mode='w')
    fmt = logging.Formatter('%(asctime)s - %(thread)d - %(filename)-10s - %(funcName)12s - %(levelname)s - %(message)s',
                            datefmt='%m/%d/%Y %I:%M:%S %p')
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = propogate
    logger.setLevel(log_level)


def create_logger_old(log_name, log_file, log_level=logging.DEBUG, propogate=False):
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except OSError, e:
            print ("error: %s %s." % (e.filename, e.strerror))

    logger = logging.getLogger(log_name)
    handler = logging.handlers.RotatingFileHandler(log_file, mode='w', maxBytes=10 * 1024 * 1024, backupCount=1)
    fmt = logging.Formatter('%(asctime)s - %(thread)d - %(filename)-10s - %(funcName)12s - %(levelname)s - %(message)s',
                            datefmt='%m/%d/%Y %I:%M:%S %p')
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = propogate
    logger.setLevel(log_level)


def setup_flags_logs(log_file, flagfile='/etc/cloudflow/cloudflow_python.conf', logdir=None, init_logger=True):
    """ Function doc """
    if flagfile is None:
        print "No flag file specified"
    else:
        try:
            FLAGS(['pgm_name', '--flagfile=' + flagfile])
        except gflags.UnrecognizedFlagError, e:
            print '%s\\nUsage: %s ARGS\\n%s' % (e, sys.argv[0], FLAGS)
            sys.exit(1)
    try:
        argv = FLAGS(sys.argv)  # parse flags

    except gflags.FlagsError, e:
        print '%s\\nUsage: %s ARGS\\n%s' % (e, sys.argv[0], FLAGS)
        sys.exit(1)

    if not os.path.exists("/var/log/cloudflow"):
        os.makedirs("/var/log/cloudflow")
    if FLAGS.log_directory == '.':
        FLAGS.log_directory = "/var/log/cloudflow"
    if logdir is not None:
        FLAGS.log_directory = logdir

    if not os.path.exists(FLAGS.log_directory):
        os.makedirs(FLAGS.log_directory)

    if not os.path.exists(FLAGS.pid_directory):
        os.makedirs(FLAGS.pid_directory)

    if init_logger:
        lfile = FLAGS.log_directory + '/' + log_file
        ###EMPTY the log file and close it.  Start with a new file everytime
        open(FLAGS.log_directory + '/' + log_file, 'w').close()
        LOG.setLevel(logging.DEBUG)
        if os.path.exists(lfile):
            try:
                os.remove(lfile)
            except OSError, e:
                print ("error: %s %s." % (e.filename, e.strerror))
        create_logger(None, lfile)

    if FLAGS.pid_directory == '.':
        FLAGS.pid_directory = os.path.dirname(os.path.abspath(__file__))

    LOG.info(_("Input flag Name: flagfile Value: %s" % flagfile))
    # print all flags in the log file
    for flag in FLAGS:
        if not (flag == '?' or flag == 'helpxml'):
            flag_get = FLAGS.get(flag, None)
            LOG.info(_("Input flag Name: %s Value: %s" % (flag, flag_get)))

    if database_verify() == None:
        LOG.critical(_("Unable to decode cloudflow db connection string"))
        sys.exit()


import inspect


def caller_name(skip=2):
    """Get a name of a caller in the format module.class.method

       `skip` specifies how many levels of stack to skip while getting caller
       name. skip=1 means "who calls me", skip=2 "who calls my caller" etc.

       An empty string is returned if skipped levels exceed stack height
    """
    stack = inspect.stack()
    start = 0 + skip
    if len(stack) < start + 1:
        return ''
    parentframe = stack[start][0]

    name = []
    module = inspect.getmodule(parentframe)
    # `modname` can be None when frame is executed directly in console
    # TODO(techtonik): consider using __main__
    if module:
        name.append(module.__name__)
    # detect classname
    if 'self' in parentframe.f_locals:
        # I don't know any way to detect call from the object method
        # XXX: there seems to be no way to detect static method call - it will
        #      be just a function call
        name.append(parentframe.f_locals['self'].__class__.__name__)
    codename = parentframe.f_code.co_name
    if codename != '<module>':  # top level usually
        name.append(codename)  # function or a method
    del parentframe
    return ".".join(name)


def database_info(connection):
    """
    Parse an SQL string of the format:
        database_type://user:password@address:/database
        mysql://dbadmin:password@10.0.0.1/nova
    """
    db = {}
    conn = connection.partition(':')
    if conn[1] != ':':
        return None
    db['type'] = conn[0]
    conn = conn[2]
    conn = conn.lstrip('/')
    conn = conn.partition(':')
    if conn[1] != ':':
        return None
    db['user'] = conn[0]
    conn = conn[2]
    conn = conn.partition('@')
    if conn[1] != '@':
        return None
    db['password'] = conn[0]
    conn = conn[2]
    conn = conn.partition('/')
    if conn[1] != '/':
        return None
    db['address'] = conn[0]
    db['database'] = conn[2]
    return db


def mysql_now():
    return python_time_to_mysql(datetime.datetime.utcnow())


def time_formats():
    print datetime.datetime.now()
    print datetime.datetime.utcnow()
    print datetime.datetime.now().isoformat()

    print time.time()
    print time.strftime("%Y-%m-%d %H:%M:%S")
    print time.asctime(time.localtime(time.time()))


def python_time_to_mysql(python_time):
    return python_time.strftime("%Y-%m-%d %H:%M:%S")


# convert from JAVASCRIPT time format to python
#  ISO 8601 TimeFormat
#  If the time is in UTC, add a Z directly after the time without a space. Z is the zone designator for the zero UTC offset
def jscript_time_to_python(t):
    return datetime.datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%fZ')


def utc_to_local(t):
    from_zone = tz.tzutc()
    to_zone = tz.tzlocal()
    t = t.replace(tzinfo=from_zone)
    return t.astimezone(to_zone)


def mysql_time_to_python(mysql_time):
    return datetime.datetime.strptime(str(mysql_time), "%Y-%m-%d %H:%M:%S")


def mysql_time_to_local_python(mysql_time):
    return utc_to_local(datetime.datetime.strptime(str(mysql_time), "%Y-%m-%d %H:%M:%S"))


def current_less_minutes(minutes):
    return (datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes))


def current_plus_minutes(minutes):
    return (datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes))


def elapsed_seconds_from_mysql_time(mysql_time):
    elapsedTime = datetime.datetime.utcnow() - mysql_time_to_python(mysql_time)
    return elapsedTime.days * 86400 + elapsedTime.seconds


import struct


def ip2int(addr):
    return struct.unpack("!I", socket.inet_aton(addr))[0]


def int2ip(addr):
    return socket.inet_ntoa(struct.pack("!I", addr))


def update_user_url(user_url, cfd_url):
    final_url = user_url
    try:
        if user_url:
            if user_url != "None":
                u = yurl.URL(user_url).validate()
                c = yurl.URL(cfd_url).validate()
                final_url = str(yurl.URL(scheme=c.scheme, host=c.host, port=u.port, path=u.path, query=u.query))
            else:
                return ""
    except:
        pass
    return final_url


def get_next_service_interface(db, dbid, LOG=LOG):
    try:
        current_index = 0
        while True:
            row = db.execute_db("SELECT tblEntities.*, tblServicesInterfaces.*, tblServicesInterfaces.id as child_id "
                                " FROM tblEntities JOIN tblServicesInterfaces "
                                "WHERE  (tblEntities.id > '%s' AND tblEntities.deleted=0 AND "
                                "tblEntities.EntityType = 'network_interface' AND "
                                "tblServicesInterfaces.tblEntities = tblEntities.id AND "
                                " (tblServicesInterfaces.BeginServiceEntityId = '%s' OR "
                                "tblServicesInterfaces.EndServiceEntityId = '%s')"
                                ") "
                                " ORDER BY tblEntities.id LIMIT 1" % (current_index, dbid, dbid))

            if not row:
                break
            row = row[0]
            current_index = row["id"]
            yield lower_key(row)

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        log_exception(sys.exc_info())


def log_test(msg):
    LOG.info(_("%s" % msg))


import psutil


def kill_priors(pgm_name, pgm_type="python"):
    try:
        syslog.syslog("Remving all previous instances of %s" % pgm_name)
        my_pid = os.getpid()
        all_pids = psutil.pids()
        for pid in all_pids:
            try:
                p = psutil.Process(pid)
            except:
                continue
            cmds = p.cmdline()
            if pid == my_pid:
                syslog.syslog("Cmd %s with Pid %s is started" % (cmds, pid))
                continue
            if not cmds or not cmds[0].endswith(pgm_type):
                continue
            if len(cmds) >= 2:
                if cmds[1].endswith(pgm_name):
                    try:
                        p.terminate()
                        syslog.syslog("Cmd %s with Pid %s is removed" % (cmds, pid))
                    except:
                        pass
        syslog.syslog("All previous instances of %s removed" % pgm_name)
    except:
        sys_log_exception(sys.exc_info())


def read_file(filename):
    try:
        if os.path.exists(filename):
            f = open(filename, 'r')
            entity = f.read()
            f.close()
            return entity
        else:
            LOG.critical(_("file %s not found" % filename))
    except:
        log_exception(sys.exc_info())
    return


def write_file(entity, filename, append_file_out=False):
    try:
        if append_file_out:
            f = open(filename, 'a')
        else:
            f = open(filename, 'w')
        f.write(entity)
        f.close()
        return filename
    except:
        log_exception(sys.exc_info())


def update_file(file_in, replace_dict, file_out=None, append_file_out=False, append_string=None):
    try:
        if not file_out:
            file_out = file_in
        s = read_file(file_in)
        if replace_dict:
            for o in replace_dict:
                if o in s:
                    LOG.info(_("replace %s with %s" % (o, replace_dict[o])))
                    s = s.replace(o, replace_dict[o])
        if append_string:
            s += append_string
        write_file(s, file_out, append_file_out=append_file_out)
    except:
        log_exception(sys.exc_info())
