#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import gflags

import time
import eventlet

import datetime
import eventlet.corolocal

import ujson
import xmlrpclib
import threading
import syslogger as syslog

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

import multiprocessing
import psutil

eventlet.monkey_patch()

LOG = logging.getLogger('vdc-status')

import utils.cloud_utils as cloud_utils

import entity_utils
import entity_functions
import entity_constants
import utils.cache_utils as cache_utils

import rest.rest_api as rest_api
from utils.underscore import _
import entity_manager

FLAGS = gflags.FLAGS

resync_slice_lock = threading.RLock()
resync_slice_requests = []

STATS_DB_CACHE_TIME = 1 * 60 * 60


def port_statisics_manager(db, uris_row, rest):
    pass


def network_service_statisics_manager(db, uris_row, rest):
    return compute_statisics_manager(db, uris_row, rest)


def old_compute_statisics_manager(db, uris_row, rest):
    try:
        if not rest:
            return None

        if not uris_row["statistics_time"]:
            if "timestamp" in rest:
                uris_row["statistics_time"] = cloud_utils.mysql_time_to_python(rest["timestamp"])
            else:
                return

        last_time = cloud_utils.mysql_time_to_python(uris_row["statistics_time"])

        if "stats_compute" in rest:
            LOG.info("Inserting % rows in tblComputeStatistics" % len(rest["stats_compute"]))
            for stat in rest["stats_compute"]:
                stat["tblentities"] = uris_row["tblentities"]
                if "timestamp" not in stat:
                    continue
                cloud_utils.insert_db(db, "tblComputeStatistics", stat)
                timestamp = cloud_utils.mysql_time_to_python(stat["timestamp"])
                if timestamp > last_time:
                    last_time = timestamp
        if "stats_storage" in rest:
            LOG.info("Inserting % rows in tblStorageStatistics" % len(rest["stats_storage"]))
            for stat in rest["stats_storage"]:
                stat["tblentities"] = uris_row["tblentities"]
                if "timestamp" not in stat:
                    continue
                cloud_utils.insert_db(db, "tblStorageStatistics", stat)
                timestamp = cloud_utils.mysql_time_to_python(stat["timestamp"])
                if timestamp > last_time:
                    last_time = timestamp
        if "stats_network" in rest:

            if uris_row["tbltableid"] == 0:
                if uris_row["entitytype"] == "server":
                    srow = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": uris_row["tblentities"]},
                                                                 order="ORDER BY id LIMIT 1"))
                    if not srow:    return
                    row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                                {"AttachedEntityId": srow["parententityid"]},
                                                                order="ORDER BY id LIMIT 1"))
                    if not row: return
                    uris_row["tbltableid"] = row["tblentities"]
                elif uris_row["entitytype"] == "serverfarm":
                    row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                                {"AttachedEntityId": uris_row["tblentities"]},
                                                                order="ORDER BY id LIMIT 1"))
                    if not row: return
                    uris_row["tbltableid"] = row["tblentities"]
                else:
                    uris_row["tbltableid"] = uris_row["tblentities"]
                uris_row["tbltablename"] = "tblEntities"

            portids = {}
            for stat in rest["stats_network"]:
                stat["tblentities"] = uris_row["tblentities"]
                if "subnet" in stat and stat["subnet"]:
                    if stat["subnet"] not in portids:
                        row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                    {"name": stat["subnet"],
                                                                     "parententityid": uris_row["tbltableid"]},
                                                                    order="ORDER BY id LIMIT 1"))
                        if row:
                            portids[stat["subnet"]] = row["id"]
                        else:
                            portids[stat["subnet"]] = 0
                    stat["tblServicePorts"] = portids[stat["subnet"]]

                if "timestamp" not in stat:
                    continue
                cloud_utils.insert_db(db, "tblNetworkStatistics", stat)
                timestamp = cloud_utils.mysql_time_to_python(stat["timestamp"])
                if timestamp > last_time:
                    last_time = timestamp
        return last_time
    except:
        cloud_utils.log_exception(sys.exc_info())


