#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import gflags
import gettext
import time
import eventlet

import json
import datetime
import eventlet.corolocal

import ujson
import yurl

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

LOG = logging.getLogger()

import utils.cloud_utils as cloud_utils
import rest.rest_api as rest_api
from utils.underscore import _
import entity_manager
import entity_constants
import utils.cache_utils
import utils.publish_utils
import utils.cache_utils as cache_utils

FLAGS = gflags.FLAGS


def add_periodic_check(db, job):
    try:
        '''
        if "return_object" in job and isinstance(job["return_object"], list) and "jobid" in job["return_object"][-1]:
            jobid = job["return_object"][-1]["jobid"]
        else:
            add = {"entitytype": "job_queue", "parententityid": job["dbid"], "deleted": 0,
                   "command": ujson.dumps({"command": "status"}), "status": "Started",
                   "jobserviceentityid": job["dbid"]}
            jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None, child_table="tblJobsQueue")

        if "entity" not in job or job["entity"] is None:
            entity = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" % job["dbid"],
                                                  order="ORDER BY id LIMIT 1"))
        job.update({"jobid": jobid})
        '''
        #        LOG.info(_("Periodic status check - Adding a new thread %s" % str(job)))
        eventlet.spawn_n(periodic_check, job)
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_and_update_entity(db, url, dbid):
    rest_me = get_entity(url)
    if rest_me["EntityStatus"].lower() not in http_error_states:
        if "uri" in rest_me:
            db_row = read_partial_entity(db, dbid)
            update_only_uri(db, db_row, dbid, rest_me, url)
    return rest_me


def update_rest_and_job(db, job, entitytype):
    user_action_row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                            {"ParentEntityId": job["dbid"],
                                                             "EntityType": "user_action"},
                                                            order="ORDER BY id LIMIT 1"))
    if user_action_row:
        LOG.info(_("Cancel command detected for dbid:  %s" % job["dbid"]))
        status = user_action_row["name"]
        update_entity_status(db, job, {"EntityStatus": "Aborted"}, "Aborted:UserCancel", entitytype)
        db.delete_rows_dict("tblEntities", {"id": user_action_row["id"]})
        return None
    rest_me = get_and_update_entity(db, job["url"], job["dbid"])
    if rest_me["EntityStatus"].lower() not in entity_manager.entities[entitytype].entity_pending_states:
        if rest_me["EntityStatus"].lower() in entity_manager.entities[entitytype].entity_failed_states:
            status = "failed"
        else:
            status = "success"
        update_entity_status(db, job, {"EntityStatus": rest_me["EntityStatus"]}, status, entitytype)
    return rest_me


def wait_for_volume_update(job, pdbid, options):
    try:
        greenthreadid = eventlet.corolocal.get_ident()
        LOG.info(_("Starting VOLUME periodic check job:%s in eventlet-threadid=%s" % (str(job), greenthreadid)))
        iterations = 0
        volume_name = options["entity_name"]
        volume_type = options["command"]
        volume_group = volume_type + "s"
        status = "completed"
        entitytype = "volume"
        sleeptime = entity_manager.entities[entitytype].periodic_status_check_time

        while True:
            time.sleep(sleeptime)
            db = cloud_utils.CloudGlobalBase(log=False)

            rest_me = update_rest_and_job(db, job, entitytype)
            rest_elements = get_entity_dict(db, rest_me, volume_group)
            url = None
            for name, uri in rest_elements.iteritems():
                if name == volume_name:
                    url = uri
                    break
            if not url:
                if "http_status_code" not in rest_me or rest_me["http_status_code"] != 200:
                    db.close()
                    break
                    #                if rest_me["EntityStatus"].lower() not in entity_manager.entities[job["entitytype"]].entity_pending_states:
                    #                    db.close()
                    #                    break
            else:
                primary_volume_uri = cloud_utils.lower_key(db.get_row_dict("tblUris", {"tblEntities": pdbid},
                                                                           order="ORDER BY id LIMIT 1"))
                if not primary_volume_uri:
                    db.close()
                    break

                slice_row = cloud_utils.lower_key(
                    db.get_row_dict("tblSlices", {"tblEntities": primary_volume_uri["tblslices"]},
                                    order="ORDER BY id LIMIT 1"))
                if not slice_row:
                    db.close()
                    break
                url = slice_row["virtual_infrastructure_url"] + url
                item_rest = rest_api.get_rest(url)
                if "http_status_code" not in item_rest or item_rest["http_status_code"] != 200:
                    db.close()
                    break

                if "entity_description" in options:
                    item_rest["description"] = options["entity_description"]

                item_rest["parententityid"] = pdbid
                item_rest["volume_type"] = volume_type
                item_rest["entitytype"] = volume_type

                if "resource_state" in item_rest and "state" in item_rest["resource_state"]:
                    item_rest["entitystatus"] = item_rest["resource_state"]["state"]

                new_dbid = cloud_utils.update_or_insert(db, "tblEntities", item_rest, {"parententityid": pdbid,
                                                                                       "entitytype": volume_type,
                                                                                       "name": volume_name},
                                                        child_table=entity_manager.entities[volume_type].child_table)

                db_row = read_partial_entity(db, new_dbid)
                create_or_update_uri(db, db_row, new_dbid, slice_row["virtual_infrastructure_url"], item_rest,
                                     uri_type="home", slice_dbid=slice_row["tblentities"])

                if item_rest["entitystatus"].lower() in entity_manager.entities[entitytype].entity_pending_states:
                    job["dbid"] = new_dbid
                    job["url"] = url
                    job["entitytype"] = volume_type
                    status = "pending"
                else:
                    status = "completed"
                db.close()
                break

            iterations += 1
            if iterations > entity_manager.entities[entitytype].periodic_max_status_check_iterations:
                update_entity_status(db, job, {"EntityStatus": "Aborted"}, "Aborted:RetryCount", entitytype)
                LOG.warn(_("Periodic status check iteration count expired for %s" % str(job)))
                status = "completed"
                db.close(log=None)
                break
            db.close()

        return status
    except:
        cloud_utils.log_exception(sys.exc_info())


def periodic_check(job):
    try:
        iterations = 0
        rest_me = None
        status = "failed"
        pdbid = job["dbid"]
        return_object = None
        vdc_dashboard = None
        entity = job["entity"]
        entitytype = entity["entitytype"]
        options = None
        status = "pending"
        final_state = None
        params = None
        vdc_row = None
        if entitytype in entity_constants.vdc_children:
            db = cloud_utils.CloudGlobalBase(log=False)
            vdc_row = read_full_entity(db, entity["parententityid"])
            db.close()
        elif entitytype in entity_constants.vdc_grandchildren:
            db = cloud_utils.CloudGlobalBase(log=False)
            parent = read_partial_entity(db, entity["parententityid"])
            if parent:
                vdc_row = read_full_entity(db, parent["parententityid"])
            db.close()

        if "return_object" in job and job["return_object"] and isinstance(job["return_object"], list):
            return_object = job["return_object"][-1]

            if "dbid" in return_object:
                pdbid = return_object["dbid"]

            if "dashboard" in return_object:
                vdc_dashboard = return_object["dashboard"]
                vdc_row = vdc_dashboard.vdc_row

            if "options" in return_object:
                options = return_object["options"]

            if "final_state" in return_object:
                final_state = return_object["final_state"]

            if "entitytype" in return_object:
                entitytype = return_object["entitytype"]

            if entitytype == "volume":
                if "command" in return_object and return_object["command"] == "snapshot":
                    status = wait_for_volume_update(job, pdbid, return_object)
                    utils.publish_utils.publish(entity["id"], {
                        "update_status": {"dbid": entity["id"], "status": entity["entitystatus"]}})
                    if status == "pending":
                        pdbid = job["dbid"]
                        entitytype = job["entitytype"]

        if vdc_row and not entity_constants.USER_LOGS_VIA_WEBSOCKET:
            params = {"log": '%s' % vdc_row["last_log_time"]}

        greenthreadid = eventlet.corolocal.get_ident()
        LOG.info(_("Starting periodic check job:%s in eventlet-threadid=%s" % (str(job)[:200], greenthreadid)))

        while status == "pending":
            time.sleep(entity_manager.entities[entitytype].periodic_status_check_time)
            db = cloud_utils.CloudGlobalBase(log=False)

            user_action_row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                    {"ParentEntityId": pdbid,
                                                                     "EntityType": "user_action"},
                                                                    order="ORDER BY id LIMIT 1"))
            if user_action_row:
                LOG.info(_("Cancel command detected for dbid:  %s" % pdbid))
                status = user_action_row["name"]
                update_entity_status(db, job, {"EntityStatus": "Aborted"}, "Aborted:UserCancel", entitytype)
                db.delete_rows_dict("tblEntities", {"id": user_action_row["id"]})
                db.close(log=None)
                break

            rest_me = get_entity(job["url"], params=params)

            # if "resource_state" in rest_me and "Messages" in rest_me["resource_state"]:
            #                if vdc_dashboard:
            #                    vdc_dashboard.service_messages = []
            #                for message in reversed(rest_me["resource_state"]["Messages"]):
            #                    update_status_messages(db, job["jobid"], job["dbid"], message.get("created", cloud_utils.mysql_now() ), message.get("text", ""))
            #                    if vdc_dashboard:
            #                        vdc_dashboard.service_messages.append(message)
            if return_object:
                return_object["response"] = rest_me
            if vdc_dashboard:
                if "resource_state" in rest_me:
                    if "progress" in rest_me["resource_state"]:
                        vdc_dashboard.service_progress = rest_me["resource_state"]["progress"]
                    vdc_dashboard.service_last_report_time = cloud_utils.mysql_now()

                vdc_dashboard.register_event(db)
                vdc_dashboard.service_messages = []

            if "log" in rest_me:
                vdc_row["last_log_time"] = update_logs(db, rest_me, vdc_row["id"],
                                                       vdc_row["last_log_time"],
                                                       "tblVdcs", vdc_row["child_id"])
                params = {"log": '%s' % vdc_row["last_log_time"]}

            if rest_me["EntityStatus"].lower() in http_error_states:
                if entity["entitymode"].lower() == "deprovisioning" or entity["entitymode"].lower() == "deleting":
                    status = "success"
            else:
                if "uri" in rest_me:
                    db_row = read_partial_entity(db, job["dbid"])
                    #                    update_only_uri(db, db_row, job["dbid"], rest_me, job["url"])
                    create_or_update_uri(db, db_row, job["dbid"], job["slice_uri"], rest_me, job["slice_dbid"],
                                         uri_type="home", vdc_row=vdc_row)
                    entity_manager.entities[entitytype].post_rest_get_function(db, job["dbid"], rest_me, rest='get')
                if rest_me["EntityStatus"].lower() not in entity_manager.entities[entitytype].entity_pending_states:
                    if rest_me["EntityStatus"].lower() in entity_manager.entities[entitytype].entity_failed_states:
                        status = "failed"
                    else:
                        if final_state:
                            if rest_me["EntityStatus"].lower() == final_state.lower():
                                status = "success"
                        else:
                            status = "success"
            updated = {"EntityStatus": rest_me["EntityStatus"]}
            if "uuid" in rest_me:
                updated["uuid"] = rest_me["uuid"]
                updated["entitytype"] = entitytype
            update_entity_status(db, job, updated, status, entitytype)
            if status != "pending":
                db.close(log=None)
                break

            iterations += 1
            if iterations > entity_manager.entities[entitytype].periodic_max_status_check_iterations:
                update_entity_status(db, job, {"EntityStatus": "Aborted"}, "Aborted:RetryCount", entitytype)
                LOG.critical(_("Periodic status check iteration count expired for %s" % str(job)))
                db.close(log=None)
                status = "failed"
                break
            db.close(log=None)

        LOG.info(_("Ending periodic check - Removing eventlet-threadid=%s status = %s " % (greenthreadid, status)))
        if "callback" in job:
            if job["callback"]:
                eventlet.spawn_n(job["callback"], job["dbid"], return_status=status, return_object=job["return_object"])

    except:
        cloud_utils.log_exception(sys.exc_info())


def read_partial_entity(db, dbid):
    return cloud_utils.lower_key(
        db.get_row_dict("tblEntities", {"id": dbid, "deleted": 0}, order="ORDER BY id LIMIT 1"))


def read_remaining_entity(db, dbid, row):
    if not row:
        return

    if row["entitytype"] in entity_manager.entities.keys():
        child_table = entity_manager.entities[row["entitytype"]].child_table
        if child_table:
            child_row = cloud_utils.lower_key(db.get_row_dict(child_table, {"tblEntities": dbid},
                                                              order="ORDER BY id LIMIT 1"))
            if "id" in child_row:
                child_row["child_id"] = child_row.pop("id")
            row.update(child_row)
    return row


def read_full_entity(db, dbid):
    entity, status = read_full_entity_status_tuple(db, dbid)
    return entity


def read_full_entity_status_tuple(db, dbid):
    row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": dbid, "deleted": 0}, order="ORDER BY id LIMIT 1"))
    if not row:
        return None, "Database read entity error"
    if row["entitytype"] in entity_manager.entities.keys():
        child_table = entity_manager.entities[row["entitytype"]].child_table
        if child_table:
            child_row = cloud_utils.lower_key(db.get_row_dict(child_table, {"tblEntities": dbid},
                                                              order="ORDER BY id LIMIT 1"))
            if child_row:
                if "id" in child_row:
                    child_row["child_id"] = child_row.pop("id")
                row.update(child_row)
    return row, None


def delete_entity_recursively(db, dbid):
    for entity in cloud_utils.entity_children(db, dbid):
        delete_entity_recursively(db, entity['id'])
    # check for URIs and delete it in CFD and in database
    db.execute_db("DELETE FROM tblAttachedEntities WHERE attachedentityid='%s'" % dbid)
    db.delete_rows_dict("tblEntities", {"id": dbid})
    db.delete_rows_dict("tblUris", {"tblEntities": dbid})
    db.delete_rows_dict("tblEntityDetails", {"tblEntities": dbid})
    db.delete_rows_dict("tblJobsQueue", {"tblEntities": dbid})


'''
def update_status_messages(db, jobid, dbid, created_at, message):
    try:
        id = db.execute_db("SELECT * FROM tblLogs WHERE tblEntities = '%s' "
                           "AND ParentEntityId = '%s' "
                           "AND created_at = '%s' "
                           "AND Message = '%s' " % (jobid, dbid, created_at, message))
        if not id:
            cloud_utils.log_message(db, dbid, message, created_at=created_at, source="Slice")
    except:
        cloud_utils.log_exception(sys.exc_info())
'''


def update_entity_status(db, job, rest_me, status, entitytype):
    try:
        v = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" % job["dbid"],
                                             order="ORDER BY id LIMIT 1"))
        if v:
            cloud_utils.update_only(db, "tblEntities", rest_me, {"id": job["dbid"]},
                                    child_table=entity_manager.entities[entitytype].child_table)
        if entity_manager.entities[entitytype].post_entity_final_status_function:
            entity_manager.entities[entitytype].post_entity_final_status_function(db, job["dbid"])

            #       cloud_utils.update_only(db, "tblEntities",
            #                                {"progress": 100, "status": status, "response": ujson.dumps(rest_me)},
            #                                {"id": job["jobid"]}, child_table="tblJobsQueue")
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_entity_dict(db, rest_elements, element_type):
    elements = {}
    try:
        if rest_elements and element_type in rest_elements:
            if "total" in rest_elements[element_type] and rest_elements[element_type]["total"] > 0 and \
                            "elements" in rest_elements[element_type]:
                for item in rest_elements[element_type]["elements"]:
                    if "uri" in item and "name" in item:
                        elements[item["name"]] = item["uri"]
                    else:
                        LOG.critical(_("Name or URI missing in type:%s response: %s" % (element_type, rest_elements)))
        else:
            LOG.critical(_("get_entity_dict - No child elements of type:%s in: %s" % (element_type, rest_elements)))
            return None
        return elements
    except:
        cloud_utils.log_exception(sys.exc_info())
    return elements


