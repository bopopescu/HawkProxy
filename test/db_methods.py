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
import sqlite3
import subprocess
import datetime
from dateutil import tz
import string
import re
import eventlet

import logging.handlers
import time
from utils.underscore import _
import uuid

import eventlet.corolocal

import eventlet.db_pool

import threading

eventlet.monkey_patch()

currentDir = os.path.dirname(os.path.abspath(__file__))

# if os.path.abspath('%s/../dist_packages' % currentDir) not in sys.path:
#    sys.path.insert(0,os.path.abspath('%s/../dist_packages' % currentDir))


sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

import mysql.connector
from mysql.connector import errorcode
from  mysql.connector import conversion

LOG = logging.getLogger()
FLAGS = gflags.FLAGS

import utils.uuid_utils as uuid_utils


class MySQLCursorDict(mysql.connector.cursor.MySQLCursorBuffered):
    def _row_to_python(self, rowdata, desc=None):
        row = super(MySQLCursorDict, self)._row_to_python(rowdata, desc)
        if row:
            return dict(zip(self.column_names, row))
        return None


# mysql-connector-python
class newCloudGlobalBase(object):
    current_connection_pool = 0
    current_threads = []

    def __init__(self, pool=True, log=True, **kwargs):
        self.db_specs = database_info(FLAGS.cloudflow_connection)
        if self.db_specs is None:
            LOG.critical(_("Unable to decode cloudflow db connection string"))
            return
        if log:
            LOG.debug(_("CloudFlow database started"))

        self.pool = pool
        self.conn = None
        self.cursor = None
        try:
            if self.pool:
                _conn = mysql.connector.connect(host=self.db_specs['address'],
                                                user=self.db_specs['user'],
                                                passwd=self.db_specs['password'],
                                                db=self.db_specs['database'],
                                                buffered=True,
                                                autocommit=True,
                                                pool_name="mysqlpool",
                                                pool_size=5,
                                                connection_timeout=30,
                                                get_warnings=True
                                                )
                _conn.close()
            else:
                self.conn = mysql.connector.connect(host=self.db_specs['address'],
                                                    user=self.db_specs['user'],
                                                    passwd=self.db_specs['password'],
                                                    db=self.db_specs['database'],
                                                    buffered=True,
                                                    autocommit=True,
                                                    )
                self.cursor = self.conn.cursor(cursor_class=MySQLCursorDict)

        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                LOG.critical(_("Something is wrong with your user name or password"))
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                LOG.critical(_("Database does not exists"))
            else:
                LOG.critical(_(err))
        except:
            log_exception(sys.exc_info())

    def close(self, log=True):
        if not self.pool:
            self.cursor.close()
            self.conn.close()
        if log:
            LOG.debug(_("CloudFlow database stopped"))

    def _get_connection(self):
        if not self.pool:
            return self.conn, self.cursor
        count = 0
        _conn = _cursor = None
        if threading.currentThread().ident in self.current_threads:
            LOG.info(_("Waiting for Conn - #:%s Thread name: %s id:%s green id:%s" % \
                       (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident,
                        eventlet.corolocal.get_ident())))
            while True:
                eventlet.greenthread.sleep(0)
                if threading.currentThread().ident not in self.current_threads:
                    break
        while True:
            err = ""
            try:
                LOG.info(_("Get Conn - #:%s Thread name: %s id:%s green id:%s" % \
                           (self.current_connection_pool, threading.currentThread().name,
                            threading.currentThread().ident, eventlet.corolocal.get_ident())))
                self.current_threads.append(threading.currentThread().ident)
                _conn = mysql.connector.connect(pool_name="mysqlpool")
                LOG.info(_("Get Cursor - #:%s Thread name: %s id:%s green id:%s" % \
                           (self.current_connection_pool, threading.currentThread().name,
                            threading.currentThread().ident, eventlet.corolocal.get_ident())))
                _cursor = _conn.cursor(cursor_class=MySQLCursorDict)

                LOG.info(_("DB + #: %s Thread name: %s id:%s green id:%s" % \
                           (self.current_connection_pool, threading.currentThread().name,
                            threading.currentThread().ident, eventlet.corolocal.get_ident())))
                break
            except mysql.connector.Error as err:

                if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                    LOG.critical(_("Something is wrong with your user name or password"))
                elif err.errno == errorcode.ER_BAD_DB_ERROR:
                    LOG.critical(_("Database does not exists"))
                    #                else:
                    #                    LOG.warning(_(err))
            except:
                log_exception(sys.exc_info())
            if threading.currentThread().ident in self.current_threads:
                self.current_threads.remove(threading.currentThread().ident)
            if count < 20:
                greenthreadid = eventlet.corolocal.get_ident()
                t = threading.currentThread()
                LOG.warn(_("%s - No DB connection Time %s sec thread name:%s thread id:%s greenthreadid:%s" % (
                    err, count, t.name, t.ident, greenthreadid)))
                eventlet.greenthread.sleep(seconds=0)
                time.sleep(1)
                count += 1
                continue
            greenthreadid = eventlet.corolocal.get_ident()
            t = threading.currentThread()
            LOG.warn(_(
                "No DB connection for thread name:%s thread id:%s greenthreadid:%s" % (t.name, t.ident, greenthreadid)))
            LOG.critical(_("Unable to get DB connection afer 20 seconds"))
            raise IOError
        self.current_connection_pool += 1
        return _conn, _cursor

    def _close_connection(self, _conn, _cursor):
        if not self.pool:
            return
        LOG.info(_("DB - #:%s Thread name: %s id:%s green id:%s" % \
                   (self.current_connection_pool, threading.currentThread().name, threading.currentThread().ident,
                    eventlet.corolocal.get_ident())))
        if not _cursor or not _conn:
            LOG.critical("Invalid DB Close called")
            return
        self.current_connection_pool -= 1
        _cursor.close()
        _conn.close()
        if threading.currentThread().ident in self.current_threads:
            self.current_threads.remove(threading.currentThread().ident)
            eventlet.greenthread.sleep(0)

    def get_row(self, db, dbsearch, order=""):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT * FROM %s WHERE (%s) %s" % (db, dbsearch, order))
            LOG.debug(_("Get from %s where %s returned %s rows" % (db, dbsearch, _cursor.rowcount)))
            return _cursor.fetchone()
        except mysql.connector.Error as e:
            LOG.critical("Error in executing a get -%s" % e.message)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_row_dict(self, table, where_dict, order="", time_clause=None):
        condition = ""
        for k, v in where_dict.items():
            condition += " %s = '%s' AND" % (k, v)
        if condition == "":
            LOG.critical("Must specify at least one WHERE clause in dictionary  - none found")
            return None

        if "deleted" in FLAGS.db_tables_dict[table]:
            where_clause = condition + " deleted = 0"
        else:
            where_clause = strip_suffix(condition, "AND")

        if time_clause is not None and "field" in time_clause and "check" in time_clause and "time" in time_clause:
            where_clause += " AND %s %s '%s'" % (time_clause["field"], time_clause["check"], time_clause['time'])

        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT  * FROM %s WHERE (%s) %s" % (table, where_clause, order))
            LOG.debug(
                _("Get command %s where (%s) %s returned %s rows" % (table, where_clause, order, _cursor.rowcount)))
            return _cursor.fetchone()
        except mysql.connector.Error as e:
            LOG.critical("Error in executing a get -%s" % e.message)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_multiple_row(self, table, dbsearch, order=""):
        LOG.debug(_("the get command %s where %s") % (table, dbsearch))
        _conn, _cursor = self._get_connection()
        try:
            rows = _cursor.execute("SELECT  * FROM %s WHERE (%s) %s" % (table, dbsearch, order))
            LOG.debug(_("Get command %s where (%s) %s returned %s rows" % (table, dbsearch, order, _cursor.rowcount)))
            return _cursor.fetchall()
        except mysql.connector.Error as e:
            LOG.critical("Error in executing a get -%s" % e.message)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_rowcount(self, table, dbsearch):
        _conn, _cursor = self._get_connection()
        try:
            rows = _cursor.execute("SELECT  COUNT(*) FROM %s WHERE (%s) " % (table, dbsearch))
            LOG.debug(_("Get command %s where (%s) returned %s rows" % (table, dbsearch, _cursor.rowcount)))
            rows = _cursor.fetchall()
            return rows[0].values()[0]
        except mysql.connector.Error as e:
            LOG.critical("Error in executing a multiple get_rowcount -%s" % e.message)
            return 0
        finally:
            self._close_connection(_conn, _cursor)

    def set_deleted_row_with_uri(self, table, row):
        _conn, _cursor = self._get_connection()
        try:
            """ delete identified row in the table"""
            LOG.debug(_("Set deleted rows from %s rowid=%d ") % (table, row['id']))
            if row['uriid'] != 0:
                try:
                    _cursor.execute("UPDATE uris SET deleted_at=now(),deleted = 1 WHERE id=%d" % (row['uriid']))
                except mysql.connector.Error as e:
                    LOG.critical("Error in executing setting deleted uris row in delete_row_with_uri -%s" % e.message)
                    return
            try:
                _cursor.execute(
                    "UPDATE %s SET deleted_at=now(), deleted = 1, resource_state = 'Deleted' WHERE id=%d" % (
                        table, row['id']))
                LOG.debug(_("Exit from setting delete row with uri from %s  ") % table)
                return
            except mysql.connector.Error as e:
                LOG.critical(
                    "Error in executing setting deleted row in delete_row_with_uri - %s" % e.message)
        finally:
            self._close_connection(_conn, _cursor)

    def delete_row_with_uri(self, db, row):
        _conn, _cursor = self._get_connection()
        try:
            """ delete identified row in the db"""
            LOG.debug(_("delete rows from %s rowid=%d ") % (db, row['id']))
            if row['uriid'] != 0:
                try:
                    _cursor.execute("Delete from uris WHERE id=%d" % (row['uriid']))
                except MySQLdb.Error, e:
                    LOG.critical(
                        "Error in executing delete uris row in delete_row_with_uri -%s" % e)
                    return
            try:
                _cursor.execute("Delete from %s WHERE id=%d" % (db, row['id']))
                LOG.debug(_("Exit from delete row with uri from %s  ") % db)
            except mysql.connector.Error as e:
                LOG.critical("Error in executing delete row in delete_row_with_uri %s" % e.message)
                return
        finally:
            self._close_connection(_conn, _cursor)

    def delete_row_id(self, table, dbid):
        _conn, _cursor = self._get_connection()
        try:
            """ delete identified row in the db"""
            LOG.debug(_("delete row from %s id=%d ") % (table, dbid))
            if dbid is not None:
                try:
                    _cursor.execute("Delete from %s WHERE id=%d" % (table, dbid))
                    LOG.debug(_("Exit from delete row from %s  ") % table)
                except mysql.connector.Error as e:
                    LOG.critical("Error in executing delete a row in delete_uri - %s" % e.message)
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
                LOG.critical("Must specify at least one WHERE clause in dictionary  - none found")
                return 0

            if "deleted" in FLAGS.db_tables_dict[table]:
                where_clause = condition + " deleted = 0"
            else:
                where_clause = strip_suffix(condition, "AND")

            if time_clause is not None and "field" in time_clause and "check" in time_clause and "time" in time_clause:
                where_clause += " AND %s %s '%s'" % (time_clause["field"], time_clause["check"], time_clause['time'])

            LOG.debug(_("DELETE row from %s WHERE %s ") % (table, where_clause))
            query = None
            try:
                if "deleted" in FLAGS.db_tables_dict[table]:
                    query = "UPDATE %s SET deleted_at=now(), deleted = 1 WHERE %s " % (table, where_clause)
                else:
                    query = "DELETE from %s WHERE %s " % (table, where_clause)
                count = _cursor.execute(query)
                LOG.debug(_("exit with count of %s delete query completed: %s  ") % (count, query))
                return count
            except mysql.connector.Error as e:
                LOG.critical("commnd is %s " % query)
                LOG.critical("Error in executing delete a row in delete_rows_dict :%s" % e.message)
                return 0
        finally:
            self._close_connection(_conn, _cursor)

    def delete_rows(self, db, timeout):
        _conn, _cursor = self._get_connection()
        try:
            """ delete all destroyed entries posted "timeout" ago """
            LOG.debug(_("delete rows from %s timeout =%s ") % (db, timeout))
            while True:
                try:
                    _cursor.execute(
                        "SELECT id, uriid FROM %s WHERE resource_state = 'DESTROYED' AND deleted_at < DATE_SUB(now(), INTERVAL %d minute) LIMIT 1" % (
                            db, timeout))

                except mysql.connector.Error as e:
                    LOG.critical(_("Error in executing Get in delete_rows :%s" % e.message))
                    return
                svc = _cursor.fetchone()
                if svc == None:
                    break
                try:
                    _cursor.execute("Delete from %s WHERE id=%d" % (db, svc['id']))
                except mysql.connector.Error as e:
                    LOG.critical(_("Error in executing delete row in delete_rows :%s" % e.message))
                    return
                if svc['uriid'] != 0:
                    try:
                        _cursor.execute("Delete from uris WHERE id=%d" % (svc['uriid']))
                        LOG.debug(_("Exit from delete rows from %s timeout =%s ") % (db, timeout))
                    except mysql.connector.Error as e:
                        LOG.critical("Error in executing delete uris row in delete_rows :%s" % e.message)
                        return
        finally:
            self._close_connection(_conn, _cursor)

    def limit_table(self, table, condition, count):
        _conn, _cursor = self._get_connection()
        try:
            c = self.get_rowcount(table, condition)
            if c > count:
                delta = c - count
                LOG.info(_("Removing %d entries from %s" % (delta, table)))
                _cursor.execute("DELETE FROM %s WHERE (%s) ORDER BY id ASC LIMIT %s " % (table, condition, delta))
                return None
        except mysql.connector.Error as e:
            LOG.critical(_("Error in executing limit table  :%s" % e.message))
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_tables(self):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SHOW TABLES")
            return _cursor.fetchall()
        except mysql.connector.Error as e:
            LOG.critical(_("Error in executing get tables  %s" % e.message))
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def get_tableDesc(self, table):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = '%s'" % table)
            return _cursor.fetchall()
        except mysql.connector.Error as e:
            LOG.critical("Error in executing get tabledesc :%s" % e.message)
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

    def update_db(self, msg, log=True):
        _conn, _cursor = self._get_connection()
        try:
            rsp = _cursor.execute(msg)
            if log:
                LOG.debug(_("CloudManager: database update command %s"), msg)
            return rsp
        except mysql.connector.Error as e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing update_db  - %s" % e.message)
            return
        finally:
            self._close_connection(_conn, _cursor)

    def update_db_insert(self, msg, log=True):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            if log:
                LOG.debug(_("CloudManager: database update command %s"), msg)
            return _cursor.lastrowid
        except mysql.connector.Error as e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing update_db_insert  - %s" % e.message)
            return 0
        finally:
            self._close_connection(_conn, _cursor)

    def execute_db(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            LOG.debug(_("Execute command %s" % msg))
            if _cursor.with_rows:
                response = _cursor.fetchall()
                LOG.debug(_("Execute command response %s" % str(response)))
            else:
                LOG.debug(_("Updated row(s): {}".format(_cursor.rowcount)))
                response = None
            return response
        except mysql.connector.Error as e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing exceute db  - %s" % e.message)
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

    def get_time_stamp(self, delta, log=True):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute("SELECT %s" % delta)
            msg = _cursor.fetchone()
            if log:
                LOG.debug(_("CloudManager: database time response %s"), msg)
            return {"time": "%s" % msg.values()[0]}
        except mysql.connector.Error as e:
            LOG.critical("Error in executing get time stamp  - %s" % e.message)
            return None
        finally:
            self._close_connection(_conn, _cursor)

    def escape_string(self, msg):
        try:
            esc = conversion.MySQLConverter().escape(msg)
            return esc
        except mysql.connector.Error as e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing escape string  %s" % e.message)
            return

    def insert_db(self, msg):
        _conn, _cursor = self._get_connection()
        try:
            _cursor.execute(msg)
            LOG.debug(_("CloudManager: database update command %s"), msg)
            return {"id": _cursor.lastrowid}
        except mysql.connector.Error as e:
            LOG.critical("Error in executing update_db  - : %s" % e.message)
            return 0
        finally:
            self._close_connection(_conn, _cursor)


class MySQLdb_CloudGlobalBase(object):
    def __init__(self, log=True, **kwargs):
        db = database_info(FLAGS.cloudflow_connection)
        if db is None:
            LOG.critical(_("Unable to decode cloudflow db connection string"))
            return
        count = 0

        while True:
            try:
                self._conn = MySQLdb.connect(host=db['address'],
                                             user=db['user'],
                                             passwd=db['password'],
                                             db=db['database'])
                break
            except MySQLdb.Error, e:
                LOG.critical("CloudFlow database Error - %s" % e)
                self._conn = None
                self._cursor = None
                if count < 10:
                    time.sleep(1)
                    continue
                raise IOError

        self._conn.autocommit(True)
        self._cursor = self._conn.cursor(MySQLdb.cursors.DictCursor)
        if log:
            LOG.debug(_("CloudFlow database started"))

    def close(self, log=True):
        """ Function doc """
        try:
            self._cursor.close()
            self._conn.commit()
            self._conn.close()

        except MySQLdb.Error, e:
            LOG.critical("Error in closing database - %s" % e)
            self._conn = None
            self._cursor = None
            return None
        if log:
            LOG.debug(_("CloudFlow database stopped"))

    def get_row(self, db, dbsearch, order=""):
        """ Function doc """
        try:
            rows = self._cursor.execute("SELECT  * FROM %s WHERE (%s) %s" % (db, dbsearch, order))
        except MySQLdb.Error, e:
            LOG.critical("Error in executing a get -%s" % e)
            return None
        LOG.debug(_("Get from %s where %s returned %s rows" % (db, dbsearch, rows)))
        return self._cursor.fetchone()

    def get_row_dict(self, table, where_dict, order="", time_clause=None):
        """ Function doc """
        condition = ""
        for k, v in where_dict.items():
            condition += " %s = '%s' AND" % (k, v)
        if condition == "":
            LOG.critical("Must specify at least one WHERE clause in dictionary  - none found")
            return None

        if "deleted" in FLAGS.db_tables_dict[table]:
            where_clause = condition + " deleted = 0"
        else:
            where_clause = strip_suffix(condition, "AND")

        if time_clause is not None and "field" in time_clause and "check" in time_clause and "time" in time_clause:
            where_clause += " AND %s %s '%s'" % (time_clause["field"], time_clause["check"], time_clause['time'])

        # LOG.debug(_("Get command %s where (%s) %s") % (table, where_clause, order))
        try:
            rows = self._cursor.execute("SELECT  * FROM %s WHERE (%s) %s" % (table, where_clause, order))
        except MySQLdb.Error, e:
            LOG.critical("Error in executing a get - %s" % e)
            return None
        LOG.debug(_("Get command %s where (%s) %s returned %s rows" % (table, where_clause, order, rows)))
        return self._cursor.fetchone()

    def get_multiple_row(self, table, dbsearch, order=""):
        """ Function doc """
        LOG.debug(_("the get command %s where %s") % (table, dbsearch))
        try:
            rows = self._cursor.execute("SELECT  * FROM %s WHERE (%s) %s" % (table, dbsearch, order))
        except MySQLdb.Error, e:
            LOG.critical("Error in executing a multiple get -%s" % e)
            return None
        LOG.debug(_("Get command %s where (%s) %s returned %s rows" % (table, dbsearch, order, rows)))
        return self._cursor.fetchall()

    def get_rowcount(self, table, dbsearch):
        """ Function doc """
        try:
            rows = self._cursor.execute("SELECT  COUNT(*) FROM %s WHERE (%s) " % (table, dbsearch))
        except MySQLdb.Error, e:
            LOG.critical("Error in executing a multiple get_rowcount -%s" % e)
            return 0
        LOG.debug(_("Get command %s where (%s) returned %s rows" % (table, dbsearch, rows)))
        rows = self._cursor.fetchall()
        return rows[0].values()[0]

    def set_deleted_row_with_uri(self, table, row):
        """ delete identified row in the table"""
        LOG.debug(_("Set deleted rows from %s rowid=%d ") % (table, row['id']))
        if row['uriid'] != 0:
            try:
                self._cursor.execute("UPDATE uris SET deleted_at=now(),deleted = 1 WHERE id=%d" % (row['uriid']))
            except MySQLdb.Error, e:
                LOG.critical("Error in executing setting deleted uris row in delete_row_with_uri -%s" % e)
                return
        try:
            self._cursor.execute(
                "UPDATE %s SET deleted_at=now(), deleted = 1, resource_state = 'Deleted' WHERE id=%d" % (
                    table, row['id']))
        except MySQLdb.Error, e:
            LOG.critical(
                "Error in executing setting deleted row in delete_row_with_uri - %s" % e)
            return
        LOG.debug(_("Exit from setting delete row with uri from %s  ") % table)

    def delete_row_with_uri(self, db, row):
        """ delete identified row in the db"""
        LOG.debug(_("delete rows from %s rowid=%d ") % (db, row['id']))
        if row['uriid'] != 0:
            try:
                self._cursor.execute("Delete from uris WHERE id=%d" % (row['uriid']))
            except MySQLdb.Error, e:
                LOG.critical(
                    "Error in executing delete uris row in delete_row_with_uri -%s" % e)
                return
        try:
            self._cursor.execute("Delete from %s WHERE id=%d" % (db, row['id']))
        except MySQLdb.Error, e:
            LOG.critical("Error in executing delete row in delete_row_with_uri %s" % e)
            return
        LOG.debug(_("Exit from delete row with uri from %s  ") % db)

    def delete_row_id(self, table, dbid):
        """ delete identified row in the db"""
        LOG.debug(_("delete row from %s id=%d ") % (table, dbid))
        if dbid is not None:
            try:
                self._cursor.execute("Delete from %s WHERE id=%d" % (table, dbid))
            except MySQLdb.Error, e:
                LOG.critical("Error in executing delete a row in delete_uri - %s" % e)
                return
        LOG.debug(_("Exit from delete row from %s  ") % table)

    def delete_rows_dict(self, table, where_dict, time_clause=None):
        """ delete identified row in the db"""

        condition = ""
        for k, v in where_dict.items():
            condition += " %s = '%s' AND" % (k, v)
        if condition == "":
            LOG.critical("Must specify at least one WHERE clause in dictionary  - none found")
            return 0

        if "deleted" in FLAGS.db_tables_dict[table]:
            where_clause = condition + " deleted = 0"
        else:
            where_clause = strip_suffix(condition, "AND")

        if time_clause is not None and "field" in time_clause and "check" in time_clause and "time" in time_clause:
            where_clause += " AND %s %s '%s'" % (time_clause["field"], time_clause["check"], time_clause['time'])

        LOG.debug(_("DELETE row from %s WHERE %s ") % (table, where_clause))
        query = None
        try:

            if "deleted" in FLAGS.db_tables_dict[table]:
                query = "UPDATE %s SET deleted_at=now(), deleted = 1 WHERE %s " % (table, where_clause)
            else:
                query = "DELETE from %s WHERE %s " % (table, where_clause)
            count = self._cursor.execute(query)
        except MySQLdb.Error, e:
            LOG.critical("commnd is %s " % query)
            LOG.critical("Error in executing delete a row in delete_rows_dict :%s" % e)
            return 0
        LOG.debug(_("exit with count of %s delete query completed: %s  ") % (count, query))
        return count

    def delete_rows(self, db, timeout):
        """ delete all destroyed entries posted "timeout" ago """
        LOG.debug(_("delete rows from %s timeout =%s ") % (db, timeout))
        while True:
            try:
                self._cursor.execute(
                    "SELECT id, uriid FROM %s WHERE resource_state = 'DESTROYED' AND deleted_at < DATE_SUB(now(), INTERVAL %d minute) LIMIT 1" % (
                        db, timeout))

            except MySQLdb.Error, e:
                LOG.critical(_("Error in executing Get in delete_rows :%s" % e))
                return
            svc = self._cursor.fetchone()
            if svc == None:
                break
            try:
                self._cursor.execute("Delete from %s WHERE id=%d" % (db, svc['id']))
            except MySQLdb.Error, e:
                LOG.critical(_("Error in executing delete row in delete_rows :%s" % e))
                return
            if svc['uriid'] != 0:
                try:
                    self._cursor.execute("Delete from uris WHERE id=%d" % (svc['uriid']))
                except MySQLdb.Error, e:
                    LOG.critical("Error in executing delete uris row in delete_rows :%s" % e)
                    return
        LOG.debug(_("Exit from delete rows from %s timeout =%s ") % (db, timeout))

    def limit_table(self, table, condition, count):
        try:
            c = self.get_rowcount(table, condition)
            if c > count:
                delta = c - count
                LOG.info(_("Removing %d entries from %s" % (delta, table)))
                self._cursor.execute("DELETE FROM %s WHERE (%s) ORDER BY id ASC LIMIT %s " % (table, condition, delta))
        except MySQLdb.Error, e:
            LOG.critical(_("Error in executing limit table  :%s" % e))
            return None
        return None

    def get_tables(self):
        try:
            self._cursor.execute("SHOW TABLES")
        except MySQLdb.Error, e:
            LOG.critical(_("Error in executing update_db  %s" % e))
            return None
        return self._cursor.fetchall()

    def get_tableDesc(self, table):
        try:
            self._cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = '%s'" % table)
        except MySQLdb.Error, e:
            LOG.critical("Error in executing update_db :%s" % e)
            return None
        return self._cursor.fetchall()

    def get_database(self):
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

    def update_db_insert(self, msg, log=True):
        try:
            rsp = self._cursor.execute(msg)
        except MySQLdb.Error, e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing update_db  - %s" % e)
            return
        if log:
            LOG.debug(_("CloudManager: database update command %s"), msg)
        return self.last_insertid()

    def update_db(self, msg, log=True):
        try:
            rsp = self._cursor.execute(msg)
        except MySQLdb.Error, e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing update_db  - %s" % e)
            return
        if log:
            LOG.debug(_("CloudManager: database update command %s"), msg)
        return rsp

    def execute_db(self, msg):
        try:
            self._cursor.execute(msg)
            response = self._cursor.fetchall()
        except MySQLdb.Error, e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing update_db  - %s" % e)
            return

        LOG.debug(_("Execute command %s" % msg))
        LOG.debug(_("Execute command response %s" % str(response)))
        return response

    def last_insertid(self):
        return self._conn.insert_id()

    def get_time_stamp(self, delta, log=True):
        try:
            self._cursor.execute("SELECT %s" % delta)
            msg = self._cursor.fetchone()
        except MySQLdb.Error, e:
            LOG.critical("Error in executing update_db  - %s" % e)
            return None
        if log:
            LOG.debug(_("CloudManager: database time response %s"), msg)
        return {"time": "%s" % msg.values()[0]}

    def escape_string(self, msg):
        try:
            esc = self._conn.escape_string(msg)
        except MySQLdb.Error, e:
            LOG.critical("sql command is: %s" % msg)
            LOG.critical("Error in executing escape string  %s" % e)
            return
        return esc


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