def locate_port(db, dbid, subnet, LOG=LOG):
    for int in cloud_utils.get_next_service_interface(db, dbid, LOG=LOG):
        if int["beginserviceentityid"] == dbid:
            destination_service_id = int["endserviceentityid"]
            dport_id = int["beginserviceportid"]  # this is our port
        else:
            destination_service_id = int["beginserviceentityid"]
            dport_id = int["endserviceportid"]  # this is our port

        srow = cache_utils.get_cache("db|tblEntities|id-%s" % destination_service_id, None, db_in=db,
                                     duration=STATS_DB_CACHE_TIME, LOG=LOG)
        if not srow:
            continue
        if srow["entitytype"] != "tap_network_service":
            continue
        north_service = south_service = None
        for intc in cloud_utils.get_next_service_interface(db, srow["id"], LOG=LOG):
            if intc["interfacetype"] == "tap":
                continue
            if intc["beginserviceentityid"] == dbid or intc["endserviceentityid"] == dbid:
                continue
            if intc["beginserviceentityid"] == srow["id"]:
                svc_dbid = intc["endserviceentityid"]
            else:
                svc_dbid = intc["beginserviceentityid"]
            n_svc = cache_utils.get_cache("db|tblEntities|id-%s" % svc_dbid, None, db_in=db,
                                          duration=STATS_DB_CACHE_TIME, LOG=LOG)
            if not n_svc:
                break
            if n_svc['name'] == subnet:
                return dport_id
    return 0


def compute_statisics_manager(db, uris_row, rest):
    try:
        if not rest:
            return None

        if not uris_row["statistics_time"]:
            if "timestamp" in rest:
                uris_row["statistics_time"] = cloud_utils.mysql_time_to_python(rest["timestamp"])
            else:
                return

        last_time = cloud_utils.mysql_time_to_python(uris_row["statistics_time"])

        if "stats_compute" in rest and rest["stats_compute"]:
            LOG.info("Inserting %s rows in tblComputeStatistics for %s" % (
                len(rest["stats_compute"]), uris_row["tblentities"]))
            for stat in rest["stats_compute"]:
                stat["tblentities"] = uris_row["tblentities"]
                if "timestamp" not in stat:
                    continue
                cloud_utils.insert_db(db, "tblComputeStatistics", stat, LOG=LOG)
                timestamp = cloud_utils.mysql_time_to_python(stat["timestamp"])
                if timestamp > last_time:
                    last_time = timestamp
        if "stats_storage" in rest and rest["stats_storage"]:
            LOG.info("Inserting %s rows in tblStorageStatistics for %s" % (
                len(rest["stats_storage"]), uris_row["tblentities"]))
            for stat in rest["stats_storage"]:
                stat["tblentities"] = uris_row["tblentities"]
                if "timestamp" not in stat:
                    continue
                cloud_utils.insert_db(db, "tblStorageStatistics", stat, LOG=LOG)
                timestamp = cloud_utils.mysql_time_to_python(stat["timestamp"])
                if timestamp > last_time:
                    last_time = timestamp
        if "stats_network" in rest and rest["stats_storage"]:
            LOG.info("Inserting %s rows in tblNetworkStatistics for %s" % (
                len(rest["stats_network"]), uris_row["tblentities"]))
            if uris_row["tbltableid"] == 0:
                if uris_row["entitytype"] == "server":
                    srow = cache_utils.get_cache("db|tblEntities|id|%s" % uris_row["tblentities"], None, db_in=db,
                                                 duration=STATS_DB_CACHE_TIME, LOG=LOG)
                    # srow = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": uris_row["tblentities"]},
                    #                                                                 order="ORDER BY id LIMIT 1"))
                    if not srow:    return
                    row = cache_utils.get_cache("db|tblAttachedEntities|AttachedEntityId|%s" % srow["parententityid"],
                                                None, db_in=db, duration=STATS_DB_CACHE_TIME, LOG=LOG)

                    #                    row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                    #                                                                {"AttachedEntityId": srow["parententityid"]},
                    #                                                                order="ORDER BY id LIMIT 1"))
                    if not row: return
                    uris_row["tbltableid"] = row["tblentities"]
                elif uris_row["entitytype"] == "serverfarm":

                    row = cache_utils.get_cache("db|tblAttachedEntities|AttachedEntityId|%s" % uris_row["tblentities"],
                                                None, db_in=db, duration=STATS_DB_CACHE_TIME, LOG=LOG)


                    # row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                    #                                                                {"AttachedEntityId": uris_row["tblentities"]},
                    #                                                                order="ORDER BY id LIMIT 1"))
                    if not row: return
                    uris_row["tbltableid"] = row["tblentities"]
                else:
                    uris_row["tbltableid"] = uris_row["tblentities"]
                uris_row["tbltablename"] = "tblEntities"

            portids = {}
            for stat in rest["stats_network"]:
                stat["tblentities"] = uris_row["tblentities"]
                if "subnet" in stat and stat["subnet"]:
                    if stat["subnet"] not in portids:

                        query = "db.get_row(\"tblEntities\",\" name='%s' AND parententityid = '%s' AND deleted=0  \")" % (
                            stat["subnet"], uris_row["tbltableid"])
                        row = cache_utils.get_cache(
                            "tblEntities|Name|%s|ParentEntityId|%s" % (stat["subnet"], uris_row["tbltableid"]),
                            query, db_in=db, duration=STATS_DB_CACHE_TIME, LOG=LOG)
                        # row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                        #                                                                    {"name": stat["subnet"],
                        #                                                                     "parententityid":uris_row["tbltableid"]},
                        #                                                                    order="ORDER BY id LIMIT 1"))

                        if row:
                            portids[stat["subnet"]] = row["id"]
                        else:
                            if stat["subnet"] != 'management':
                                portids[stat["subnet"]] = locate_port(db, uris_row["tbltableid"], stat["subnet"])
                                LOG.critical(
                                    _("Network stats for subnet %s id assigned:%s parent: %s" % (
                                        stat["subnet"], portids[stat["subnet"]], uris_row["tbltableid"])))
                            else:
                                portids[stat["subnet"]] = 0
                    stat["tblServicePorts"] = portids[stat["subnet"]]

                if "timestamp" not in stat:
                    continue
                cloud_utils.insert_db(db, "tblNetworkStatistics", stat, LOG=LOG)
                timestamp = cloud_utils.mysql_time_to_python(stat["timestamp"])
                if timestamp > last_time:
                    last_time = timestamp
        return last_time
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