def get_dbid_keys(db, dbid):
    keys = []
    try:
        current_index = 0
        while True:
            row = cloud_utils.lower_key(
                db.get_row("tblSSHPublicKeys", "tblEntities = '%s' AND id > '%s'" % (dbid, current_index),
                           order="ORDER BY id LIMIT 1"))
            if row:
                current_index = row['id']
                keys.append({"name": row["name"], "key": row["public_key"]})
            else:
                break
    except:
        cloud_utils.log_exception(sys.exc_info())
    return keys


def add_ssh_keys(db, dbid, j):
    try:
        keys = get_dbid_keys(db, dbid)
        current_index = 0
        while True:
            tmp = db.execute_db("SELECT * FROM tblAttachedEntities  "
                                " WHERE ( tblEntities = '%s' AND AttachedEntityType = 'ssh_user' AND id > '%s'  ) LIMIT 1" % (
                                    dbid, current_index))
            if not tmp:
                break
            current_index = tmp[0]['id']
            keys.extend(get_dbid_keys(db, tmp[0]["AttachedEntityId"]))
        # if keys:
        j.update({"ssh_keys": keys})
    except:
        cloud_utils.log_exception(sys.exc_info())


def json_metadata_keyvalue(db, dbid):
    response = []
    for kv in cloud_utils.get_generic(db, "tblKeyValuePairs", "tblEntities", dbid):
        response.append({"key": kv["thekey"], "value": kv["thevalue"]})
    return response


def get_entity_uri(db, dbid, entity, slice_row=None):
    uritype = "home"
    uri_row = cloud_utils.lower_key(db.get_row_dict("tblUris", {"tblEntities": dbid,
                                                                "type": uritype,
                                                                "deleted": 0},
                                                    order="ORDER BY id LIMIT 1"))
    if not uri_row:
        if entity["entitytype"] == "organization" and slice_row:
            return slice_row["virtual_infrastructure_url"], None
        LOG.critical(_("Unable to locate URI for tblEntities id %s" % dbid))
        return None, "Unable to locate entity URI in tblUris database"

    if not slice_row:
        slice_row = cloud_utils.lower_key(db.get_row_dict("tblSlices", {"tblEntities": uri_row["tblslices"]},
                                                          order="ORDER BY id LIMIT 1"))
        if not slice_row:
            LOG.critical(
                _("Unable to locate slice for tblEntities  uriid %s entity id  %s" % (uri_row["id"], dbid)))
            return None, "Unable to locate entry URI in tblslices in database"

    return uri_row["uri"], None


def build_entity(db, dbid, row=None):
    if not row:
        row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": dbid}, order="ORDER BY id LIMIT 1"))
        if not row:
            return None
    j = {"name": row["name"], "description": row["description"], "uuid": row["uniqueid"]}
    if "email" in row:
        j["email"] = row["email"]
    if "administrator" in row:
        j["administrator"] = row["administrator"]
    if "location" in row:
        j["location"] = row["location"]
    add_ssh_keys(db, dbid, j)
    if "user_data" in row and row["user_data"]:
        j["user_data"] = row["user_data"]
    entity_manager.add_user_data(db, dbid, j)
    return j


def post_entity_on_parent(db, dbid, element, slice_home, parent_uri, options=None):
    rest_element = {}
    try:
        if slice_home and parent_uri:
            j = build_entity(db, dbid)
            if not j:
                return {}
            if options and "newname" in options:
                j["name"] = options["newname"]
            return post_entity(j, element, slice_home + parent_uri)
    except:
        cloud_utils.log_exception(sys.exc_info())
        rest_element = {}
    return rest_element


def build_put_entity(db, dbid, element, url, options=None):
    if url:
        j = build_entity(db, dbid)
        if not j:
            return {}
        if options and "newname" in options:
            j["name"] = options["newname"]

        return put_entity(j, element, url)
    return {}


http_error_states = ["unavailable"]


def post_entity(entity, entitytype, url):
    rest_element = {}
    try:
        rest_element = rest_api.post_rest(url, entity, headers={"Content-type":
                                                                    "application/cloudflow.net.cloud.%s+json" %
                                                                    entity_manager.entitytype_rest(entitytype)})
        if "resource_state" in rest_element.keys() and "state" in rest_element["resource_state"].keys():
            rest_element["EntityStatus"] = rest_element["resource_state"]["state"]
        elif "http_status_code" in rest_element.keys() and rest_element["http_status_code"] != 200:
            rest_element["EntityStatus"] = "Unavailable"
    except:
        cloud_utils.log_exception(sys.exc_info())
        rest_element = {"EntityStatus": "Unavailable", "http_status_code": 500}
    return rest_element


def put_entity(entity, entitytype, url):
    rest_element = {}
    try:
        rest_element = rest_api.put_rest(url, entity, headers={"Content-type":
                                                                   "application/cloudflow.net.cloud.%s+json" %
                                                                   entity_manager.entitytype_rest(entitytype)})
        if "resource_state" in rest_element.keys() and "state" in rest_element["resource_state"].keys():
            rest_element["EntityStatus"] = rest_element["resource_state"]["state"]
        elif "http_status_code" in rest_element.keys() and rest_element["http_status_code"] != 200:
            rest_element["EntityStatus"] = "Unavailable"
    except:
        cloud_utils.log_exception(sys.exc_info())
        rest_element = {"EntityStatus": "Unavailable", "http_status_code": 500}
    return rest_element


def get_entity(url, params=None):
    rest_element = {}
    try:
        rest_element = rest_api.get_rest(url, params)
        if "resource_state" in rest_element.keys() and "state" in rest_element["resource_state"].keys():
            rest_element["EntityStatus"] = rest_element["resource_state"]["state"]
        elif "http_status_code" in rest_element.keys() and rest_element["http_status_code"] != 200:
            rest_element["EntityStatus"] = "Unavailable"
    except:
        cloud_utils.log_exception(sys.exc_info())
        rest_element = {"EntityStatus": "Unavailable", "http_status_code": 500}
    return rest_element


def delete_entity(url):
    rest_element = {}
    try:
        rest_element = rest_api.delete_rest(url)
        if "resource_state" in rest_element.keys() and "state" in rest_element["resource_state"].keys():
            rest_element["EntityStatus"] = rest_element["resource_state"]["state"]
        elif "http_status_code" in rest_element.keys() and rest_element["http_status_code"] != 200:
            rest_element["EntityStatus"] = "Unavailable"
    except:
        cloud_utils.log_exception(sys.exc_info())
        rest_element = {"EntityStatus": "Unavailable", "http_status_code": 500}
    return rest_element


def confirm_options_keys(dict_name, items_list):
    if not dict_name:
        return "No required parameters provided"
    for item in items_list:
        if item not in dict_name.keys():
            return "Required parameter %s missing" % item
    return None


import threading

name_lock = threading.RLock()


def create_entity_name(db, entitytype):
    id = db.execute_db("SELECT MAX(id) FROM tblEntities")
    if entitytype:
        prefix = entity_manager.entities[entitytype].default_entity_name_prefix
    else:
        prefix = ""
    return prefix + str(id[0]["MAX(id)"]) + "-" + cloud_utils.get_random_string(4)


def create_postfix(db):
    id = db.execute_db("SELECT MAX(id) FROM tblEntities")
    return str(id[0]["MAX(id)"]) + "-" + cloud_utils.get_random_string(4)


def create_addresses(rest):
    addresses = None
    if "addresses" in rest and isinstance(rest["addresses"], list):
        addresses = []
        for adr in rest["addresses"]:
            if adr.get("network") == "vdc-management":
                continue
            adrs = {}
            adrs["Interface"] = adr.get("network")
            adrs["MAC Address"] = adr.get("mac_address")
            adrs["IP Address"] = adr.get("ip_address")
            adrs["DNS Name"] = adr.get("dns_name")
            if not adrs["Interface"] or not adrs["MAC Address"]:
                LOG.info(_("rest has invalid addresses %s" % rest))
            if "nat" in adr:
                external_addresses = []
                for extr in adr["nat"]:
                    exts = {}
                    exts["NAT Service"] = extr.get("nat_service")
                    exts["IP Address"] = extr.get("ip_address")
                    exts["DNS Name"] = extr.get("dns_name")
                    external_addresses.append(exts)
                adrs["External Addresses"] = external_addresses
            addresses.append(adrs)
    return addresses


def create_or_update_service_details(db, dbid, rest, slice_dbid=0):
    try:
        if not isinstance(rest, dict):
            return
        entity = []
        entity.append({"Name": rest.get("name")})
        entity.append({"Status": rest.get("EntityStatus")})
        if rest.get("novnc_url"):
            entity.append({"Web Console": rest.get("novnc_url")})
        defaut_throughput = 100
        if "params" in rest:
            params = rest["params"]
            if "max_instances_count" in params and "throughput" in params:
                entity.append({"Provisioned": (params["max_instances_count"] * params["throughput"])})
                defaut_throughput = params["throughput"]
        if "service_status" in rest and "current_instances_count" in rest["service_status"]:
            entity.append({"Deployed": (rest["service_status"]["current_instances_count"] * defaut_throughput)})

        addresses = create_addresses(rest)
        if addresses:
            entity.append({"Network Addresses": addresses})
        details = ujson.dumps(entity)
        #        details = db.escape_string(details)
        cloud_utils.update_or_insert(db, "tblEntityDetails", {"details": details, "tblEntities": dbid},
                                     {"tblEntities": dbid})

        if "cfm" in rest:
            if slice_dbid != 0:
                row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": slice_dbid,
                                                                            "entitysubtype": "slice_network_entity",
                                                                            "name": rest['cfm']},
                                                            order="ORDER BY id LIMIT 1"))
                if row:
                    cloud_utils.update_or_insert(db, "tblAttachedEntities", {"tblentities": row["id"],
                                                                             "attachedentityid": dbid,
                                                                             "attachedentitytype": "physical"},
                                                 {"tblentities": row["id"],
                                                  "attachedentityid": dbid,
                                                  "attachedentitytype": "physical"})
        else:
            db.execute_db(
                "DELETE FROM tblAttachedEntities WHERE attachedentityid='%s' AND attachedentitytype='physical' " % dbid)

    except:
        cloud_utils.log_exception(sys.exc_info())


def create_or_update_server_details(db, dbid, rest, slice_dbid=0):
    if not isinstance(rest, dict):
        return
    if "console_log" in rest:
        cloud_utils.update_or_insert(db, "tblConsoleLog",
                                     {"console_log": db.escape_string(rest["console_log"]), "tblEntities": dbid},
                                     {"tblEntities": dbid})
    entity = []
    entity.append({"Name": rest.get("name")})
    entity.append({"Server Farm": rest.get("serverfarm")})
    entity.append({"Compute Service": rest.get("compute_service")})

    entity.append({"Status": rest.get("EntityStatus")})
    entity.append({"Web Console": rest.get("novnc_url")})
    entity.append({"VNC Java Console": rest.get("xvpvnc_url")})
    addresses = create_addresses(rest)
    if addresses:
        entity.append({"Network Addresses": addresses})

    entity.append({"VM State": rest.get("vm_state")})
    entity.append({"Task State": rest.get("task_state")})
    entity.append({"UUID": rest.get("uuid")})

    entity.append({"Fault Code": rest.get("fault_code")})
    entity.append({"Fault Details": db.escape_string(rest.get("fault_details", ""))})
    entity.append({"Fault Message": db.escape_string(rest.get("fault_message", ""))})

    details = ujson.dumps(entity)
    #    details = db.escape_string(details)
    cloud_utils.update_or_insert(db, "tblEntityDetails", {"details": details, "tblEntities": dbid},
                                 {"tblEntities": dbid})

    if "host" in rest:
        if slice_dbid != 0:
            row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": slice_dbid,
                                                                        "entitytype": "slice_compute_entity",
                                                                        "name": rest['host']},
                                                        order="ORDER BY id LIMIT 1"))
            if row:
                cloud_utils.update_or_insert(db, "tblAttachedEntities", {"tblentities": row["id"],
                                                                         "attachedentityid": dbid,
                                                                         "attachedentitytype": "physical"},
                                             {"tblentities": row["id"],
                                              "attachedentityid": dbid,
                                              "attachedentitytype": "physical"})
    else:
        db.execute_db(
            "DELETE FROM tblAttachedEntities WHERE attachedentityid='%s' AND attachedentitytype='physical' " % dbid)

    pass
    '''
    entity = [

        {"Server Farm":},
        {"Status":},

        {"VM status":},
        {"Task status":},
        {"uuid":},
        {"Created at":},
        {"Web Console":},
        {"VNC Jave Console":},
        {"Internal IP Address":},
        {"Mac Address":},
        {"Public IP Address":},
        {"Internal DNS Name":},
        {"External DNS Name":},
    ]
    '''


def create_or_update_serverfarm_details(db, dbid, rest, slice_dbid=0):
    if not isinstance(rest, dict):
        return

    entity = []
    entity.append({"Name": rest.get("name")})
    entity.append({"Compute Service": rest.get("compute_service")})
    entity.append({"Status": rest.get("EntityStatus")})

    count = db.get_rowcount("tblEntities", "entitytype='server' AND parententityid=%s AND deleted=0" % dbid)
    entity.append({"Provisioned": count})
    count = db.get_rowcount("tblEntities",
                            "entitytype='server' AND parententityid=%s AND LOWER(entitystatus) ='active' AND deleted=0" % dbid)
    entity.append({"Deployed": count})

    details = ujson.dumps(entity)
    #    details = db.escape_string(details)
    cloud_utils.update_or_insert(db, "tblEntityDetails", {"details": details, "tblEntities": dbid},
                                 {"tblEntities": dbid})