# t2 = datetime.datetime.now()
# print "%s:  %s in : %s seconds" % (datetime.datetime.now(),db_row["name"], datetime.datetime.now() - t2)


def update_status(db, vdc, db_row, uris_row, slice_uri, slice_dbid):
    return_status = None
    try:
        if "uri" in uris_row:
            if not vdc["last_log_time"]:
                vdc["last_log_time"] = vdc["created_at"]
            if entity_constants.USER_LOGS_VIA_WEBSOCKET:

                params = None
            else:
                params = {"log": '%s' % vdc["last_log_time"]}

            rest = entity_utils.get_entity(uris_row["uri"], params=params)

            if "EntityStatus" not in rest:
                return

            if rest["EntityStatus"] == "Unavailable":
                if "http_status_code" in rest and rest[
                    "http_status_code"] == 404 and slice_dbid not in resync_slice_requests:
                    resync_slice_requests.append(slice_dbid)
                if db_row["entitytype"] == "vdc":
                    cloud_utils.update_or_insert(db, "tblEntities", rest, {"id": uris_row["tblentities"]},
                                                 child_table=entity_manager.entities[
                                                     uris_row["entitytype"]].child_table, LOG=LOG)
                return

            if "log" in rest:
                vdc["last_log_time"] = entity_utils.update_logs(db, rest, vdc["id"], vdc["last_log_time"], "tblVdcs",
                                                                vdc["child_id"])

            # updated_vdc = db.get_row_dict("tblEntities", {"id": vdc["id"]}, order="ORDER BY id LIMIT 1")
            #            if not updated_vdc or updated_vdc["EntityStatus"].lower() != "active":
            #                return
            return_status = rest["EntityStatus"]
            entity_utils.create_or_update_uri(db, db_row, uris_row["tblentities"], slice_uri, rest, uri_type="home",
                                              slice_dbid=slice_dbid, vdc_row=vdc)
            #           if "EntityStatus" in rest:
            #               return_status = rest["EntityStatus"]

            #            if "EntityStatus" in rest and rest["EntityStatus"].lower() == "active":
            # do not update status to active - in case the VDC is being deleted.
            #                del rest["EntityStatus"]
            cloud_utils.update_or_insert(db, "tblEntities", rest, {"id": uris_row["tblentities"]},
                                         child_table=entity_manager.entities[uris_row["entitytype"]].child_table,
                                         LOG=LOG)

            if return_status.lower() != "active":
                return return_status
        '''
        if "entitytype" in uris_row and uris_row["entitytype"] == "service_port":
            return return_status

#        return return_status
        if "statistics" in uris_row and uris_row["statistics"]:
            if entity_manager.entities[uris_row["entitytype"]].statistics_manager:
                #                if not uris_row["statistics_time"]:
                #                    uris_row["statistics_time"] = uris_row["created_at"]
                count = 0
                while True:
                    if not uris_row["statistics_time"]:
                        rest = entity_utils.get_entity(uris_row["statistics"])
                        update_time = True
                    else:
                        start_time = str(uris_row["statistics_time"]).replace(" ", ".")
                        rest = entity_utils.get_entity(uris_row["statistics"], params={"fromtime": '%s' % start_time})
                        update_time = False

                    last_time = entity_manager.entities[uris_row["entitytype"]].statistics_manager(db, uris_row, rest)

                    if update_time or (
                                last_time and last_time != cloud_utils.mysql_time_to_python(
                                    uris_row["statistics_time"])):
                        if last_time:
                            uris_row["statistics_time"] = cloud_utils.python_time_to_mysql(last_time)
                        cloud_utils.update_only(db, "tblUris", {"statistics_time": uris_row["statistics_time"]},
                                                {"id": uris_row["id"]}, LOG=LOG)
                        if (datetime.datetime.utcnow() - last_time).seconds < 120:
                            break
                    else:
                        break
                    count += 1
                    if count > 0:
                        break
                if count > 1:
                    LOG.critical(_("Network stats for id:%s Retries:%s" % (uris_row["tbltableid"], count )))
                db.limit_table("tblComputeStatistics", "tblEntities = '%s' " % db_row["id"], 5000, 500)
                db.limit_table("tblStorageStatistics", "tblEntities = '%s' " % db_row["id"], 5000, 500)
                db.limit_table("tblNetworkStatistics", "tblEntities = '%s' " % db_row["id"], 5000, 500)
                db.limit_table("tblServiceStatistics", "tblEntities = '%s' " % db_row["id"], 5000, 500)
        '''

    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        return None
    return return_status


def update_vdc_group_child(entity, item, slice_uri, slice_dbid):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    try:
        row = cloud_utils.lower_key(db.get_row_dict("tblUris", {"tblEntities": item["id"]},
                                                    order="ORDER BY id LIMIT 1"))
        if row:
            row["entitytype"] = item["entitytype"]
            status = update_status(db, entity, item, row, slice_uri, slice_dbid)
            if not status:
                return
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        db.close()


def update_vdc_group(entity, group, slice_uri, slice_dbid):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    try:
        row = cloud_utils.lower_key(
            db.get_row_dict("tblUris", {"tblEntities": group["id"]}, order="ORDER BY id LIMIT 1"))
        if row:
            pool = eventlet.GreenPool()
            row["entitytype"] = group["entitytype"]
            status = update_status(db, entity, group, row, slice_uri, slice_dbid)
            if not status:
                return
            for item in cloud_utils.entity_members(db, group["id"], entity_constants.profile_group_child[
                group["entitytype"]]):
                #                if item["entitystatus"].lower() == 'ready':
                #                    continue
                pool.spawn_n(update_vdc_group_child, entity, item, slice_uri, slice_dbid)
            pool.waitall()
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        db.close()


def update_vdc_groups(entity, slice_uri, slice_dbid):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    try:
        pool = eventlet.GreenPool()
        for group in entity_utils.get_next_vdc_group(db, entity["id"]):
            #            if group["entitystatus"].lower() == 'ready':
            #                continue
            pool.spawn_n(update_vdc_group, entity, group, slice_uri, slice_dbid)
        pool.waitall()
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        db.close()


def update_vdc_service(entity, service, slice_uri, slice_dbid):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    try:
        row = cloud_utils.lower_key(
            db.get_row_dict("tblUris", {"tblEntities": service["id"]}, order="ORDER BY id LIMIT 1"))
        if row:
            row["entitytype"] = service["entitytype"]
            status = update_status(db, entity, service, row, slice_uri, slice_dbid)
            if not status:
                return
                #        for port in cloud_utils.network_service_ports(db, service["id"]):
                #            row = cloud_utils.lower_key(
                #                db.get_row_dict("tblUris", {"tblEntities": port["id"]}, order="ORDER BY id LIMIT 1"))
                #            if row:
                #                row["entitytype"] = port["entitytype"]
                #                status = update_status(db, entity, port, row, slice_uri, slice_dbid)
                #                if not status:
                #                    return
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        db.close()


def update_vdc_services(entity, slice_uri, slice_dbid):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    try:
        pool = eventlet.GreenPool()
        for service in entity_utils.get_next_service(db, entity["id"]):
            if service["entitymode"].lower() != "active":
                continue
            pool.spawn_n(update_vdc_service, entity, service, slice_uri, slice_dbid)
        pool.waitall()
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        db.close()


def update_full_vdc(db, entity):
    t1 = datetime.datetime.now()
    try:
        entity = entity_utils.add_child_entity(db, entity)
        if not entity["activated_at"]:
            return
        row = cloud_utils.lower_key(
            db.get_row_dict("tblUris", {"tblEntities": entity["id"]}, order="ORDER BY id LIMIT 1"))
        if not row:
            return
        row["entitytype"] = entity["entitytype"]
        slice_uri = ""
        slice_dbid = 0
        if row:
            slice = entity_utils.get_entity_row_dict(db, {"id": row["tblslices"]})
            if slice:
                if slice["entitystatus"].lower() != "active":
                    return
                slice_uri = slice["virtual_infrastructure_url"]
                slice_dbid = slice["id"]
        status = update_status(db, entity, entity, row, slice_uri, slice_dbid)
        if not status or status.lower() != 'active':
            return
        pool = eventlet.GreenPool()
        pool.spawn_n(update_vdc_groups, entity, slice_uri, slice_dbid)
        pool.spawn_n(update_vdc_services, entity, slice_uri, slice_dbid)
        pool.waitall()
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    print "%s: VDC %s resynced in : %s seconds" % (
        datetime.datetime.now(), entity["name"], datetime.datetime.now() - t1)
    LOG.info(_("VDC %s resynced in : %s seconds" % (entity["name"], datetime.datetime.now() - t1)))