def create_or_update_container_details(db, dbid, rest, slice_dbid=0):
    try:
        if not isinstance(rest, dict):
            return

        entity = []
        entity.append({"Name": rest.get("name")})
        entity.append({"Storage Service": rest.get("storage_service", "None")})
        entity.append({"Status": rest.get("EntityStatus")})

        count = db.get_rowcount("tblEntities", "entitytype='volume' AND parententityid=%s AND deleted=0" % dbid)
        entity.append({"Provisioned": count})
        count = db.get_rowcount("tblEntities",
                                "entitytype='volume' AND parententityid=%s AND LOWER(entitystatus) ='active' AND deleted=0" % dbid)
        entity.append({"Deployed": count})

        details = ujson.dumps(entity)
        #        details = db.escape_string(details)
        cloud_utils.update_or_insert(db, "tblEntityDetails", {"details": details, "tblEntities": dbid},
                                     {"tblEntities": dbid})
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_or_update_volume_details(db, dbid, rest, slice_dbid=0):
    try:
        if not isinstance(rest, dict):
            return

        entity = []
        entity.append({"Name": rest.get("name")})
        entity.append({"Container": rest.get("container")})
        entity.append({"Storage Service": rest.get("storage_servicei", "None")})

        entity.append({"Status": rest.get("EntityStatus")})
        entity.append({"UUID": rest.get("uuid")})

        details = ujson.dumps(entity)
        #        details = db.escape_string(details)
        cloud_utils.update_or_insert(db, "tblEntityDetails", {"details": details, "tblEntities": dbid},
                                     {"tblEntities": dbid})

        if "storage" in rest:
            if slice_dbid != 0:
                row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": slice_dbid,
                                                                            "entitytype": "slice_storage_entity",
                                                                            "name": rest['storage']},
                                                            order="ORDER BY id LIMIT 1"))
                if row:
                    cloud_utils.update_or_insert(db, "tblAttachedEntities", {"tblentities": row["id"],
                                                                             "attachedentityid": dbid,
                                                                             "attachedentitytype": "physical"},
                                                 {"tblentities": row["id"],
                                                  "attachedentityid": dbid,
                                                  "attachedentitytype": "physical"})
        else:
            db.execute_db(
                "DELETE FROM tblAttachedEntities WHERE attachedentityid='%s' AND attachedentitytype='physical' " % dbid)
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_or_update_compute_details(db, dbid, rest):
    try:
        if not isinstance(rest, dict):
            return
        entity = []
        entity.append({"Name": rest.get("name")})
        entity.append({"Status": rest.get("EntityStatus")})

        clusters = db.get_multiple_row("tblAttachedEntities", "AttachedEntityType='serverfarm' AND "
                                                              "tblEntities=%s " % dbid)
        pcount = dcount = 0
        for cluster in clusters:
            pcount += db.get_rowcount("tblEntities", "entitytype='server' AND "
                                                     "parententityid=%s AND deleted=0" % cluster["AttachedEntityId"])
            dcount += db.get_rowcount("tblEntities", "entitytype='server' AND "
                                                     "parententityid=%s AND LOWER(entitystatus) ='active' "
                                                     "AND deleted=0" % cluster["AttachedEntityId"])
        entity.append({"Provisioned": pcount})
        entity.append({"Deployed": dcount})
        details = ujson.dumps(entity)
        #        details = db.escape_string(details)
        cloud_utils.update_or_insert(db, "tblEntityDetails", {"details": details, "tblEntities": dbid},
                                     {"tblEntities": dbid})
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_or_update_entity_details(db, db_row, dbid, rest, slice_dbid=0):
    if not db_row:
        db_row = read_partial_entity(db, dbid)
    if not db_row:
        return
    if db_row["entitytype"] == "server":
        create_or_update_server_details(db, dbid, rest, slice_dbid)
    elif db_row["entitytype"] == "serverfarm":
        create_or_update_serverfarm_details(db, dbid, rest)
    elif db_row["entitytype"] == "compute_network_service":
        create_or_update_compute_details(db, dbid, rest)
    elif db_row["entitysubtype"] == "network_service":
        create_or_update_service_details(db, dbid, rest, slice_dbid)
    elif db_row["entitytype"] == "container":
        create_or_update_container_details(db, dbid, rest, slice_dbid)
    elif db_row["entitytype"] == "volume":
        create_or_update_volume_details(db, dbid, rest, slice_dbid)


def create_or_update_uri(db, db_row, dbid, slice_uri, rest, slice_dbid=0, uri_type="home", vdc_row=None):
    try:
        if "uri" in rest and rest["uri"]:

            update = {"tblEntities": dbid, "tblSlices": slice_dbid, "type": uri_type}

            if not db_row or db_row["entitytype"] not in entity_constants.physical_entitytypes:
                update["uri"] = slice_uri + rest["uri"]

            if uri_type == "home":
                if "novnc_url" in rest:
                    rest["novnc_url"] = cloud_utils.update_user_url(rest["novnc_url"], slice_uri)
                update["rest_response"] = json.dumps(rest)
                create_or_update_entity_details(db, db_row, dbid, rest, slice_dbid=slice_dbid)
            if "statistics" in rest:
                update["statistics"] = slice_uri + rest["statistics"]
            if "traffic_stats" in rest:
                update["statistics"] = slice_uri + rest["traffic_stats"]

            cloud_utils.update_or_insert(db, "tblUris", update,
                                         {"tblEntities": dbid, "tblSlices": slice_dbid, "type": uri_type})

            if "firewall" in rest and isinstance(rest["firewall"], list) and vdc_row:
                for cfd_group in rest["firewall"]:
                    group_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": vdc_row["id"],
                                                                                      "entitytype": "security_group",
                                                                                      "deleted": 0,
                                                                                      "name": cfd_group[
                                                                                          "security_group"]
                                                                                      }, order="ORDER BY id LIMIT 1"))
                    if not group_row:
                        continue
                    if "status" in cfd_group and isinstance(cfd_group["status"], list):
                        for cfd_child in cfd_group["status"]:
                            child_row = cloud_utils.lower_key(
                                db.get_row_dict("tblEntities", {"parententityid": group_row["id"],
                                                                "entitytype": "security_rule",
                                                                "deleted": 0,
                                                                "name": cfd_child["name"]
                                                                }, order="ORDER BY id LIMIT 1"))
                            if not child_row:
                                continue

                            cloud_utils.update_or_insert(db, "tblAttachedEntitiesStatus",
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          "entitystatus": cfd_child["entity_state"],
                                                          "details": cfd_child.pop("details", "")
                                                          },
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          })

            if "vpn" in rest and isinstance(rest["vpn"], list) and vdc_row:
                for cfd_group in rest["vpn"]:
                    group_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": vdc_row["id"],
                                                                                      "entitytype": "vpn_group",
                                                                                      "deleted": 0,
                                                                                      "name": cfd_group["vpn_group"]
                                                                                      }, order="ORDER BY id LIMIT 1"))
                    if not group_row:
                        continue
                    if "status" in cfd_group and isinstance(cfd_group["status"], list):
                        for cfd_child in cfd_group["status"]:
                            child_row = cloud_utils.lower_key(
                                db.get_row_dict("tblEntities", {"parententityid": group_row["id"],
                                                                "entitytype": "vpn_connection",
                                                                "deleted": 0,
                                                                "name": cfd_child["name"]
                                                                }, order="ORDER BY id LIMIT 1"))
                            if not child_row:
                                continue

                            cloud_utils.update_or_insert(db, "tblAttachedEntitiesStatus",
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          "entitystatus": cfd_child["entity_state"],
                                                          "details": cfd_child.pop("details", "")
                                                          },
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          })

            if "load_balancer" in rest and isinstance(rest["load_balancer"], list) and vdc_row:
                for cfd_group in rest["load_balancer"]:
                    group_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": vdc_row["id"],
                                                                                      "entitytype": "lbs_group",
                                                                                      "deleted": 0,
                                                                                      "name": cfd_group["lbs_group"]
                                                                                      }, order="ORDER BY id LIMIT 1"))
                    if not group_row:
                        continue
                    if "status" in cfd_group and isinstance(cfd_group["status"], list):
                        for cfd_child in cfd_group["status"]:
                            child_row = cloud_utils.lower_key(
                                db.get_row_dict("tblEntities", {"parententityid": group_row["id"],
                                                                "entitytype": "lbs_service",
                                                                "deleted": 0,
                                                                "name": cfd_child["name"]
                                                                }, order="ORDER BY id LIMIT 1"))
                            if not child_row:
                                continue

                            cloud_utils.update_or_insert(db, "tblAttachedEntitiesStatus",
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          "entitystatus": cfd_child["entity_state"],
                                                          "details": cfd_child.pop("details", "")
                                                          },
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          })

            if "acl" in rest and isinstance(rest["acl"], list) and vdc_row:
                for cfd_group in rest["acl"]:
                    group_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": vdc_row["id"],
                                                                                      "entitytype": "acl_group",
                                                                                      "deleted": 0,
                                                                                      "name": cfd_group["access_group"]
                                                                                      }, order="ORDER BY id LIMIT 1"))
                    if not group_row:
                        continue
                    if "status" in cfd_group and isinstance(cfd_group["status"], list):
                        for cfd_child in cfd_group["status"]:
                            child_row = cloud_utils.lower_key(
                                db.get_row_dict("tblEntities", {"parententityid": group_row["id"],
                                                                "entitytype": "acl_rule",
                                                                "deleted": 0,
                                                                "name": cfd_child["name"]
                                                                }, order="ORDER BY id LIMIT 1"))
                            if not child_row:
                                continue

                            cloud_utils.update_or_insert(db, "tblAttachedEntitiesStatus",
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          "entitystatus": cfd_child["entity_state"],
                                                          "details": cfd_child.pop("details", "")
                                                          },
                                                         {"vdcentityid": vdc_row["id"],
                                                          "childentityid": child_row["id"],
                                                          "groupentityid": group_row["id"],
                                                          "serviceentityid": db_row["parententityid"],
                                                          "portentityid": dbid,
                                                          })


        else:
            LOG.warn(_("URI missing in rest: %s for dbid: %s for uri_type: %s" % (rest, dbid, uri_type)))
    except:
        cloud_utils.log_exception(sys.exc_info())


def update_only_uri(db, db_row, dbid, rest, entity_url, uri_type="home"):
    try:
        if "uri" in rest and rest["uri"]:
            update = {"tblEntities": dbid, "type": uri_type}
            if uri_type == "home":
                if "novnc_url" in rest:
                    rest["novnc_url"] = cloud_utils.update_user_url(rest["novnc_url"], entity_url)
                update["rest_response"] = json.dumps(rest)
            cloud_utils.update_only(db, "tblUris", update, {"tblEntities": dbid, "type": uri_type})
        else:
            LOG.warn(_("URI missing in rest: %s for dbid: %s for uri_type: %s" % (rest, dbid, uri_type)))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_service(db, dbid):
    try:
        for entitytype in entity_constants.topology_network_services:
            if entitytype in entity_manager.entities:
                for service in cloud_utils.entity_children(db, dbid, entitytype,
                                                           entity_manager.entities[entitytype].child_table):
                    yield service
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_vdc_service(db, dbid):
    try:
        current_index = 0
        while True:
            service = db.get_row("tblEntities",
                                 "parententityid = '%s' AND entitysubtype='network_service' AND id > '%s'" % (
                                     dbid, current_index),
                                 order="ORDER BY id LIMIT 1")
            if service:
                current_index = service['id']
                yield cloud_utils.lower_key(service)
            else:
                break
            yield service
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_vdc_interface(db, dbid):
    try:
        for interface in cloud_utils.entity_members(db, dbid, "network_interface", child_table=entity_manager.entities[
            "network_interface"].child_table):
            yield interface

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_service_port(db, dbid):
    try:
        for interface in cloud_utils.entity_members(db, dbid, "service_port",
                                                    child_table=entity_manager.entities["service_port"].child_table):
            yield interface

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_vdc_group(db, dbid):
    try:
        for profile in entity_constants.profile_groups_provision_order:
            if profile["group"] in entity_manager.entities:
                for group in cloud_utils.entity_members(db, dbid, profile["group"], child_table=entity_manager.entities[
                    profile["group"]].child_table):
                    yield group
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_group(db, dbid, group=entity_constants.profile_groups_provision_order):
    try:
        for profile in group:
            if profile["group"] in entity_manager.entities:
                for group in cloud_utils.entity_members(db, dbid, profile["group"], child_table=entity_manager.entities[
                    profile["group"]].child_table):
                    yield group
                    if profile["child"] and profile["child"] in entity_manager.entities:
                        for child in cloud_utils.entity_members(db, group["id"], profile["child"],
                                                                child_table=entity_manager.entities[
                                                                    profile["child"]].child_table):
                            yield child
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_entity_row_dict(db, where):
    try:
        primary_row = db.get_row_dict("tblEntities", where, order="ORDER BY id LIMIT 1")
        if not primary_row:
            return None
        crow = db.get_row(entity_manager.entities[primary_row["EntityType"]].child_table,
                          "tblEntities='%s' " % primary_row['id'], order="ORDER BY id LIMIT 1")
        if "id" in crow:
            crow["child_id"] = crow.pop("id")
        primary_row.update(crow)
        return cloud_utils.lower_key(primary_row)

    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_entity_row(db, where):
    try:
        current_index = 0
        while True:
            w = " %s AND id > %s " % (where, current_index)
            primary_row = db.get_row("tblEntities", w, order="ORDER BY id LIMIT 1")
            if not primary_row:
                return
            current_index = primary_row["id"]
            child_table = entity_manager.entities[primary_row["EntityType"]].child_table
            if child_table:
                crow = db.get_row(child_table,
                                  "tblEntities='%s' " % primary_row['id'], order="ORDER BY id LIMIT 1")
                if "id" in crow:
                    crow["child_id"] = crow.pop("id")
                primary_row.update(crow)
            yield cloud_utils.lower_key(primary_row)

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for where:  %s" % where))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_entity_attached(db, dbid):
    try:
        current_index = 0
        while True:
            row = cloud_utils.lower_key(
                db.get_row("tblAttachedEntities", "tblEntities = '%s' AND id > '%s'" % (dbid, current_index),
                           order="ORDER BY id LIMIT 1"))
            if row:
                current_index = row['id']
                yield row
            else:
                break
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error"))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_next_attached_parent_entity(db, dbid, entitytype=None):
    for row in get_next_attached_parent(db, dbid, entitytype):
        yield cloud_utils.lower_key(
            db.get_row_dict("tblEntities", {"id": row["tblentities"]}, order="ORDER BY id LIMIT 1"))


def get_next_attached_parent(db, dbid, entitytype=None):
    try:
        current_index = 0
        if entitytype:
            cond = "AND entitytype = '%s' " % entitytype
        else:
            cond = ""
        while True:
            row = cloud_utils.lower_key(
                db.get_row("tblAttachedEntities",
                           "AttachedEntityId = '%s' AND id > %s %s " % (dbid, current_index, cond),
                           order="ORDER BY id LIMIT 1"))
            if row:
                current_index = row['id']
                yield row
            else:
                break
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error"))
    except:
        cloud_utils.log_exception(sys.exc_info())


def set_entity_mode(db, dbid, mode):
    db.execute_db("UPDATE tblEntities SET  EntityMode = '%s', updated_at=now() "
                  "WHERE (id='%s' AND deleted=0)" % (mode, dbid))


def reset_status_and_uri(db, dbid, status):
    db.execute_db("UPDATE tblEntities SET EntityStatus = '%s', EntityMode = '%s', updated_at=now(), EntityBridgeId=0 "
                  "WHERE (id='%s' AND deleted=0)" % (status, status, dbid))

    db.execute_db("UPDATE tblUris SET deleted = 1, deleted_at=now() "
                  "WHERE (tblEntities='%s' AND deleted=0)" % dbid)

    db.execute_db("UPDATE tblEntityDetails SET deleted = 1, deleted_at=now() "
                  "WHERE (tblEntities='%s' AND deleted=0)" % dbid)


def reset_vdc_entities(db, dbid):
    try:
        entity = cloud_utils.lower_key(
            db.get_row_dict("tblEntities", {"id": dbid}, order="ORDER BY id LIMIT 1"))

        reset_compute_resources(db, entity)
        reset_network_resources(db, entity)

        #        db.update_db(
        #            "UPDATE tblResourcesCompute SET cpu=0,ram=0,network=0 WHERE Catagory='deployed' AND tblEntities='%s'" % dbid)

        for profile in get_next_group(db, dbid, group=entity_constants.profile_groups_deprovision_order):
            reset_status_and_uri(db, profile["id"], "Ready")
            if profile["entitytype"] == "server":
                db.execute_db("UPDATE tblServers SET novnc_url=NULL WHERE (id ='%s')" % profile["child_id"])
                db.execute_db(
                    "DELETE FROM tblAttachedEntities WHERE attachedentityid='%s' AND AttachedEntityType='physical' " %
                    profile["id"])

            if profile["entitytype"] == "volume":
                db.execute_db(
                    "DELETE FROM tblAttachedEntities WHERE attachedentityid='%s' AND AttachedEntityType='physical'  " %
                    profile["id"])

        for service in get_next_service(db, dbid):
            reset_status_and_uri(db, service["id"], "Ready")
            db.execute_db(
                "DELETE FROM tblAttachedEntities WHERE attachedentityid='%s' AND AttachedEntityType='physical' " %
                service["id"])

        db.execute_db("UPDATE tblEntities SET EntityStatus = 'Ready', EntityMode = 'Ready', updated_at=now() "
                      "WHERE (EntityType = 'network_interface' AND ParentEntityId='%s' "
                      "AND deleted=0)" % dbid)

        db.execute_db("UPDATE tblEntities SET EntityStatus = 'Ready', EntityMode = 'Ready',  updated_at=now() "
                      "WHERE (id='%s' "
                      "AND deleted=0)" % dbid)

        db.execute_db("DELETE FROM tblAttachedEntitiesStatus WHERE (vdcentityid='%s')" % dbid)

    except:
        cloud_utils.log_exception(sys.exc_info())


def json_default(o):
    if type(o) is datetime.date or type(o) is datetime.datetime:
        return o.isoformat()


class DashBoard(object):
    def __init__(self, db, dbid, vdc_row, name, mode, entitystatus, commandid, title="", bottom_visibility=True,
                 skip=False):
        self.vdc_row = vdc_row
        self.vdc_name = name
        self.vdc_mode = mode
        if skip:
            self.vdc_services_count = 0
        else:
            self.vdc_services_count = db.get_rowcount("tblEntities", "entitysubtype='network_service' AND "
                                                                     "parententityid = '%s' AND deleted=0" % dbid)
        self.vdc_start_time = cloud_utils.mysql_now()
        self.vdc_elapsed_time = datetime.datetime.utcnow()
        self.vdc_progress = 0
        self.vdc_dbid = dbid

        self.bottom_visibility = bottom_visibility

        self.service_name = ""
        self.service_type = ""
        self.service_elapsed_time = None
        self.service_last_report_time = ""
        self.service_progress = 0
        self.service_dbid = 0

        self.service_messages = []
        self.footnote = None
        self.messagebox = None
        self.messagebox_type = None
        self.commandid = commandid

        self.title = title
        self.current_name_label = "Current Service"
        self.current_type_label = "Service Type"

        self.vdc_entitystatus = entitystatus

        self.services_entitystatus = {}
        self.interfaces_entitystatus = {}

        if skip:
            return
        for service in get_next_service(db, dbid):
            self.services_entitystatus[service["id"]] = entitystatus

        for interface in cloud_utils.entity_children(db, dbid, "network_interface"):
            self.interfaces_entitystatus[interface["id"]] = entitystatus

    def update_vdc_entitystatus(self, db, entitystatus):
        self.vdc_entitystatus = entitystatus
        db.execute_db(
            "UPDATE tblEntities SET updated_at = now(), EntityStatus = '%s', EntityMode = '%s' WHERE id='%s'" % (
                entitystatus, entitystatus, self.vdc_dbid))

    def update_services(self, entitystatus):
        for dbid in self.services_entitystatus:
            self.services_entitystatus[dbid] = entitystatus

    def update_interfaces(self, entitystatus):
        for dbid in self.interfaces_entitystatus:
            self.interfaces_entitystatus[dbid] = entitystatus

    def register_current_service_status(self, db, entitystatus):
        self.register_service_status(db, self.service_dbid, entitystatus)

    def update_service_status(self, db, dbid, entitystatus):
        if dbid in self.services_entitystatus.keys():
            self.services_entitystatus[dbid] = entitystatus

    def register_service_status(self, db, dbid, entitystatus):
        if dbid in self.services_entitystatus.keys():
            self.services_entitystatus[dbid] = entitystatus
            self.register_event(db)

    def update_interface_status(self, db, dbid, entitystatus):
        if dbid in self.interfaces_entitystatus.keys():
            self.interfaces_entitystatus[dbid] = entitystatus

    def register_interface_status(self, db, dbid, entitystatus):
        if dbid in self.interfaces_entitystatus.keys():
            self.interfaces_entitystatus[dbid] = entitystatus
            self.register_event(db)

    def register_vdc_status(self, db, entitystatus):
        self.vdc_entitystatus = entitystatus
        self.register_event(db)

    def final(self, db, message, message_type):
        self.messagebox = message
        self.messagebox_type = message_type
        self.register_event(db)

    def clear_service(self):
        self.service_name = ""
        self.service_type = ""
        self.service_elapsed_time = None
        self.service_last_report_time = ""
        self.service_messages = []

    def update_service_taps(self, db, dbid, entitystatus):
        for int in cloud_utils.get_next_service_interface(db, dbid):
            self.update_interface_status(db, int["id"], entitystatus)
            if int["interfacetype"] != "tap":
                continue
            if int["beginserviceentityid"] == dbid:
                tap_dbid = int["endserviceentityid"]
            else:
                tap_dbid = int["beginserviceentityid"]
            self.update_service_status(db, tap_dbid, entitystatus)

    def update_db_service_taps(self, db, dbid, entitystatus):
        for int in cloud_utils.get_next_service_interface(db, dbid):
            if int["interfacetype"] != "tap":
                continue
            db.execute_db(
                "UPDATE tblEntities SET updated_at = now(), EntityStatus = '%s', EntityMode = '%s' WHERE id='%s'" % (
                    entitystatus, entitystatus, int["id"]))
            if int["beginserviceentityid"] == dbid:
                tap_dbid = int["endserviceentityid"]
            else:
                tap_dbid = int["beginserviceentityid"]
            db.execute_db(
                "UPDATE tblEntities SET updated_at = now(), EntityStatus = '%s', EntityMode = '%s' WHERE id='%s'" % (
                    entitystatus, entitystatus, tap_dbid))

    def completion_time(self):
        if self.vdc_elapsed_time:
            vdc_elapsed = time.strftime("%H:%M:%S",
                                        time.gmtime((datetime.datetime.utcnow() - self.vdc_elapsed_time).seconds))
        else:
            vdc_elapsed = "00:00:00"
        return vdc_elapsed

    def service_completion_time(self):
        if self.service_elapsed_time:
            elapsed = time.strftime("%H:%M:%S",
                                    time.gmtime((datetime.datetime.utcnow() - self.service_elapsed_time).seconds))
        else:
            elapsed = "00:00:00"
        return elapsed

    def register_event(self, db):
        try:
            if self.messagebox:
                event = {"messagebox": {"text": self.messagebox, "type": self.messagebox_type},
                         "commandid": self.commandid}
            else:
                if self.vdc_elapsed_time:
                    vdc_elapsed = time.strftime("%H:%M:%S", time.gmtime(
                        (datetime.datetime.utcnow() - self.vdc_elapsed_time).seconds))
                else:
                    vdc_elapsed = ""
                if self.service_elapsed_time:
                    service_elapsed = time.strftime("%H:%M:%S", time.gmtime(
                        (datetime.datetime.utcnow() - self.service_elapsed_time).seconds))
                else:
                    service_elapsed = ""

                    # if not self.service_last_report_time:
                #                    self.service_last_report_time = ""

                event = {
                    "top": {"display": [{"label": "Virtual Datacenter", "value": self.vdc_name, "type": "text"},
                                        {"label": "Mode", "value": self.vdc_mode, "type": "text"},
                                        {"label": "Number of Services", "value": self.vdc_services_count,
                                         "type": "text"},
                                        {"label": "Start Time", "value": self.vdc_start_time, "type": "currenttime"},
                                        {"label": "Elapsed Time", "value": vdc_elapsed, "type": "text"}],
                            "progress": {"label": "VDC Progress", "value": self.vdc_progress, "type": "progressmeter"}},
                    "bottom": {
                        "display": [{"label": self.current_name_label, "value": self.service_name, "type": "text"},
                                    {"label": self.current_type_label, "value": self.service_type, "type": "text"},
                                    {"label": "Elapsed Time", "value": service_elapsed, "type": "text"},
                                    {"label": "Last Report Time", "value": self.service_last_report_time,
                                     "type": "time"}],
                        "progress": {"label": "Service Progress", "value": self.service_progress,
                                     "type": "progressmeter"}},
                    "title": self.title,
                    "messages": self.service_messages,
                    "footnote": self.footnote,
                    "vdc": self.vdc_entitystatus,
                    "services": self.services_entitystatus,
                    "interfaces": self.interfaces_entitystatus,
                    "commandid": self.commandid
                }

                # if not self.bottom_visibility and "bottom" in event:
                #            event["bottom"]["display"] = ""

            event_json = json.dumps(event, default=json_default)
            db.execute_db(
                "INSERT INTO tblVdcProvisionLogs (tblEntities, created_at, Message, Commandid) VALUES ('%s', now(), '%s','%s')" %
                (self.vdc_dbid, event_json, self.commandid))
        except:
            cloud_utils.log_exception(sys.exc_info())


def clone_slice_images(db, slice_dbid):
    for org in cloud_utils.get_entity(db, "organization"):
        clone_entity(db, org["id"], slice_dbid, "imagelibrary")
        for dept in cloud_utils.entity_members(db, org["id"], "department"):
            clone_entity(db, dept["id"], slice_dbid, "imagelibrary")


def clone_from_slices(db, dbid, entitytype):
    for slice in cloud_utils.get_entity(db, "slice"):
        if slice["entitystatus"].lower() != "inactive":
            clone_entity(db, dbid, slice["id"], entitytype)
        else:
            unclone_entity(db, dbid, slice["id"], entitytype)


def clone_entity_attachments(db, to_dbid, from_dbid, entitytype, vdc_dbid):
    try:
        for ent in cloud_utils.entity_members(db, from_dbid, entitytype,
                                              child_table=entity_manager.entities[entitytype].child_table):
            cloned_ent = db.get_row("tblEntities", " name = '%s' AND entitytype = '%s' AND parententityid = %s " % (
                ent["name"], entitytype, to_dbid),
                                    order="ORDER BY id LIMIT 1")
            if not cloned_ent:
                LOG.warn(_("cloning attachement -- unable to find cloned entity itself %s" % ent))
                continue
            current_index = 0
            while True:
                attach = db.get_row("tblAttachedEntities",
                                    " tblEntities = '%s' AND id > '%s'" % (ent["id"], current_index),
                                    order="ORDER BY id LIMIT 1")
                if not attach:
                    break
                current_index = attach['id']

                att_entity = db.get_row_dict("tblEntities", {"id": attach["AttachedEntityId"], "deleted": 0},
                                             order="ORDER BY id LIMIT 1")
                if not att_entity:
                    LOG.warn(_("cloning attachement -- unable to find cloned entity's attachment  %s" % attach))
                    continue

                if attach["AttachedEntityType"] == "serverfarm" or attach["AttachedEntityType"] == "container":
                    cloned_att_entity = db.get_row("tblEntities",
                                                   " name = '%s' AND entitytype = '%s' AND parententityid = %s " % (
                                                       att_entity["Name"], att_entity["EntityType"], vdc_dbid),
                                                   order="ORDER BY id LIMIT 1")
                    if not cloned_att_entity:
                        LOG.warn(_("cloning attachement -- group leven - unable to find cloned entity %s" % attach))
                        continue

                elif attach["AttachedEntityType"] == "volume" or attach["AttachedEntityType"] == "volume_boot":
                    parent_att_entity = db.get_row_dict("tblEntities",
                                                        {"id": att_entity["ParentEntityId"], "deleted": 0},
                                                        order="ORDER BY id LIMIT 1")
                    if not parent_att_entity:
                        LOG.warn(_("cloning attachement -- unable to find entity's parent %s" % attach))
                        continue
                    cloned_parent_att_entity = db.get_row("tblEntities",
                                                          " name = '%s' AND entitytype = '%s' AND parententityid = %s " % (
                                                              parent_att_entity["Name"],
                                                              parent_att_entity["EntityType"],
                                                              vdc_dbid),
                                                          order="ORDER BY id LIMIT 1")
                    if not cloned_parent_att_entity:
                        LOG.warn(_("cloning attachement -- unable to find cloned entity parent %s" % attach))
                        continue

                    cloned_att_entity = db.get_row("tblEntities",
                                                   " name = '%s' AND entitytype = '%s' AND parententityid = %s " %
                                                   (att_entity["Name"], att_entity["EntityType"],
                                                    cloned_parent_att_entity["id"]),
                                                   order="ORDER BY id LIMIT 1")
                    if not cloned_att_entity:
                        LOG.warn(_("cloning attachement -- unable to find cloned entity %s" % attach))
                        continue

                elif attach["AttachedEntityType"] == "image" or attach["AttachedEntityType"] == "ssh_user":
                    cloned_att_entity = att_entity

                else:
                    LOG.warn(_("cloning attachement -- unknown entitytype in attachment %s" % attach))

                attach.pop("id", None)
                attach["tblEntities"] = cloned_ent["id"]
                attach["AttachedEntityId"] = cloned_att_entity["id"]
                attach["AttachedEntityUniqueId"] = cloned_att_entity["UniqueId"]
                cloud_utils.insert_db(db, "tblAttachedEntities", attach)

            if entitytype in entity_constants.profile_group_child:
                clone_entity_attachments(db, cloned_ent["id"], ent["id"],
                                         entity_constants.profile_group_child[entitytype], vdc_dbid)

    except:
        cloud_utils.log_exception(sys.exc_info())


def clone_entity(db, to_dbid, from_dbid, entitytype, update_clonedfrom=True):
    for ent in cloud_utils.entity_members(db, from_dbid, entitytype,
                                          child_table=entity_manager.entities[entitytype].child_table):
        if ent["clonedfromentityid"] == 0:
            ent["clonedfromentityid"] = ent["id"]

        master_id = ent["id"]
        ent["parententityid"] = to_dbid

        ent.pop("id", None)
        ent.pop("created_at", None)
        ent.pop("deleted_at", None)
        ent.pop("updated_at", None)
        ent.pop("deleted", None)
        ent.pop("tblentities", None)

        if update_clonedfrom:
            clonedfromid = ent["clonedfromentityid"]
        else:
            clonedfromid = 0
            ent["clonedfromentityid"] = 0

        clone_id = cloud_utils.update_or_insert(db, "tblEntities", ent, {"entitytype": entitytype, "name": ent["name"],
                                                                         "deleted": 0, "parententityid": to_dbid,
                                                                         "clonedfromentityid": clonedfromid
                                                                         },
                                                child_table=entity_manager.entities[entitytype].child_table)
        if not clone_id or clone_id == 0:
            continue

        for kv in cloud_utils.get_generic(db, "tblKeyValuePairs", "tblEntities", from_dbid):
            cloud_utils.insert_db(db, "tblKeyValuePairs", {"tblEntities": clone_id,
                                                           "thekey": kv["thekey"], "thevalue": kv["thevalue"]})

        user_data = db.get_row_dict("tblUserData", {"tblEntities": master_id}, order="ORDER BY id LIMIT 1")
        if user_data:
            cloud_utils.update_or_insert(db, "tblUserData", {"tblEntities": clone_id,
                                                             "user_data": user_data["User_Data"]},
                                         {"tblentities": clone_id})

        current_index = 0
        while True:
            row = cloud_utils.lower_key(
                db.get_row("tblSSHPublicKeys", "tblEntities = '%s' AND id > '%s'" % (master_id, current_index),
                           order="ORDER BY id LIMIT 1"))
            if row:
                current_index = row['id']
                cloud_utils.insert_db(db, "tblSSHPublicKeys",
                                      {"tblEntities": clone_id, "name": row["name"], "public_key": row["public_key"]})
            else:
                break

        if entitytype in entity_constants.profile_group_child:
            clone_entity(db, clone_id, master_id, entity_constants.profile_group_child[entitytype], update_clonedfrom)