def update_partial_vdc(db, entity):
    try:
        entity = entity_utils.add_child_entity(db, entity)
        row = cloud_utils.lower_key(
            db.get_row_dict("tblUris", {"tblEntities": entity["id"]}, order="ORDER BY id LIMIT 1"))
        if not row:
            return
        row["entitytype"] = entity["entitytype"]
        slice_uri = ""
        slice_dbid = 0
        if row:
            slice = entity_utils.get_entity_row_dict(db, {"id": row["tblslices"]})
            if slice:
                if slice["entitystatus"].lower() != "active":
                    return
                slice_uri = slice["virtual_infrastructure_url"]
                slice_dbid = slice["id"]

        status = update_status(db, entity, entity, row, slice_uri, slice_dbid)
        if not status:
            return
        for group in cloud_utils.entity_children(db, entity["id"], entitytype="container"):
            if group["entitystatus"] != 'Active':
                continue
            row = cloud_utils.lower_key(
                db.get_row_dict("tblUris", {"tblEntities": group["id"]}, order="ORDER BY id LIMIT 1"))
            if row:
                row["entitytype"] = group["entitytype"]
                status = update_status(db, entity, group, row, slice_uri, slice_dbid)
                if not status:
                    return
                for item in cloud_utils.entity_members(db, group["id"], entity_constants.profile_group_child[
                    group["entitytype"]]):
                    if item["entitystatus"].lower() != "active":
                        continue
                    row = cloud_utils.lower_key(db.get_row_dict("tblUris", {"tblEntities": item["id"]},
                                                                order="ORDER BY id LIMIT 1"))
                    if row:
                        row["entitytype"] = item["entitytype"]
                        status = update_status(db, entity, item, row, slice_uri, slice_dbid)
                        if not status:
                            return
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def run_periodic_status_and_statistics():
    try:
        LOG.info(_("Start background monitor to collect stats and status"))
        time.sleep(30)
        pool = eventlet.GreenPool()
        last_update_time = datetime.datetime.now()
        while True:
            db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
            for entity in cloud_utils.get_entity(db, "vdc"):
                #                time.sleep(1)
                if entity["entitymode"].lower() == "active":
                    pool.spawn_n(update_full_vdc, db, entity)
                else:
                    count = db.get_rowcount("tblEntities", "EntityType = 'container' AND deleted=0 AND "
                                                           "EntityStatus = 'Active' AND parententityid = '%s'" % entity[
                                                "id"])
                    if count > 0:
                        pool.spawn_n(update_partial_vdc, db, entity)
            pool.waitall()

            if (datetime.datetime.now() - last_update_time).total_seconds() > 30:
                entity_utils.update_vdc_resources(db)
                last_update_time = datetime.datetime.now()

            db.close(log=None)
            time.sleep(3)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def periodic_vdc_status_and_statistics():
    while True:
        try:
            while True:
                LOG.info(_("Start/restart background monitor to collect stats and status"))
                run_periodic_status_and_statistics()
                time.sleep(10)
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


parent_entities = {"container": "volume", "serverfarm": "server"}