def unclone_entity(db, to_dbid, from_dbid, entitytype):
    for ent in cloud_utils.entity_members(db, from_dbid, entitytype,
                                          child_table=entity_manager.entities[entitytype].child_table):
        if ent["clonedfromentityid"] == 0:
            ent["clonedfromentityid"] = ent["id"]
        row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"clonedfromentityid": ent["clonedfromentityid"],
                                                                    "deleted": 0, "parententityid": to_dbid},
                                                    order="ORDER BY id LIMIT 1"))
        if not row:
            continue
        if entitytype in entity_constants.profile_group_child:
            unclone_entity(db, row["id"], ent["id"], entity_constants.profile_group_child[entitytype])
        db.execute_db("UPDATE tblEntities SET tblEntities.deleted=1, tblEntities.deleted_at= now() "
                      " WHERE id = '%s' " % row["id"])


def entity_name_check(db, parententityid, entitytype, name):
    check_row = db.execute_db("SELECT * FROM tblEntities WHERE (Name = '%s' AND EntityType = '%s' AND deleted = 0 AND \
                               ParentEntityId = '%s' )  ORDER By id LIMIT 1" %
                              (name, entitytype, parententityid))
    return check_row


def add_child_entity(db, entity):
    """.
    """
    child_table = entity_manager.entities[entity["entitytype"]].child_table
    if not child_table:
        return entity

    crow = db.get_row(child_table, "tblEntities='%s' " % entity['id'], order="ORDER BY id LIMIT 1")
    if "id" in crow:
        crow["child_id"] = crow.pop("id")
    entity.update(cloud_utils.lower_key(crow))
    return entity


def update_logs(db, rest, entityid, time, table, id):
    try:
        logs = rest["log"]
        log_time = cloud_utils.mysql_time_to_python(time)
        for log in logs:
            if not log:
                continue
            if "unique_id" not in log:
                log["unique_id"] = 0
            db.execute_db(
                "INSERT INTO tblLogs (tblentities, parententityid, created_at, field, severity, unique_id, message, source)"
                " VALUES ('%s', '%s', '%s', '%s', '%s','%s', '%s', 'Slice') " %
                (entityid, entityid, log["created_at"], log["type"], log["severity"], log["unique_id"],
                 db.escape_string(log["message"])))
            if log_time < cloud_utils.mysql_time_to_python(log["created_at"]):
                log_time = cloud_utils.mysql_time_to_python(log["created_at"])

        db.update_db(
            "UPDATE %s SET last_log_time='%s' WHERE id= %s" % (table, cloud_utils.python_time_to_mysql(log_time), id))
        return cloud_utils.python_time_to_mysql(log_time)
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_active_container_count(db, dbid):
    return db.get_rowcount("tblEntities",
                           "EntityType = 'container' AND deleted=0 AND EntityStatus = 'Active' AND parententityid = '%s'" % dbid)


def update_virtual_resoures_tree_compute(db, dbid, slice_id, class_id, reset_flag=False, LOG=LOG):
    try:
        if dbid == 0:
            return
        sums = db.execute_db(
            "SELECT sum(cpu), sum(ram), sum(network) FROM tblResourcesCompute "
            " WHERE computeclassesid = %s and  entitytype != 'slice' and catagory = 'deployed' and ParentEntityId ='%s'" %
            (class_id, dbid))
        if not sums or not isinstance(sums, tuple) or "sum(cpu)" not in sums[0] or \
                        "sum(ram)" not in sums[0] or "sum(network)" not in sums[0] or sums[0]["sum(cpu)"] is None or \
                        sums[0]["sum(ram)"] is None or sums[0]["sum(network)"] is None:
            return
        cpu = int(sums[0]["sum(cpu)"])
        ram = int(sums[0]["sum(ram)"])
        network = int(sums[0]["sum(network)"])
        parent = cloud_utils.lower_key(
            db.get_row_dict("tblResourcesCompute",
                            {"tblEntities": dbid, "catagory": "deployed", "computeclassesid": class_id},
                            order="ORDER BY id LIMIT 1"))
        if reset_flag or not parent or parent["cpu"] != cpu or parent["ram"] != ram or parent["network"] != network:
            if (cpu == 0 and ram == 0 and network == 0 and parent):
                db.delete_rows_dict("tblResourcesCompute",
                                    {"parententityid": dbid, "entitytype": parent["entitytype"], "catagory": "deployed",
                                     "computeclassesid": class_id})
            else:
                cloud_utils.update_or_insert(db, "tblResourcesCompute", {"tblentities": dbid,
                                                                         "cpu": cpu, "ram": ram, "network": network,
                                                                         "catagory": "deployed",
                                                                         "computeclassesid": class_id},
                                             {"tblentities": dbid, "catagory": "deployed",
                                              "computeclassesid": class_id})
            if parent:
                current = parent
            else:
                current = cloud_utils.lower_key(
                    db.get_row_dict("tblResourcesCompute",
                                    {"tblEntities": dbid, "catagory": "deployed", "computeclassesid": class_id},
                                    order="ORDER BY id LIMIT 1"))
            if not current:
                LOG.critical(
                    _("Compute resources aborted for dbid:%s cpu:%s ram:%s network:%s" % (dbid, cpu, ram, network)))
                return
            LOG.info(_("Compute resources updated for dbid:%s EntityType:%s cpu:%s ram:%s network:%s" % (
                dbid, current["entitytype"], cpu, ram, network)))
            update_virtual_resoures_tree_compute(db, current["parententityid"], slice_id, reset_flag, class_id, LOG=LOG)
        else:
            LOG.info(_("Compute resources skipped for dbid:%s EntityType:%s cpu:%s ram:%s network:%s" % (
                dbid, parent["entitytype"], cpu, ram, network)))
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


'''
def update_resoures_tree_compute(db, current, slice_id):
    try:
        sums = db.execute_db(
            "SELECT sum(cpu), sum(ram), sum(network) FROM tblResourcesCompute WHERE  ParentEntityId ='%s'" % current[
                "parententityid"])
        if not sums or not isinstance(sums, tuple) or "sum(cpu)" not in sums[0] or "sum(ram)" not in sums[
            0] or "sum(network)" not in sums[0]:
            return
        cpu = int(sums[0]["sum(cpu)"])
        ram = int(sums[0]["sum(ram)"])
        network = int(sums[0]["sum(network)"])

        parent = cloud_utils.lower_key(
            db.get_row_dict("tblResourcesCompute", {"tblEntities": current["parententityid"],
                                                    "catagory": "deployed"},
                            order="ORDER BY id LIMIT 1"))

        if not parent or parent["cpu"] != cpu or parent["ram"] != ram or parent["network"] != network:
            cloud_utils.update_or_insert(db, "tblResourcesCompute", {"tblentities": current["parententityid"],
                                                                     "cpu": cpu,
                                                                     "ram": ram,
                                                                     "network": network,
                                                                     "catagory": "deployed",
            },
                                         {"tblentities": current["parententityid"], "catagory": "deployed"})

            if parent:
                current = parent
            else:
                current = cloud_utils.lower_key(
                    db.get_row_dict("tblResourcesCompute", {"tblEntities": current["parententityid"],
                                                            "catagory": "deployed"},
                                    order="ORDER BY id LIMIT 1"))
            if not current or current["parententityid"] == 0:
                return
            update_virtual_resoures_tree_compute(db, current, slice_id)

    except:
        cloud_utils.log_exception(sys.exc_info())

                    svc = add_child_entity(db, service)
            for farm in cloud_utils.entity_attach(db, service["id"], entitytype="serverfarm"):
                if farm["entitystatus"].lower() != "active":
                    continue
                for server in cloud_utils.entity_children(db, farm["id"], entitytype="server"):
                    if server["entitystatus"].lower() != "active":
                        continue
                    srv = add_child_entity(db, server)
                    cpu += srv["cpuvcpu"]
                    ram += srv["memory"]
                    network += svc["throughput"]


'''


def update_compute_resources(db, slice_id, vdc, LOG=LOG):
    class_resources = setup_resource_record()
    try:
        for service in cloud_utils.entity_children(db, vdc["id"], entitytype="compute_network_service"):
            get_compute_service_resources(db, service["id"], check_status=True, resources=class_resources, LOG=LOG)

        for class_id in class_resources["compute_resources"]:
            resources = class_resources["compute_resources"][class_id]
            current = cloud_utils.lower_key(
                db.get_row_dict("tblResourcesCompute",
                                {"tblEntities": vdc["id"], "catagory": "deployed", "sliceid": slice_id,
                                 "computeclassesid": class_id},
                                order="ORDER BY id LIMIT 1"))
            if not current or (current["cpu"] != resources["vcpu"] or
                                       current["ram"] != resources["ram"] or
                                       current["network"] != resources["network"]):
                cloud_utils.update_or_insert(db, "tblResourcesCompute", {"tblentities": vdc["id"],
                                                                         "cpu": resources["vcpu"],
                                                                         "ram": resources["ram"],
                                                                         "network": resources["network"],
                                                                         "catagory": "deployed",
                                                                         "sliceid": slice_id,
                                                                         "computeclassesid": class_id},
                                             {"tblentities": vdc["id"], "catagory": "deployed",
                                              "computeclassesid": class_id})
                if not current:
                    current = cloud_utils.lower_key(
                        db.get_row_dict("tblResourcesCompute",
                                        {"tblEntities": vdc["id"], "catagory": "deployed", "sliceid": slice_id,
                                         "computeclassesid": class_id},
                                        order="ORDER BY id LIMIT 1"))
                LOG.info(
                    _("Compute resources updated for dbid:%s Class id: %s EntityType:%s vcpu:%s ram:%s network:%s" %
                      (vdc["id"], current["entitytype"], class_id, resources["vcpu"],
                       resources["ram"], resources["network"])))

                update_virtual_resoures_tree_compute(db, current["parententityid"], slice_id, class_id, LOG=LOG)
                update_compute_slice_resources(db, slice_id, class_id, LOG=LOG)
            else:
                LOG.info(_("Compute resources skipped for dbid:%s EntityType:%s cpu:%s ram:%s network:%s" %
                           (vdc["id"], current["entitytype"], resources["vcpu"],
                            resources["ram"], resources["network"])))
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def reset_compute_resources(db, vdc, LOG=LOG):
    try:
        #        cpu = 0
        #        ram = 0
        #        network = 0
        current_id = 0
        while True:
            current = cloud_utils.lower_key(
                db.get_row("tblResourcesCompute",
                           "id > %s AND tblEntities = %s AND catagory = 'deployed' " % (current_id, vdc["id"]),
                           order="ORDER BY id LIMIT 1"))
            if not current:
                return

            current_id = current["id"]
            slice_id = current["sliceid"]
            class_id = current['computeclassesid']
            db.delete_row_id("tblResourcesCompute", current["id"])
            #            if current["cpu"] != cpu  or  current["ram"] != ram or current["network"] != network:
            #                cloud_utils.update_only(db, "tblResourcesCompute", {"tblentities": vdc["id"],
            #                                        "cpu": cpu, "ram": ram, "network": network,"catagory": "deployed", "sliceid": 0, 'computeclassesid':class_id },
            #                                                                    {"id":current_id})
            if current["parententityid"] != 0:
                LOG.info(_("Compute resources reset for dbid:%s EntityType:%s classid: %s" % (
                    vdc["id"], current["entitytype"], class_id)))
                update_virtual_resoures_tree_compute(db, current["parententityid"], slice_id, class_id, reset_flag=True,
                                                     LOG=LOG)
            # Update slice resources
            update_compute_slice_resources(db, slice_id, class_id, LOG=LOG)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def update_virtual_resoures_tree_storage(db, dbid, slice_id, class_id, LOG=LOG):
    try:
        if dbid == 0:
            return
        sums = db.execute_db(
            "SELECT sum(iops), sum(capacity), sum(network) "
            "FROM tblResourcesStorage "
            "WHERE entitytype != 'slice' and storageclassesid = %s and catagory = 'deployed' and ParentEntityId ='%s' " % (
                class_id, dbid))
        if not sums or not isinstance(sums, tuple) or "sum(capacity)" not in sums[0] or \
                        "sum(iops)" not in sums[0] or "sum(network)" not in sums[0] or sums[0][
            "sum(capacity)"] is None or \
                        sums[0]["sum(iops)"] is None or sums[0]["sum(network)"] is None:
            return
        capacity = int(sums[0]["sum(capacity)"])
        iops = int(sums[0]["sum(iops)"])
        network = int(sums[0]["sum(network)"])
        parent = cloud_utils.lower_key(
            db.get_row_dict("tblResourcesStorage", {"tblEntities": dbid, "storageclassesid": class_id,
                                                    "catagory": "deployed"}, order="ORDER BY id LIMIT 1"))
        if not parent or parent["capacity"] != capacity or parent["iops"] != iops or parent["network"] != network:
            if (capacity == 0 and iops == 0 and network == 0 and parent):
                db.delete_rows_dict("tblResourcesStorage",
                                    {"parententityid": dbid, "entitytype": parent["entitytype"], "catagory": "deployed",
                                     "storageclassesid": class_id})
            else:
                cloud_utils.update_or_insert(db, "tblResourcesStorage", {"tblentities": dbid, "capacity": capacity,
                                                                         "iops": iops, "network": network,
                                                                         "storageclassesid": class_id,
                                                                         "catagory": "deployed", },
                                             {"tblentities": dbid, "storageclassesid": class_id,
                                              "catagory": "deployed"})
            if parent:
                current = parent
            else:
                current = cloud_utils.lower_key(
                    db.get_row_dict("tblResourcesStorage", {"tblEntities": dbid, "storageclassesid": class_id,
                                                            "catagory": "deployed"}, order="ORDER BY id LIMIT 1"))
            if not current or current["parententityid"] == 0:
                return
            LOG.info(_(
                "Storage resources updated for dbid:%s EntityType:%s class id  %s: capacity:%s iops:%s network:%s" % (
                    dbid, current["entitytype"], class_id, capacity, iops, network)))
            update_virtual_resoures_tree_storage(db, current["parententityid"], class_id, slice_id, LOG=LOG)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def update_storage_resources(db, slice_id, vdc, LOG=LOG):
    try:
        class_resources = get_vdc_storage_resources(db, vdc, check_status=True)
        for class_id in class_resources["storage_resources"]:
            resources = class_resources["storage_resources"][class_id]
            current = cloud_utils.lower_key(
                db.get_row_dict("tblResourcesStorage",
                                {"tblEntities": vdc["id"], "catagory": "deployed", "storageclassesid": class_id,
                                 "sliceid": slice_id},
                                order="ORDER BY id LIMIT 1"))
            db_update = False
            if current:
                if resources["capacity"] == 0:
                    db.delete_row_id("tblResourcesStorage", current["id"])
                elif (current["capacity"] != resources["capacity"]):
                    db_update = True
            if (not current and resources["capacity"] != 0) or db_update:
                cloud_utils.update_or_insert(db, "tblResourcesStorage", {"tblentities": vdc["id"],
                                                                         "capacity": resources["capacity"],
                                                                         "iops": resources["iops"],
                                                                         "network": resources["net"],
                                                                         "catagory": "deployed",
                                                                         "storageclassesid": class_id,
                                                                         "sliceid": slice_id},
                                             {"tblentities": vdc["id"], "storageclassesid": class_id,
                                              "catagory": "deployed"})
            if not current:
                current = cloud_utils.lower_key(
                    db.get_row_dict("tblResourcesStorage",
                                    {"tblEntities": vdc["id"], "catagory": "deployed", "storageclassesid": class_id,
                                     "sliceid": slice_id},
                                    order="ORDER BY id LIMIT 1"))
            if not current:
                continue
            LOG.info(
                _("Storage resources updated for dbid:%s EntityType:%s class id %s: capacity:%s iops:%s network:%s" %
                  (vdc["id"], current["entitytype"],
                   class_id, resources["capacity"], resources["iops"], resources["net"])))
            update_virtual_resoures_tree_storage(db, current["parententityid"], slice_id, class_id, LOG=LOG)
            update_storage_slice_resources(db, slice_id, class_id, LOG=LOG)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def update_virtual_resoures_tree_network(db, dbid, network_type, slice_id, class_id, reset_flag=False, LOG=LOG):
    try:
        if dbid == 0:
            return
        sums = db.execute_db(
            "SELECT sum(throughput) "
            "FROM tblResourcesNetwork "
            "WHERE entitytype != 'slice' and type ='%s' and "
            "catagory = 'deployed' and ParentEntityId ='%s' and networkclassesid=%s  " % (network_type, dbid, class_id))
        if not sums or not isinstance(sums, tuple) or "sum(throughput)" not in sums[0] or sums[0][
            "sum(throughput)"] is None:
            return
        throughput = int(sums[0]["sum(throughput)"])
        parent = cloud_utils.lower_key(
            db.get_row_dict("tblResourcesNetwork",
                            {"tblEntities": dbid, "type": network_type, "networkclassesid": class_id,
                             "catagory": "deployed"}, order="ORDER BY id LIMIT 1"))
        if reset_flag or not parent or parent["throughput"] != throughput:
            if throughput == 0:
                db.delete_rows_dict("tblResourcesNetwork",
                                    {"parententityid": dbid, "entitytype": parent["entitytype"],
                                     "catagory": "deployed", "type": network_type, "networkclassesid": class_id})
            else:
                cloud_utils.update_or_insert(db, "tblResourcesNetwork",
                                             {"tblentities": dbid, "networkclassesid": class_id,
                                              "throughput": throughput, "type": network_type, "catagory": "deployed"},
                                             {"tblentities": dbid, "type": network_type, "catagory": "deployed",
                                              "networkclassesid": class_id})
            if parent:
                current = parent
            else:
                current = cloud_utils.lower_key(
                    db.get_row_dict("tblResourcesNetwork",
                                    {"tblEntities": dbid, "type": network_type, "networkclassesid": class_id,
                                     "catagory": "deployed"}, order="ORDER BY id LIMIT 1"))
            if not current or current["parententityid"] == 0:
                return
            LOG.info(_("Network resources updated for dbid:%s EntityType:%s network type %s: throughput:%s" % (
                dbid, current["entitytype"], network_type, throughput)))
            update_virtual_resoures_tree_network(db, current["parententityid"], network_type, slice_id, class_id,
                                                 reset_flag, LOG=LOG)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