def update_entity(entitytype, record, parent_row, vdc_row, slice_uri, slice_dbid):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    try:
        if "name" not in record:
            LOG.critical(_("Skipping update: name not found in record: %s" % record))
            return
        if entitytype == "vdc":
            entity_row = vdc_row
        elif entitytype == "service":
            entity_row = cloud_utils.to_lower(db.get_row_dict("tblEntities", {"name": record["name"],
                                                                              "entitysubtype": "network_service",
                                                                              "parententityid": parent_row["id"]}))
            if entity_row:
                entitytype = entity_row["entitytype"]
        else:
            entity_row = cloud_utils.to_lower(db.get_row_dict("tblEntities",
                                                              {"name": record["name"], "entitytype": entitytype,
                                                               "parententityid": parent_row["id"]}))
        if not entity_row:
            LOG.critical(_("Skipping update: DB entry not found for record: %s" % record))
            return
        if entitytype in parent_entities:
            if parent_entities[entitytype] in record:
                elements = record[parent_entities[entitytype]].get("elements", {})
                for element in elements:
                    eventlet.spawn_n(update_entity, parent_entities[entitytype], element, entity_row, vdc_row,
                                     slice_uri, slice_dbid)

        if "updated_at" not in record:
            LOG.critical(_("Skipping update: No update time in record: %s" % record))
            return
        uris_row = cloud_utils.to_lower(
            db.get_row_dict("tblUris", {"tblEntities": entity_row["id"]}, order="ORDER BY id LIMIT 1"))
        if not uris_row:
            LOG.critical(_("Skipping update: No URI in database for record: %s" % record))
            return

        rest = entity_utils.get_entity(uris_row["uri"])
        if "EntityStatus" not in rest:
            LOG.critical(_("Skipping update: no responsr to URI: %s" % record))
            return
        if rest["EntityStatus"] == "Unavailable":
            if "http_status_code" in rest and rest[
                "http_status_code"] == 404 and slice_dbid not in resync_slice_requests:
                resync_slice_requests.append(slice_dbid)
            if entity_row["entitytype"] == "vdc":
                cloud_utils.update_or_insert(db, "tblEntities", rest, {"id": uris_row["tblentities"]},
                                             child_table=entity_manager.entities[entitytype].child_table, LOG=LOG)
            return
        LOG.info(_("Update record: %s" % record))
        entity_utils.create_or_update_uri(db, entity_row, uris_row["tblentities"], slice_uri, rest, uri_type="home",
                                          slice_dbid=slice_dbid, vdc_row=vdc_row)
        if "name" in rest:
            del rest["name"]

        cloud_utils.update_or_insert(db, "tblEntities", rest, {"id": uris_row["tblentities"]},
                                     child_table=entity_manager.entities[entitytype].child_table, LOG=LOG)

    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        db.close()


def vdc_changes(entity):
    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
    t1 = datetime.datetime.now()
    try:
        entity = entity_utils.add_child_entity(db, entity)
        if entity["hawkresynctime"] and (datetime.datetime.utcnow() - entity["hawkresynctime"]).total_seconds() <= \
                entity["resyncintervalseconds"]:
            return
        db.update_db("UPDATE tblVdcs SET hawkresynctime = now() WHERE id=%s  " % entity["child_id"])

        if not entity["lastresynctime"]:
            if entity["entitymode"].lower() == "active":
                entity["lastresynctime"] = entity["activated_at"]
            else:
                entity["lastresynctime"] = entity["updated_at"]

        lastresynctime = entity["lastresynctime"]

        row = cloud_utils.lower_key(
            db.get_row_dict("tblUris", {"tblEntities": entity["id"]}, order="ORDER BY id LIMIT 1"))
        if not row:
            return
        row["entitytype"] = entity["entitytype"]
        slice_uri = ""
        slice_dbid = 0
        if row:
            slice = entity_utils.get_entity_row_dict(db, {"id": row["tblslices"]})
            if slice:
                if slice["entitystatus"].lower() != "active":
                    return
                slice_uri = slice["virtual_infrastructure_url"]
                slice_dbid = slice["id"]
                if slice["resyncinprogress"] != 0 and (
                            datetime.datetime.utcnow() - slice["lastresynctime"]).total_seconds() < (10 * 60):
                    return

        rest = entity_utils.get_entity(row["uri"], params={"changes-since": '%s' % entity["lastresynctime"]})
        if "http_status_code" in rest and rest["http_status_code"] != 200:
            return
        if "records" not in rest or not rest["records"]:
            return
        pool = eventlet.GreenPool()
        for record in rest["records"]:
            elements = rest["records"][record].get("elements", {})
            for element in elements:
                pool.spawn_n(update_entity, record, element, entity, entity, slice_uri, slice_dbid)
        if "timestamp" in rest:
            db.update_db("UPDATE tblVdcs SET lastresynctime ='%s' "
                         "WHERE id=%s AND lastresynctime = '%s' " % (
                             rest["timestamp"], entity["child_id"], lastresynctime))
        pool.waitall()


    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    finally:
        update_interval = None
        if entity["entitymode"].lower() == "active":
            if entity["resyncintervalseconds"] != entity_constants.ACTIVE_VDC_SCAN_INTERVAL:
                update_interval = entity_constants.ACTIVE_VDC_SCAN_INTERVAL
        else:
            count = entity_utils.get_active_container_count(db, entity["id"])
            if count == 0:
                if entity["resyncintervalseconds"] != entity_constants.INACTIVE_VDC_SCAN_INTERVAL:
                    update_interval = entity_constants.INACTIVE_VDC_SCAN_INTERVAL
            else:
                if entity["resyncintervalseconds"] != entity_constants.INACTIVE_VDC_CONTAINERS_SCAN_INTERVAL:
                    update_interval = entity_constants.INACTIVE_VDC_CONTAINERS_SCAN_INTERVAL
        if update_interval:
            db.update_db(
                "UPDATE tblVdcs SET resyncintervalseconds = '%s' WHERE id=%s  " % (update_interval, entity["child_id"]))
        db.close()


# print "%s: VDC %s resynced in : %s seconds" % (
#        datetime.datetime.now(), entity["name"], datetime.datetime.now() - t1)
#        LOG.info(_("VDC %s resynced in : %s seconds" % (entity["name"], datetime.datetime.now() - t1)))


def run_periodic_changes():
    try:
        LOG.info(_("Start background monitor to collect updated status"))
        #        time.sleep(30)
        pool = eventlet.GreenPool()
        last_update_time = datetime.datetime.now()
        while True:
            t1 = datetime.datetime.now()
            db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
            for entity in cloud_utils.get_entity(db, "vdc"):
                pool.spawn_n(vdc_changes, entity)
            pool.waitall()
            if (datetime.datetime.now() - last_update_time).total_seconds() > 30:
                entity_utils.update_vdc_resources(db, LOG=LOG)
                last_update_time = datetime.datetime.now()
            db.close(log=None)
            print "%s: ALL vdcs resynced in : %s seconds" % (
                datetime.datetime.now(), datetime.datetime.now() - t1)
            LOG.info(_("All VDC resynced in : %s seconds" % (datetime.datetime.now() - t1)))
            time.sleep(10)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def periodic_vdc_changes():
    while True:
        try:
            while True:
                LOG.info(_("Start/restart background monitor to collect stats and status"))
                run_periodic_changes()
                time.sleep(10)
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def periodic_slice_status_resync():
    while True:
        try:
            LOG.info(_("Start background slices resync physical resources"))
            while True:
                time.sleep(30)
                with resync_slice_lock:
                    slice_updated = False
                    pool = eventlet.GreenPool()
                    t1 = datetime.datetime.now()
                    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
                    for slice in entity_utils.get_next_entity_row(db,
                                                                  "entitytype='slice' and deleted=0 and entitystatus != 'Duplicate' "):
                        if slice["resyncinprogress"] != 0 and (
                                    datetime.datetime.utcnow() - slice["lastresynctime"]).total_seconds() < (10 * 60):
                            continue
                        if slice["url"]:
                            if not slice["last_log_time"]:
                                slice["last_log_time"] = slice["created_at"]
                            if entity_constants.USER_LOGS_VIA_WEBSOCKET:
                                params = None
                            else:
                                params = {"log": '%s' % slice["last_log_time"]}

                            rest_system = rest_api.get_rest(slice["url"], params=params)

                            if "log" in rest_system:
                                slice["last_log_time"] = entity_utils.update_logs(db, rest_system, slice["id"],
                                                                                  slice["last_log_time"], "tblSlices",
                                                                                  slice["child_id"])

                            if "created_at" not in rest_system or "updated_at" not in rest_system:
                                LOG.info(_("CFD created at or updated at time changed - resync physical resources"))
                                eve = entity_functions.SliceFunctions(db, slice['id'], LOG=LOG)
                                pool.spawn_n(eve.do, db, "initialize")
                                #                                slice_updated = True
                                if slice['id'] in resync_slice_requests:
                                    resync_slice_requests.remove(slice['id'])
                                continue
                            # print "%s: ***Slices timecheck rest:%s:%s db:%s:%s" % (datetime.datetime.now(),
                            #                                                                                   rest_system["created_at"],
                            #                                                                                   rest_system["updated_at"],
                            #                                                                                   slice["slice_created_at"],
                            #                                                                                   slice["slice_updated_at"]  )
                            if slice["entitystatus"] != "Active" or \
                                            rest_system["created_at"] != unicode(slice["slice_created_at"]) or \
                                            rest_system["updated_at"] != unicode(slice["slice_updated_at"]) or \
                                            slice['id'] in resync_slice_requests:
                                db.update_db(
                                    "UPDATE tblSlices SET  slice_created_at='%s',  slice_updated_at='%s', lastresynctime=now(),  resyncinprogress=1 WHERE id= %s" % (
                                        rest_system["created_at"], rest_system["updated_at"], slice["child_id"]))

                                #                                s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
                                #                                response = s.genericPhptoPy("slice", slice['id'], "initialize", ujson.dumps({}), 0)


                                eve = entity_functions.SliceFunctions(db, slice['id'], LOG=LOG)
                                pool.spawn_n(eve.do, db, "initialize")


                                #                                slice_updated = True
                                if slice['id'] in resync_slice_requests:
                                    resync_slice_requests.remove(slice['id'])
                    pool.waitall()
                    #                    if slice_updated:
                    #                        s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
                    #                        response = s.genericPhptoPy("system", 0, "organizations", ujson.dumps({}), 0)

                    #                        eve = entity_functions.SystemFunctions(db)
                    #                        eve.do(db, "organizations")

                    db.close(log=None)
                print "%s: ***Slices resynced in : %s seconds" % (datetime.datetime.now(), datetime.datetime.now() - t1)
                LOG.info(_("Slices resynced in : %s seconds" % (datetime.datetime.now() - t1)))
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def regular_slice_resync():
    while True:
        try:
            LOG.info(_("Start background syste, resync physical resources"))
            while True:
                with resync_slice_lock:
                    t1 = datetime.datetime.now()
                    db = cloud_utils.CloudGlobalBase(LOG=LOG, log=False)
                    #                    s = xmlrpclib.ServerProxy('http://localhost:8000', allow_none=True)
                    #                    print ujson.loads(s.genericPhptoPy("system", 0, "initialize", ujson.dumps({}), 0))
                    eve = entity_functions.SystemFunctions(db)
                    eve.do(db, "initialize")
                    db.close(log=None)
                # print "%s: System resynced in : %s seconds" % (datetime.datetime.now(), datetime.datetime.now() - t1)
                LOG.info(_("System resynced in : %s seconds" % (datetime.datetime.now() - t1)))
                time.sleep(1 * 60 * 60)
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def resync_rpc(function):
    return