process_network_services = [
    "nat_network_service",
    "rts_network_service",
    "fws_network_service",
    "lbs_network_service",
    "ipsecvpn_network_service",
    "nms_network_service",
]


def update_network_resources(db, slice_id, vdc, LOG=LOG):
    try:
        class_resources = setup_resource_record()
        for service in get_next_service(db, vdc["id"]):
            if service["entitytype"] not in process_network_services:
                continue
            # if service["servicetype"] not in throughputs:
            #                throughputs[service["servicetype"]] = 0
            if service["entitystatus"].lower() != "active":
                continue

            uris_row = db.get_row("tblUris", "tblEntities = %s AND deleted=0 " % service["id"])
            if not uris_row or "rest_response" not in uris_row:
                continue
            try:
                rest_response = ujson.loads(uris_row["rest_response"])
            except:
                continue
            throughput = 0
            if "params" in rest_response and "throughput" in rest_response["params"]:
                throughput = rest_response["params"]["throughput"]
            if "service_status" in rest_response and "current_instances_count" in rest_response["service_status"]:
                throughput = throughput * rest_response["service_status"]["current_instances_count"]
            add_network_resources(class_resources, service, throughput=throughput,
                                  maximum_throughput=(service["throughput"] * service["maxinstancescount"]))

        for class_id in class_resources["network_resources"]:
            resources = class_resources["network_resources"][class_id]

            for service_type in resources:
                throughput = resources[service_type]["throughput"]
                if throughput == 0:
                    continue
                current = cloud_utils.lower_key(
                    db.get_row_dict("tblResourcesNetwork",
                                    {"tblEntities": vdc["id"], "catagory": "deployed", "type": service_type,
                                     "networkclassesid": class_id, "sliceid": slice_id},
                                    order="ORDER BY id LIMIT 1"))
                if not current or current["throughput"] != throughput:
                    cloud_utils.update_or_insert(db, "tblResourcesNetwork", {"tblentities": vdc["id"],
                                                                             "throughput": throughput,
                                                                             "catagory": "deployed",
                                                                             "type": service_type,
                                                                             "networkclassesid": class_id,
                                                                             "sliceid": slice_id},
                                                 {"tblentities": vdc["id"], "type": service_type,
                                                  "catagory": "deployed", "networkclassesid": class_id, })
                    if not current:
                        current = cloud_utils.lower_key(db.get_row_dict("tblResourcesNetwork",
                                                                        {"tblEntities": vdc["id"],
                                                                         "catagory": "deployed", "type": service_type,
                                                                         "networkclassesid": class_id,
                                                                         "sliceid": slice_id},
                                                                        order="ORDER BY id LIMIT 1"))
                    LOG.info(_("Network resources updated for dbid:%s sliceid: %s EntityType:%s "
                               "network type %s: throughput:%s" % (
                                   vdc["id"], slice_id, current["entitytype"], service_type, throughput)))

                    update_virtual_resoures_tree_network(db, current["parententityid"], service_type, slice_id,
                                                         class_id, LOG=LOG)
                    sums = db.execute_db("SELECT sum(throughput) FROM tblResourcesNetwork "
                                         "  WHERE entitytype='vdc' and type = '%s' and catagory = 'deployed' and sliceid =%s "
                                         "and networkclassesid = %s" % (service_type, slice_id, class_id))
                    if not sums or not isinstance(sums, tuple) or "sum(throughput)" not in sums[0] or sums[0][
                        "sum(throughput)"] is None:
                        return
                    throughput = int(sums[0]["sum(throughput)"])
                    cloud_utils.update_or_insert(db, "tblResourcesNetwork",
                                                 {"tblentities": slice_id, "throughput": throughput,
                                                  "type": service_type, "catagory": "deployed",
                                                  "networkclassesid": class_id},
                                                 {"tblentities": slice_id, "type": service_type, "catagory": "deployed",
                                                  "networkclassesid": class_id})
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def old_reset_network_resources(db, vdc, LOG=LOG):
    try:
        class_resources = setup_resource_record()
        for service in get_next_service(db, vdc["id"]):
            if service["entitytype"] not in process_network_services:
                continue
            add_network_resources(class_resources, service, throughput=0, maximum_throughput=0, override=True)

        for class_id in class_resources["network_resources"]:
            resources = class_resources["network_resources"][class_id]
            for service_type in resources:
                current_id = 0
                throughput = resources[service_type]["throughput"]
                while True:
                    current = cloud_utils.lower_key(
                        db.get_row("tblResourcesNetwork",
                                   "id > %s AND tblEntities = %s AND catagory = 'deployed' AND "
                                   "type = '%s' and networkclassesid = %s " % (
                                       current_id, vdc["id"], service_type, class_id),
                                   order="ORDER BY id LIMIT 1"))
                    if not current:
                        break
                    current_id = current["id"]
                    if current["throughput"] == throughput:
                        continue
                    slice_id = current["sliceid"]
                    cloud_utils.update_or_insert(db, "tblResourcesNetwork",
                                                 {"tblentities": vdc["id"], "networkclassesid": class_id,
                                                  "throughput": throughput, "catagory": "deployed",
                                                  "type": service_type, "sliceid": 0},
                                                 {"tblentities": vdc["id"], "type": service_type,
                                                  "catagory": "deployed", "networkclassesid": class_id})
                    if current["parententityid"] != 0:
                        update_virtual_resoures_tree_network(db, current["parententityid"], service_type, slice_id,
                                                             class_id, reset_flag=True)
                    update_network_slice_resources(db, service_type, slice_id, class_id, LOG=LOG)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def reset_network_resources(db, vdc, LOG=LOG):
    try:
        current_id = 0
        while True:
            current = cloud_utils.lower_key(db.get_row("tblResourcesNetwork",
                                                       "id > %s AND tblEntities = %s AND catagory = 'deployed' " % (
                                                           current_id, vdc["id"]),
                                                       order="ORDER BY id LIMIT 1"))
            if not current:
                break
            current_id = current["id"]
            db.delete_row_id("tblResourcesNetwork", current["id"])
            if current["parententityid"] != 0:
                update_virtual_resoures_tree_network(db, current["parententityid"], current["type"], current["sliceid"],
                                                     current["networkclassesid"], reset_flag=True)
            update_network_slice_resources(db, current["type"], current["sliceid"], current["networkclassesid"],
                                           LOG=LOG)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def update_network_slice_resources(db, service_type, slice_id, class_id, LOG=LOG):
    try:
        if slice_id == 0:
            return
        sums = db.execute_db("SELECT sum(throughput) FROM tblResourcesNetwork "
                             "  WHERE  entitytype='vdc' and type = '%s' and "
                             "catagory = 'deployed' and sliceid =%s and networkclassesid = %s" % (
                                 service_type, slice_id, class_id))
        if not sums or not isinstance(sums, tuple) or "sum(throughput)" not in sums[0] or sums[0][
            "sum(throughput)"] is None:
            return
        sthroughput = int(sums[0]["sum(throughput)"])
        cloud_utils.update_or_insert(db, "tblResourcesNetwork", {"tblentities": slice_id, "throughput": sthroughput,
                                                                 "type": service_type, "catagory": "deployed",
                                                                 "networkclassesid": class_id},
                                     {"tblentities": slice_id, "type": service_type, "catagory": "deployed",
                                      "networkclassesid": class_id})
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def update_compute_slice_resources(db, slice_id, class_id, LOG=LOG):
    try:
        # Update slice resources
        if slice_id == 0:
            return
        sums = db.execute_db("SELECT sum(cpu), sum(ram), sum(network) FROM tblResourcesCompute "
                             "  WHERE  entitytype='vdc' and catagory = 'deployed' and sliceid =%s and computeclassesid = %s  " % (
                                 slice_id, class_id))
        if not sums or not isinstance(sums, tuple) or "sum(cpu)" not in sums[0] or \
                        "sum(ram)" not in sums[0] or "sum(network)" not in sums[0] or sums[0]["sum(cpu)"] is None or \
                        sums[0]["sum(ram)"] is None or sums[0]["sum(network)"] is None:
            return
        scpu = int(sums[0]["sum(cpu)"])
        sram = int(sums[0]["sum(ram)"])
        snetwork = int(sums[0]["sum(network)"])
        cloud_utils.update_or_insert(db, "tblResourcesCompute", {"tblentities": slice_id, "computeclassesid": class_id,
                                                                 "cpu": scpu, "ram": sram, "network": snetwork,
                                                                 "catagory": "deployed", },
                                     {"tblentities": slice_id, "catagory": "deployed", "computeclassesid": class_id})
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def update_storage_slice_resources(db, slice_id, class_id, LOG=LOG):
    try:
        if slice_id == 0:
            return
        sums = db.execute_db("SELECT sum(capacity), sum(iops), sum(network) FROM tblResourcesStorage "
                             "  WHERE  entitytype='vdc' and storageclassesid= %s and catagory = 'deployed' and sliceid ='%s' " % (
                                 class_id, slice_id))
        if not sums or not isinstance(sums, tuple) or "sum(capacity)" not in sums[0] \
                or "sum(iops)" not in sums[0] or "sum(network)" not in sums[0] \
                or sums[0]["sum(capacity)"] is None or sums[0]["sum(iops)"] is None or sums[0]["sum(network)"] is None:
            return
        capacity = int(sums[0]["sum(capacity)"])
        iops = int(sums[0]["sum(iops)"])
        network = int(sums[0]["sum(network)"])
        cloud_utils.update_or_insert(db, "tblResourcesStorage",
                                     {"tblentities": slice_id, "capacity": capacity, "iops": iops,
                                      "storageclassesid": class_id, "network": network, "catagory": "deployed"},
                                     {"tblentities": slice_id, "storageclassesid": class_id, "catagory": "deployed"})
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)


def get_slice(db, entity):
    row = cloud_utils.lower_key(
        db.get_row_dict("tblUris", {"tblEntities": entity["id"]}, order="ORDER BY id LIMIT 1"))
    if not row:
        return
    return row["tblslices"]


def update_vdc_resources(db, LOG=LOG):
    for entity in cloud_utils.get_entity(db, "vdc"):
        if entity["entitymode"].lower() == "active":
            slice_id = get_slice(db, entity)
            if not slice_id:
                continue
            update_compute_resources(db, slice_id, entity, LOG=LOG)
            update_storage_resources(db, slice_id, entity, LOG=LOG)
            update_network_resources(db, slice_id, entity, LOG=LOG)
        else:
            count = db.get_rowcount("tblEntities", "EntityType = 'container' AND deleted=0 AND "
                                                   "EntityStatus = 'Active' AND parententityid = '%s'" % entity["id"])
            if count > 0:
                slice_id = get_slice(db, entity)
                if not slice_id:
                    continue
                update_storage_resources(db, slice_id, entity, LOG=LOG)


def update_destination_port_name(db, dbid, name):
    db.execute_db("UPDATE tblEntities JOIN tblServicePorts SET tblEntities.name='%s' "
                  " WHERE ( tblServicePorts.tblEntities  = tblEntities.id AND "
                  "         tblServicePorts.DestinationServiceEntityId  = '%s') " % (name, dbid))