'''
import rpc.rpcServer

def resync_server():
    server = rpc.rpcServer.AsyncXMLRPCServer(("0.0.0.0", 8001), allow_none=True, logRequests=False)
    server.register_introspection_functions()
    server.register_function(resync_rpc)
    server.serve_forever()
'''


def cache_thread():
    cache_utils.cache_manager(LOG=LOG)


import entity.db_cleanup


def periodic_database_validation():
    while True:
        try:
            LOG.info(_("Start background task to validate database"))
            db = cloud_utils.CloudGlobalBase(log=False)
            entity.db_cleanup.system_db_validation(db)
            db.close()
            while True:
                time.sleep(3000)
        except:
            cloud_utils.log_exception(sys.exc_info())


def periodic_database_cleanup():
    try:
        LOG.info(_("Start background monitor to permanently remove deleted rows from database tables"))
        while True:
            #            with bg_lock:
            db = cloud_utils.CloudGlobalBase(log=False)
            count = db.update_db("DELETE FROM tblVdcProvisionLogs WHERE created_at < now() - interval 1 day")
            if count > 0:
                LOG.info(_("Deleted %s rows from tblVdcProvisionLogs " % count))
            delete_time = db.get_time_stamp(" NOW() - INTERVAL 60 MINUTE")['time']
            for table in FLAGS.db_tables_dict:
                if "deleted" in FLAGS.db_tables_dict[table]:
                    msg = db.update_db("DELETE from %s WHERE deleted = 1 AND deleted_at < '%s' LIMIT 50" %
                                       (table, delete_time))
                    if msg > 0:
                        LOG.info(_("Deleted %s rows %s WHERE deleted = 1 AND deleted_at < '%s' LIMIT 50" %
                                   (msg, table, delete_time)))
            db.close(log=None)
            time.sleep(3000)
    except:
        cloud_utils.log_exception(sys.exc_info())
        return None


threads = [
    #    periodic_vdc_status_and_statistics,
    #           regular_slice_resync,
    periodic_slice_status_resync,
    #          resync_server
    periodic_database_validation,
    cache_thread,
    periodic_database_cleanup,
    periodic_vdc_changes
]


def run_vdc_status():
    #    cloud_utils.create_logger("vdc-status", FLAGS.log_directory + '/vdc-status.log')
    p = multiprocessing.current_process()

    p = psutil.Process(os.getpid())
    old = p.nice()
    p.nice(10)
    new = p.nice()

    print "Old nice level %s and new nice level %s" % (old, new)
    LOG.info(_("Starting vdc status as %s pid %s - updated from default pri %s to %s" % (p.name, p.pid, old, new)))

    time.sleep(10)
    # set up mysql pool
    db = cloud_utils.CloudGlobalBase(LOG=LOG)
    db.close()

    instances = []
    for t in threads:
        instances.append(cloud_utils.RunForEverThread(target=t, name=t.func_name, LOG=LOG))
    for t in instances:
        t.start()
    for t in instances:
        t.join()


if __name__ == "__main__":

    syslog.syslog("%s at Pid %s is started" % (os.path.basename(__file__), os.getpid()))
    cloud_utils.kill_priors(os.path.basename(__file__))
    cloud_utils.bash_command_no_exception("mkdir -p  /var/log/cloudflow")
    cloud_utils.bash_command_no_exception("mkdir -p /var/log/cloudflow/previous")
    cloud_utils.setup_flags_logs('vdc-status.log')
    print "Starting Hawk Resync"
    while True:
        try:
            run_vdc_status()
        except:
            syslog.syslog("%s at Pid %s is being restarted " % (os.path.basename(__file__), os.getpid()))
            cloud_utils.sys_log_exception(sys.exc_info())
        time.sleep(5)