def log_entity_message(db, dbid, msg, entity=None, created_at=None, source=None, type="Info"):
    if not entity:
        entity = read_partial_entity(db, dbid)
        if not entity:
            return
    if entity["entitytype"] in entity_constants.entity_grandchildren:
        parent = read_partial_entity(db, entity["parententityid"])
        log_entity = read_partial_entity(db, parent["parententityid"])
        name = "%s.%s" % (entity["name"], parent["name"])
    elif entity["entitytype"] in entity_constants.entity_children:
        log_entity = read_partial_entity(db, entity["parententityid"])
        name = entity["name"]
    else:
        return
    cloud_utils.log_message(db, log_entity["id"], "%s: %s" % (name, msg), type=type)


def validate_network_resources(db, vdc_dbid, vdc_row, resources, class_id, reserve=False):
    try:
        if not resources:
            return "success"
        dept_check = True
        class_name = id2name(db, class_id)
        for svc in resources:
            if resources[svc]["throughput"] == 0:  # if no resources aare requested for this service.
                continue
            allocated = db.get_row("tblResourcesNetwork",
                                   "tblEntities = %s AND catagory = 'total' AND type = '%s' AND networkclassesid = %s " % (
                                       vdc_row["parententityid"], svc, class_id),
                                   order="ORDER BY id LIMIT 1") or {"Throughput": 0}
            deploy_id = vdc_row["parententityid"]
            if allocated["Throughput"] == 0:  ##### and int(class_id) == 0:
                dept_check = False
                cloud_utils.log_message(db, vdc_dbid, "%s - Skipping department resource check for %s - none assigned"
                                        % (vdc_row["name"], entity_constants.resource_network_services_2_names[svc]),
                                        type="Info")
                dept_row = db.get_row_dict("tblEntities", {"id": vdc_row["parententityid"]},
                                           order="ORDER BY id LIMIT 1")
                allocated = db.get_row("tblResourcesNetwork",
                                       "tblEntities = %s AND catagory = 'total' AND type = '%s' AND networkclassesid = %s " % (
                                           dept_row["ParentEntityId"], svc, class_id),
                                       order="ORDER BY id LIMIT 1") or {"Throughput": 0}
                deploy_id = dept_row["ParentEntityId"]
            deployed = db.get_row("tblResourcesNetwork",
                                  "tblEntities = %s AND catagory = 'deployed' AND type = '%s' AND networkclassesid = %s  " % (
                                      deploy_id, svc, class_id),
                                  order="ORDER BY id LIMIT 1") or {"Throughput": 0}
            available = allocated["Throughput"] - deployed["Throughput"]

            ###            if (allocated["Throughput"] == 0 and int(class_id) == 0) or available >= resources[svc]["throughput"]:
            ###                if allocated["Throughput"] == 0 and int(class_id) == 0:
            if (allocated["Throughput"] == 0) or available >= resources[svc]["throughput"]:
                if allocated["Throughput"] == 0:
                    cloud_utils.log_message(db, vdc_dbid,
                                            "%s - Skipping organization resource check for %s - none assigned"
                                            % (
                                                vdc_row["name"],
                                                entity_constants.resource_network_services_2_names[svc]),
                                            type="Info")
                if reserve:
                    deployed = db.get_row("tblResourcesNetwork",
                                          "tblEntities = %s AND catagory = 'deployed' AND type = '%s' AND networkclassesid = %s  " % (
                                              vdc_row["id"], svc, class_id),
                                          order="ORDER BY id LIMIT 1") or {"Throughput": 0}
                    cloud_utils.log_message(db, vdc_dbid,
                                            "%s - Resources (Mbps) consumed for %s. Class: %s Allocated: %s Deployed: %s Available: %s Provisioning: %s "
                                            % (vdc_row["name"],
                                               entity_constants.resource_network_services_2_names[svc], class_name,
                                               allocated["Throughput"], deployed["Throughput"],
                                               available, resources[svc]["throughput"]), type="Info")
                    cloud_utils.update_or_insert(db, "tblResourcesNetwork", {"tblentities": vdc_row["id"],
                                                                             "throughput": (
                                                                                 resources[svc]["throughput"] +
                                                                                 deployed[
                                                                                     "Throughput"]),
                                                                             "catagory": "deployed",
                                                                             "type": svc,
                                                                             "sliceid": vdc_row[
                                                                                 "selectedsliceentityid"]},
                                                 {"tblentities": vdc_row["id"], "type": svc, "catagory": "deployed"})
                    update_virtual_resoures_tree_network(db, vdc_row["parententityid"], svc,
                                                         vdc_row["selectedsliceentityid"], class_id, reset_flag=True)
                    update_network_slice_resources(db, svc, vdc_row["selectedsliceentityid"], class_id)
                else:
                    cloud_utils.log_message(db, vdc_dbid,
                                            "%s - Resources (Mbps) available for %s. Class: %s Allocated: %s Deployed: %s Available: %s Needed: %s "
                                            % (vdc_row["name"],
                                               entity_constants.resource_network_services_2_names[svc], class_name,
                                               allocated["Throughput"], deployed["Throughput"],
                                               available, resources[svc]["throughput"]), type="Info")
            else:
                if not dept_check:
                    cloud_utils.log_message(db, vdc_dbid, "%s - Network resource check from Organization resource pool"
                                            % (vdc_row["name"]), type="Info")
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Insufficient resources (Mbps) for %s. Class: %s Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"],
                                           entity_constants.resource_network_services_2_names[svc], class_name,
                                           allocated["Throughput"], deployed["Throughput"],
                                           available, resources[svc]["throughput"]), type="Warn")
                return "failed"
        return "success"
    except:
        print sys.exc_info()
        cloud_utils.log_exception(sys.exc_info())
    return "failed"


def validate_compute_resources(db, vdc_dbid, vdc_row, resources, class_id, reserve=False):
    try:
        if not resources:
            return "success"
        dept_check = True
        class_name = id2name(db, class_id)
        allocated = db.get_row("tblResourcesCompute",
                               "tblEntities = %s AND catagory = 'total' AND computeclassesid = %s " % (
                                   vdc_row["parententityid"], class_id),
                               order="ORDER BY id LIMIT 1") or {"RAM": 0, "Network": 0, "CPU": 0}
        deploy_id = vdc_row["parententityid"]
        if allocated["CPU"] == 0 and allocated["RAM"] == 0:  ################### and int(class_id) == 0:
            dept_check = False
            cloud_utils.log_message(db, vdc_dbid, "%s - Skipping department compute resource check - none assigned"
                                    % (vdc_row["name"]), type="Info")
            dept_row = db.get_row_dict("tblEntities", {"id": vdc_row["parententityid"]}, order="ORDER BY id LIMIT 1")
            allocated = db.get_row("tblResourcesCompute",
                                   "tblEntities = %s AND catagory = 'total' AND computeclassesid = %s " % (
                                       dept_row["ParentEntityId"], class_id),
                                   order="ORDER BY id LIMIT 1") or {"RAM": 0, "Network": 0, "CPU": 0}
            deploy_id = dept_row["ParentEntityId"]
        deployed = db.get_row("tblResourcesCompute",
                              "tblEntities = %s AND catagory = 'deployed' AND computeclassesid = %s " % (
                                  deploy_id, class_id),
                              order="ORDER BY id LIMIT 1") or {"RAM": 0, "Network": 0, "CPU": 0}

        available = {"RAM": allocated["RAM"] - deployed["RAM"], "CPU": allocated["CPU"] - deployed["CPU"],
                     "Network": allocated["Network"] - deployed["Network"]}
        #        if (allocated["CPU"] == 0 and allocated["RAM"] == 0 and int(class_id) == 0) or \
        #                (available["RAM"] >= resources["ram"]
        #                and available["CPU"] >= resources["vcpu"]
        #                and (resources["network"] == 0 or available["Network"] >= resources["network"])):
        #            if allocated["CPU"] == 0 and allocated["RAM"] == 0 and int(class_id) == 0:

        if (allocated["CPU"] == 0 and allocated["RAM"] == 0) or \
                (available["RAM"] >= resources["ram"]
                 and available["CPU"] >= resources["vcpu"]
                 and (resources["network"] == 0 or available["Network"] >= resources["network"])):
            if allocated["CPU"] == 0 and allocated["RAM"] == 0:  ################## and int(class_id) == 0:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Skipping organization compute resource check - none assigned"
                                        % (vdc_row["name"]), type="Info")
            if reserve:
                reserve_compute_resources(db, resources, vdc_row, class_id, class_name=class_name, allocated=allocated,
                                          available=available)
            else:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - vCPU resources. Class: %s Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"], class_name,
                                           allocated["CPU"], deployed["CPU"],
                                           available["CPU"], resources["vcpu"]), type="Info")
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - RAM (MB) resources.Class: %s  Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"], class_name,
                                           allocated["RAM"], deployed["RAM"],
                                           available["RAM"], resources["ram"]), type="Info")
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Compute network resources (Mbps). Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"],
                                           allocated["Network"], deployed["Network"],
                                           available["Network"], resources["network"]), type="Info")
        else:
            if not dept_check:
                cloud_utils.log_message(db, vdc_dbid, "%s - Compute resource check from Organization resource pool"
                                        % (vdc_row["name"]), type="Info")
            if available["CPU"] < resources["vcpu"]:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Insufficient vCPU resources. Class: %s Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"], class_name, allocated["CPU"], deployed["CPU"],
                                           available["CPU"], resources["vcpu"]), type="Warn")
            if available["RAM"] < resources["ram"]:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Insufficient RAM (MB) resources. Class: %s Allocated: %s Deployed: %s Available: %s Needed:  %s "
                                        % (vdc_row["name"], class_name, allocated["RAM"], deployed["RAM"],
                                           available["RAM"], resources["ram"]), type="Warn")
            if resources["network"] > 0 and available["Network"] < resources["network"]:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Insufficient compute network resources (Mbps). Class: %s Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"], class_name, allocated["Network"], deployed["Network"],
                                           available["Network"], resources["network"]), type="Warn")
            print "FAILING"
            return "failed"
        return "success"
    except:
        print sys.exc_info()
        cloud_utils.log_exception(sys.exc_info())
    return "failed"


def reserve_compute_resources(db, resources, vdc_row, class_id, class_name=None, allocated=None, available=None):
    try:
        if not class_name:
            class_name = id2name(db, class_id)

        deployed = db.get_row("tblResourcesCompute",
                              "tblEntities = %s AND catagory = 'deployed' AND computeclassesid = %s " % (
                                  vdc_row["id"], class_id),
                              order="ORDER BY id LIMIT 1") or {"RAM": 0, "Network": 0, "CPU": 0}

        if allocated and available:
            cloud_utils.log_message(db, vdc_row["id"],
                                    "%s - vCPU resources. Class: %s Allocated: %s Deployed: %s Available: %s Provisioning: %s "
                                    % (vdc_row["name"], class_name, allocated["CPU"], deployed["CPU"],
                                       available["CPU"], resources["vcpu"]), type="Info")
            cloud_utils.log_message(db, vdc_row["id"],
                                    "%s - RAM (MB) resources. Class: %s Allocated: %s Deployed: %s Available: %s Provisioning: %s "
                                    % (vdc_row["name"], class_name, allocated["RAM"], deployed["RAM"],
                                       available["RAM"], resources["ram"]), type="Info")
            cloud_utils.log_message(db, vdc_row["id"],
                                    "%s - Compute network resources (Mbps). Class: %s Allocated: %s Deployed: %s Available: %s Provisioning: %s "
                                    % (vdc_row["name"], class_name, allocated["Network"], deployed["Network"],
                                       available["Network"], resources["network"]), type="Info")
        cloud_utils.update_or_insert(db, "tblResourcesCompute", {"tblentities": vdc_row["id"],
                                                                 "cpu": (resources["vcpu"] + deployed["CPU"]),
                                                                 "ram": (resources["ram"] + deployed["RAM"]),
                                                                 "network": (
                                                                     resources["network"] + deployed["Network"]),
                                                                 "catagory": "deployed", "computeclassesid": class_id,
                                                                 "sliceid": vdc_row["selectedsliceentityid"]},
                                     {"tblentities": vdc_row["id"], "catagory": "deployed",
                                      "computeclassesid": class_id})
        update_virtual_resoures_tree_compute(db, vdc_row["parententityid"], vdc_row["selectedsliceentityid"], class_id,
                                             reset_flag=True)
        update_compute_slice_resources(db, vdc_row["selectedsliceentityid"], class_id)

    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_storage_resources(db, vdc_dbid, vdc_row, resources, class_id, reserve=False):
    try:
        if not resources:
            return "success"

        dept_check = True

        class_name = id2name(db, class_id)
        #            if storagetype == "ephemeral":
        #                cloud_utils.log_message(db, vdc_dbid, "%s - Ephemeral storage (GB) Needed: %s " %
        #                                              (vdc_row["name"], resources[storagetype]["capacity"]), type="Info")
        #                continue
        allocated = db.get_row("tblResourcesStorage",
                               "tblEntities = %s AND catagory = 'total' AND storageclassesid = %s " % (
                                   vdc_row["parententityid"], class_id),
                               order="ORDER BY id LIMIT 1") or {"Capacity": 0, "IOPS": 0, "Network": 0}
        deploy_id = vdc_row["parententityid"]
        if allocated["Capacity"] == 0:  ####################### and int(class_id) == 0:
            dept_check = False
            cloud_utils.log_message(db, vdc_dbid,
                                    "%s - Skipping department storage  resource check for class %s - none assigned"
                                    % (vdc_row["name"], class_name), type="Info")
            dept_row = db.get_row_dict("tblEntities", {"id": vdc_row["parententityid"]}, order="ORDER BY id LIMIT 1")
            allocated = db.get_row("tblResourcesStorage",
                                   "tblEntities = %s AND catagory = 'total' AND  storageclassesid = %s " % (
                                       dept_row["ParentEntityId"], class_id),
                                   order="ORDER BY id LIMIT 1") or {"Capacity": 0, "IOPS": 0, "Network": 0}
            deploy_id = dept_row["ParentEntityId"]

        deployed = db.get_row("tblResourcesStorage",
                              "tblEntities = %s AND catagory = 'deployed' AND storageclassesid = %s " % (
                                  deploy_id, class_id),
                              order="ORDER BY id LIMIT 1") or {"Capacity": 0, "IOPS": 0, "Network": 0}
        available = {"Capacity": allocated["Capacity"] - deployed["Capacity"]}

        #        if (allocated["Capacity"] == 0 and int(class_id) == 0 ) or (available["Capacity"] >= resources["capacity"]):
        #            if allocated["Capacity"] == 0 and  int(class_id) == 0:
        if (allocated["Capacity"] == 0) or (available["Capacity"] >= resources["capacity"]):
            if allocated["Capacity"] == 0:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Skipping organization storage resource check for class %s - none assigned"
                                        % (vdc_row["name"], class_name), type="Info")
            if reserve:
                reserve_storage_resources(db, resources, vdc_row, class_id, class_name=class_name, allocated=allocated,
                                          available=available)
            else:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Storage class %s resources. Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"], class_name,
                                           allocated["Capacity"], deployed["Capacity"],
                                           available["Capacity"], resources["capacity"]), type="Info")
        else:
            if not dept_check:
                cloud_utils.log_message(db, vdc_dbid, "%s - Storage resource check from Organization resource pool"
                                        % (vdc_row["name"]), type="Info")
            if available["Capacity"] < resources["capacity"]:
                cloud_utils.log_message(db, vdc_dbid,
                                        "%s - Storage class %s resources. Allocated: %s Deployed: %s Available: %s Needed: %s "
                                        % (vdc_row["name"], class_name,
                                           allocated["Capacity"], deployed["Capacity"],
                                           available["Capacity"], resources["capacity"]), type="Warn")
            return "failed"
        return "success"
    except:
        cloud_utils.log_exception(sys.exc_info())
    return "failed"


def reserve_storage_resources(db, resources, vdc_row, class_id, class_name=None, allocated=None, available=None):
    try:
        if not class_name:
            class_name = id2name(db, class_id)

        deployed = db.get_row("tblResourcesStorage",
                              "tblEntities = %s AND catagory = 'deployed' AND storageclassesid = %s " % (
                                  vdc_row["id"], class_id),
                              order="ORDER BY id LIMIT 1") or {"Capacity": 0, "IOPS": 0, "Network": 0}
        if allocated and available:
            cloud_utils.log_message(db, vdc_row["id"],
                                    "%s - Storage class %s resources. Allocated: %s Deployed: %s Available: %s Provisioning: %s "
                                    % (vdc_row["name"], class_name,
                                       allocated["Capacity"], deployed["Capacity"],
                                       available["Capacity"], resources["capacity"]), type="Info")
        cloud_utils.update_or_insert(db, "tblResourcesStorage", {"tblentities": vdc_row["id"],
                                                                 "capacity": (
                                                                     resources["capacity"] + deployed["Capacity"]),
                                                                 "iops": (resources["iops"] + deployed["IOPS"]),
                                                                 "network": (resources["net"] + deployed["Network"]),
                                                                 "catagory": "deployed",
                                                                 "sliceid": vdc_row["selectedsliceentityid"]},
                                     {"tblentities": vdc_row["id"], "catagory": "deployed",
                                      "storageclassesid": class_id})
        update_virtual_resoures_tree_storage(db, vdc_row["parententityid"], vdc_row["selectedsliceentityid"], class_id)
        update_storage_slice_resources(db, vdc_row["selectedsliceentityid"], class_id)

    except:
        cloud_utils.log_exception(sys.exc_info())


def setup_resource_record():
    resources = {"storage_resources": {},
                 "compute_resources": {},
                 "network_resources": {}
                 }
    return resources


def add_compute_class(resources, class_id):
    if str(class_id) not in resources["compute_resources"]:
        resources["compute_resources"][str(class_id)] = {"vcpu": 0, "ram": 0, "network": 0, "ephemeral": 0}


def add_storage_class(resources, class_id):
    if str(class_id) not in resources["storage_resources"]:
        resources["storage_resources"][str(class_id)] = {"capacity": 0, "iops": 0, "net": 0}


def add_network_class(resources, class_id):
    if str(class_id) not in resources["network_resources"]:
        n_resources = {}
        for item in entity_constants.resource_network_services:
            n_resources[item] = {"throughput": 0, "maximum_throughput": 0}
        resources["network_resources"][str(class_id)] = n_resources


def add_network_resources(resources, service, throughput=0, maximum_throughput=0, override=False):
    class_id = str(service["networkclassid"])
    add_network_class(resources, service["networkclassid"])
    if not override and not throughput:
        throughput = service["throughput"]
        maximum_throughput = service["throughput"] * service["maxinstancescount"]

    if service["entitytype"] in entity_constants.virtual_entitytype_2_network_services:
        net_service = entity_constants.virtual_entitytype_2_network_services[service["entitytype"]]
        resources["network_resources"][class_id][net_service]["throughput"] += throughput
        resources["network_resources"][class_id][net_service]["maximum_throughput"] += maximum_throughput


def add_server_resources(resources, serverfarm, server, network):
    class_id = str(serverfarm['tblcomputeclassesid'])
    add_compute_class(resources, class_id)
    resources["compute_resources"][class_id]["vcpu"] += server["cpuvcpu"]
    resources["compute_resources"][class_id]["ram"] += server["memory"]
    resources["compute_resources"][class_id]["network"] += network
    if server["boot_storage_type"].lower() == "ephemeral":
        resources["compute_resources"][class_id]["ephemeral"] += server["ephemeral_storage"]


def add_volume_resources(resources, container, volume, network, resource_counts=True):
    class_id = str(container['tblstorageclassesid'])
    add_storage_class(resources, class_id)
    if resource_counts:
        resources["storage_resources"][class_id]["capacity"] += volume["capacity"]


def validate_resources(db, vdc_dbid, vdc_row, resources, reserve=False):
    return_status = "success"
    try:
        for class_id in resources["compute_resources"]:
            status = validate_compute_resources(db, vdc_dbid, vdc_row, resources["compute_resources"][class_id],
                                                class_id, reserve=reserve)
            if status != "success":
                if reserve:
                    return status
                return_status = "failed"
        for class_id in resources["storage_resources"]:
            status = validate_storage_resources(db, vdc_dbid, vdc_row, resources["storage_resources"][class_id],
                                                class_id, reserve=reserve)
            if status != "success":
                if reserve:
                    return status
                return_status = "failed"
        for class_id in resources["network_resources"]:
            status = validate_network_resources(db, vdc_dbid, vdc_row, resources["network_resources"][class_id],
                                                class_id, reserve=reserve)
            if status != "success":
                if reserve:
                    return status
                return_status = "failed"

    except:
        cloud_utils.log_exception(sys.exc_info())
    return return_status


def add_resources(master, item, LOG=LOG):
    for key in item:
        if key in master:
            if isinstance(item[key], dict):
                add_resources(master[key], item[key])
            else:
                master[key] += item[key]
        else:
            master[key] = item[key]


def negate_resources(resources):
    for key in resources:
        if isinstance(resources[key], dict):
            negate_resources(resources[key])
        else:
            resources[key] = -resources[key]


def get_compute_service_resources(db, dbid, check_status=None, LOG=LOG, resources=None):
    if not resources:
        resources = setup_resource_record()
    try:
        bw = get_service_bandwidth(db, dbid)
        for serverfarm in cloud_utils.entity_attach(db, dbid, entitytype="serverfarm"):
            if check_status and serverfarm["entitystatus"].lower() != "active":
                continue
            read_remaining_entity(db, serverfarm["id"], serverfarm)
            for server in cloud_utils.entity_children(db, serverfarm['id'], entitytype='server',
                                                      child_table="tblServers"):
                if check_status and server["entitystatus"].lower() != "active":
                    continue
                get_server_resources(db, server, serverfarm=serverfarm, network=bw, resources=resources)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return resources


def get_server_resources(db, server, network=None, serverfarm=None, storage_resources=None, LOG=LOG, resources=None):
    if not resources:
        resources = setup_resource_record()
    try:
        if network is None:
            network = 0
            if not serverfarm:
                serverfarm = read_full_entity(db, server["parententityid"])
            if not serverfarm:
                return resources
            farm_attach = db.get_row_dict("tblAttachedEntities",
                                          {"attachedentityid": serverfarm["id"], "attachedentitytype": "serverfarm"},
                                          order="ORDER BY id LIMIT 1")
            if farm_attach:
                network = get_service_bandwidth(db, farm_attach["tblEntities"])

        add_server_resources(resources, serverfarm, server, network)
        if storage_resources and server["boot_storage_type"].lower() == "volume":
            volume_attach = db.get_row_dict("tblAttachedEntities",
                                            {"tblEntities": server["id"], "attachedentitytype": "volume_boot"},
                                            order="ORDER BY id LIMIT 1")
            if volume_attach:
                volume_row = read_full_entity(db, volume_attach["AttachedEntityId"])
                if volume_row and volume_row["entitystatus"].lower() != "active":
                    container_row = read_full_entity(db, volume_row["parententityid"])
                    add_volume_resources(resources, container_row, volume_row, 0)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    return resources


def get_vdc_storage_resources(db, vdc, check_status=None, LOG=LOG, resources=None):
    if not resources:
        resources = setup_resource_record()
    try:
        for container in cloud_utils.entity_children(db, vdc["id"], entitytype="container",
                                                     child_table="tblContainers"):
            #            if check_status and container["entitystatus"].lower() != "active":
            #                continue
            get_container_resources(db, container, resources=resources, check_status=check_status)
            #            add_resources(resources, con)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    return resources


def get_container_resources(db, container, check_status=None, LOG=LOG, resources=None):
    if not resources:
        resources = setup_resource_record()

    try:
        for volume in cloud_utils.entity_children(db, container["id"], entitytype="volume",
                                                  child_table="tblContainerVolumes"):
            resource_counts = True
            if check_status and (
                            volume["entitystatus"].lower() != "active" and volume[
                        "entitystatus"].lower() != "allocated"):
                resource_counts = False
            get_volume_resources(db, volume, container=container, resources=resources, resource_counts=resource_counts)
            #            vol = get_volume_resources(db, volume, container=container, resources=resources)
            #            add_resources(resources, vol)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    return resources


def get_volume_resources(db, volume, container=None, LOG=LOG, resources=None, resource_counts=True):
    if not resources:
        resources = setup_resource_record()
    try:
        if not container:
            container = read_full_entity(db, volume["parententityid"])
        if not container:
            return resources
        container_attach = db.get_row_dict("tblAttachedEntities",
                                           {"attachedentityid": container["id"], "attachedentitytype": "container"},
                                           order="ORDER BY id LIMIT 1")
        if container_attach:
            network = get_service_bandwidth(db, container_attach["tblEntities"])
        else:
            network = 0
        add_volume_resources(resources, container, volume, network, resource_counts=resource_counts)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    return resources


def get_service_bandwidth(db, dbid):
    bw = db.execute_db("SELECT sum(GuarBandwidth) as bw "
                       " FROM tblEntities JOIN tblServicePorts "
                       "WHERE  (tblEntities.EntityType = 'service_port' AND tblEntities.deleted=0 AND "
                       "tblServicePorts.tblEntities = tblEntities.id AND "
                       "tblEntities.ParentEntityId = '%s')" % dbid)
    if bw:
        return int(bw[0].values()[0])
    else:
        return 0


def update_resources(db, entity, request, LOG=LOG):
    status = "failed"
    try:
        parent = read_full_entity(db, entity["parententityid"])
        if entity["entitytype"] == "volume":
            class_resources = get_volume_resources(db, entity, container=parent)
        elif entity["entitytype"] == "server":
            class_resources = get_server_resources(db, entity, serverfarm=parent, storage_resources=True)
        else:
            return status
        vdc_row = read_full_entity(db, parent["parententityid"])
        if request == "provision":
            status = validate_resources(db, vdc_row["id"], vdc_row, class_resources, reserve=True)
        elif request == "deprovision":
            negate_resources(class_resources)
            if entity["entitytype"] == "volume":
                for class_id in class_resources["storage_resources"]:
                    resources = class_resources["storage_resources"][class_id]
                    reserve_storage_resources(db, resources, vdc_row, class_id)
            else:
                for class_id in class_resources["compute_resources"]:
                    resources = class_resources["compute_resources"][class_id]
                    reserve_compute_resources(db, resources, vdc_row, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
    return status


def update_developer_resources(db, user_dbid):
    try:
        acl = db.get_row("tblEntitiesACL", "tblEntities = %s " % user_dbid, order="ORDER BY id LIMIT 1")
        if not acl:
            LOG.critical(_("Unable to get user ACL record for dbid: %s" % user_dbid))
            return
        if acl["AclRole"] != "developer":
            return
        user = utils.cache_utils.get_cache("db|tblEntities|id|%s" % user_dbid, None, db_in=db)
        if not user:
            return
        group = utils.cache_utils.get_cache("db|tblEntities|id|%s" % user["parententityid"], None, db_in=db)
        if not group:
            return
        org = utils.cache_utils.get_cache("db|tblEntities|id|%s" % group["parententityid"], None, db_in=db)
        if not org:
            return
        org_ext = db.get_row("tblOrganizations", " tblEntities = %s " % org["id"], order="ORDER BY id LIMIT 1")
        if not org_ext:
            return

        if org_ext["flavors_enabled"] != 0:
            flavors = db.get_multiple_row("tblResourcesFlavors",
                                          "tblEntities = %s and catagory = 'deployed'  " % user_dbid)
            if not flavors:
                return
            for flavor in flavors:
                count = db.execute_db(
                    "SELECT count(*) as count FROM tblEntities JOIN tblServers ON tblEntities.id = tblServers.tblEntities "
                    " WHERE (tblEntities.parententityid = %s and tblEntities.entitytype='server' and tblEntities.deleted=0 AND "
                    "tblEntities.entitystatus ='Active' and tblServers.tblflavors=%s ) "
                    % (acl["AclEntityId"], flavor["tblFlavors"]))
                db.execute_db("UPDATE tblResourcesFlavors SET Quantity = %s, updated_at=now() "
                              " WHERE id =%s  " % (count[0]["count"], flavor["id"]))
            return

        cpu = 0
        ram = 0
        storage = 0
        servers = db.get_multiple_row("tblEntities",
                                      "entitytype='server' AND parententityid = '%s' AND entitystatus ='Active' AND  deleted=0  " %
                                      acl["AclEntityId"])
        if servers:
            for entity in servers:
                server = db.get_row("tblServers", "tblEntities = %s " % entity["id"])
                if not server:
                    continue
                cpu += server["CPUVcpu"]
                ram += server["Memory"]
                storage += server["ephemeral_storage"]
        cloud_utils.update_or_insert(db, "tblResourcesCompute",
                                     {"tblentities": user_dbid, "cpu": cpu, "ram": ram, "catagory": "deployed"},
                                     {"tblentities": user_dbid, "catagory": "deployed"})

        if acl["ContainerEntityId"] != 0:
            storage = 0
            volumes = db.get_multiple_row("tblEntities",
                                          "entitytype='volume' AND parententityid = '%s' AND (entitystatus ='Active' or entitystatus ='Allocated') AND  deleted=0  " %
                                          acl["ContainerEntityId"])
            if volumes:
                for entity in volumes:
                    volume = db.get_row("tblContainerVolumes", "tblEntities = %s " % entity["id"])
                    if not volume:
                        continue
                    storage += volume["Capacity"]
        cloud_utils.update_or_insert(db, "tblResourcesStorage", {"tblentities": user_dbid, "capacity": storage,
                                                                 "type": "gold", "catagory": "deployed"},
                                     {"tblentities": user_dbid, "catagory": "deployed", "type": "gold"})
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_throughputs(db, options):
    try:
        if options["entitytype"] in entity_constants.virtual_entitytype_2_network_services:
            phy_entity = db.get_row("tblEntities", "deleted=0 AND "
                                                   "EntityType = '%s' AND entitysubtype='slice_network_entity' " %
                                    entity_constants.virtual_2_physical_entitytypes[options["entitytype"]],
                                    order="ORDER BY id DESC LIMIT 1")
            if phy_entity:
                phy_entity_ext = db.get_row("tblNetworkEntities", "tblEntities=%s " % phy_entity["id"],
                                            order="ORDER BY id DESC LIMIT 1")
                if phy_entity_ext:
                    return phy_entity_ext["Throughputs"]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ''


def id2name(db, dbid):
    if dbid:
        #entity = cache_utils.get_cache("db|tblEntities|id|%s" % dbid, None, db_in=db) TODO why does this not work
        entity = db.get_row_dict("tblEntities", {"id": dbid})
        if entity:
            return entity["name"]
    return "Default"
