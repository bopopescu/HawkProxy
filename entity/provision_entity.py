#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import gflags
import gettext
import time
import eventlet
import traceback
import json
import string
import Queue
import datetime
import jsonpickle
import ujson

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

from utils.underscore import _

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
import rest.rest_api as rest_api

import entity_manager
import entity_utils

import validate_entity
import entity_functions
import entity_commands

from eventlet import event


def paste(db, dbid, options=None):
    try:
        if "parententityid" in options:
            dbid = options["parententityid"]
        if not dbid:
            return json.dumps({"result_code": -1, "result_message": "Invalid VDC id", "dbid": dbid})
        if "items" not in options or not isinstance(options["items"], list):
            return json.dumps({"result_code": -1, "result_message": "no or invalid items specified", "dbid": dbid})

        eve = entity_functions.EntityFunctions(db, dbid)

        service_id_mapping = {}

        for _item in options["items"]:

            item = cloud_utils.lower_key(_item, remove_none=True)

            if "id" not in item:
                continue
            old_row = cloud_utils.lower_key(db.get_row("tblEntities", "id = %s" % item["id"]), remove_none=True)
            if not old_row:
                continue
            if old_row["entitytype"] == "network_interface":
                ext_row = cloud_utils.lower_key(db.get_row("tblServicesInterfaces", "tblEntities= %s" % item["id"]),
                                                remove_none=True)
                del ext_row["id"]
                old_row.update(ext_row)
                old_row["beginserviceentityid"] = service_id_mapping.get(item.get("sourceid", 0), 0)
                old_row["endserviceentityid"] = service_id_mapping.get(item.get("targetid", 0), 0)
                old_row.pop("beginserviceportid", None)
                old_row.pop("endserviceportid", None)

            elif old_row["entitysubtype"] == "network_service":
                ext_row = cloud_utils.lower_key(db.get_row("tblServices", "tblEntities= %s" % item["id"]),
                                                remove_none=True)
                del ext_row["id"]
                old_row.update(ext_row)

                old_row.pop("defaultgateways", None)
                old_row.pop("defaultgatewayentityid", None)

            else:
                continue

            if old_row["deleted"] == 0:
                old_row["name"] = old_row["name"] + "-" + entity_utils.create_entity_name(db, None)
            else:
                dup = entity_utils.entity_name_check(db, dbid, old_row["entitytype"], old_row["name"])
                if dup:
                    old_row["name"] = old_row["name"] + "-" + entity_utils.create_entity_name(db, None)

            old_row.update(item)

            old_row.pop("id", None)
            old_row.pop('created_at', None)
            old_row.pop('updated_at', None)
            old_row.pop('deleted_at', None)
            old_row.pop('deleted', None)

            old_row.pop('entitystatus', None)
            old_row.pop('entitydisabled', None)
            old_row.pop('entitymode', None)

            old_row.pop('clonedfromentityid', None)
            old_row.pop('uniqueid', None)
            old_row.pop('tblentities', None)

            json_response = eve.do(db, "create", old_row)
            response = ujson.loads(json_response)
            service_id_mapping[item["id"]] = response.get("dbid", 0)

        return json.dumps({"result_code": 0, "result_message": "completed", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def clear_entity(db, dbid, options=None):
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if error:
            return json.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": dbid})

        if row["entitytype"] != "vdc" and row["entitysubtype"] != "network_service":
            eve = entity_functions.EntityFunctions(db, dbid)
            return eve.do(db, "command", options=options)

        #### below is only for VDC ad network services

        if options and "commandid" in options:
            commandid = options["commandid"]
        else:
            commandid = cloud_utils.generate_uuid()

        if row["entitytype"] != "vdc":
            cloud_utils.log_message(db, dbid, "Service: %s - inavlid clear command" % row["name"], type="Warn")
            return json.dumps({"result_code": -1, "result_message": "inavlid clear command", "dbid": dbid})

        dashboard = entity_utils.DashBoard(db, row["id"], row, row["name"], "Clear", "ClearPending", commandid,
                                           title="Topology clearing", skip=True)
        dashboard.register_event(db)

        for ent in entity_utils.get_next_vdc_service(db, dbid):
            eve = entity_functions.EntityFunctions(db, ent["id"])
            status = eve.do(db, "delete")

        dashboard.final(db, "%s Topology canvas cleared successfully" % row["name"], "ok")

        return json.dumps({"result_code": 0, "result_message": "clear topology completed", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def deprovision_entity(db, dbid, options=None):
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if error:
            return json.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": dbid})

        if row["entitytype"] != "vdc" and row["entitysubtype"] != "network_service":
            eve = entity_functions.EntityFunctions(db, dbid)
            return eve.do(db, "command", options=options)

        #### below is only for VDC ad network services

        if options and "commandid" in options:
            commandid = options["commandid"]
        else:
            commandid = cloud_utils.generate_uuid()

        if row["entitytype"] == "vdc":
            vdc_row = row
        else:
            vdc_dbid = row["parententityid"]
            vdc_row, error = entity_utils.read_full_entity_status_tuple(db, vdc_dbid)
            if error:
                cloud_utils.log_message(db, dbid, "Service: %s - Unable to locate VDC record" % row["name"],
                                        type="Warn")
                return

        dashboard = entity_utils.DashBoard(db, vdc_row["id"], vdc_row, vdc_row["name"], "Deprovision",
                                           "DeprovisionPending", commandid, title="Topology deprovisioning")

        db.execute_db(
            "UPDATE tblEntities SET EntityStatus = 'Deprovisioning',  EntityMode = 'Deprovisioning'  WHERE (id='%s')" % dbid)

        #        add = {"entitytype": "job_queue", "parententityid": dbid, "deleted": 0,
        #                                    "command": ujson.dumps(options), "status": "Started", "jobserviceentityid": dbid}
        #        jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None, child_table="tblJobsQueue")

        return_object = [{"options": options, "dbid": dbid, "dashboard": dashboard,
                          "caller": deprovision_entity, "entity": row, "vdc_row": vdc_row}]
        #                                    "jobid": jobid, "caller": deprovision_entity, "entity": row, "vdc_row": vdc_row}]

        if row["entitysubtype"] == "network_service":
            eventlet.spawn_n(start_deprovision_service, return_object)
        else:
            dashboard.update_vdc_entitystatus(db, "Deprovisioning")
            dashboard.register_event(db)
            eventlet.spawn_n(start_deprovision_vdc, return_object)

        return json.dumps({"result_code": 0, "result_message": "deprovision completed", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def start_deprovision_vdc(return_object):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)

        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        entity["entitymode"] = "Deprovisioing"
        cloud_utils.log_message(db, dbid, "Deprovisioning %s... " % entity["name"])
        status = deprovision_vdc(db, return_object)
        dashboard.final(db,
                        "%s deprovisioned successfully in %s seconds" % (entity["name"], dashboard.completion_time()),
                        "ok")
        cloud_utils.log_message(db, dbid,
                                "VDC %s deprovisioned in %s seconds" % (entity["name"], dashboard.completion_time()))
        db.execute_db("UPDATE tblVdcs SET activated_at = NULL WHERE id=%s" % entity["child_id"])
        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def deprovision_vdc(db, return_object):
    try:
        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        dashboard.clear_service()
        dashboard.vdc_mode = "Deprovision"
        dashboard.footnote = "Deprovisioning all services..."
        dashboard.bottom_visibility = False
        dashboard.update_vdc_entitystatus(db, "Deprovisioning")

        evt = event.Event()
        return_object[-1]["event"] = evt
        return_object[-1]["caller"] = deprovision_vdc

        eve = entity_functions.EntityFunctions(db, dbid, return_object=return_object,
                                               callback=done_with_current_service)
        status = eve.do(db, "command", options={"command": "deprovision"})
        result = wait_and_log(evt, msg=" Deprovision %s " % entity["name"])
        entity_utils.reset_vdc_entities(db, dbid)
        #        if result["return_status"] != "success":
        #            return

        dashboard.update_services("Ready")
        dashboard.update_interfaces("Ready")
        dashboard.vdc_entitystatus = "Ready"
        dashboard.register_event(db)
        return result["return_status"]

    except:
        cloud_utils.log_exception(sys.exc_info())


def start_deprovision_service(return_object):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)

        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        entity["entitymode"] = "Deprovisioing"

        status = deprovision_service(db, return_object)
        dashboard.final(db, "Network service %s deprovisioned." % entity["name"], "ok")

        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def deprovision_service(db, return_object):
    try:
        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        vdc_row = return_object[-1]["vdc_row"]

        dashboard.vdc_mode = "Deprovision"
        dashboard.bottom_visibility = False
        dashboard.footnote = "Deprovisioning %s..." % entity["name"]

        dashboard.service_name = entity["name"]
        dashboard.service_dbid = entity["id"]
        dashboard.service_type = entity_manager.entities[entity["entitytype"]].rest_header
        dashboard.service_elapsed_time = datetime.datetime.utcnow()
        dashboard.service_last_report_time = ""
        dashboard.footnote = "Deprovisioning " + entity["name"] + "..."
        dashboard.update_service_taps(db, dbid, "Deprovisioning")

        dashboard.register_service_status(db, entity["id"], "Deprovisioning")

        evt = event.Event()
        rtn_obj = [{"caller": deprovision_service, "dbid": dbid, "event": evt, "dashboard": dashboard,
                    #                    "jobid": jobid
                    }]
        cloud_utils.log_message(db, vdc_row["id"], "%s: Deprovisioning  %s" % (vdc_row["name"], entity["name"]))
        eve = entity_functions.EntityFunctions(db, dbid, return_object=rtn_obj,
                                               callback=done_with_current_service)
        status = eve.do(db, "command", options={"command": "deprovision"})
        result = wait_and_log(evt, msg=" Deprovision %s " % entity["name"])
        entity_utils.reset_status_and_uri(db, dbid, 'Ready')
        dashboard.update_db_service_taps(db, dbid, "Ready")

        resources = entity_utils.setup_resource_record()

        #        resources = {"storage_resources":{},"compute_resources":{"vcpu":0, "ram":0,"network":0},"network_resources":{} }
        #        resources["network_resources"][entity["entitytype"]] = {"throughput": -entity["throughput"],
        #                                            "maximum_throughput": -(entity["throughput"] * entity["maxinstancescount"]) }

        #
        entity_utils.add_network_resources(resources, entity)
        entity_utils.negate_resources(resources)
        status = entity_utils.validate_resources(db, vdc_row["id"], vdc_row, resources, reserve=True)

        cloud_utils.log_message(db, vdc_row["id"], "%s: Service %s deprovisioned" % (vdc_row["name"], entity["name"]))

    except:
        cloud_utils.log_exception(sys.exc_info())


def suspend_entity(db, dbid, options=None):
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if error:
            return json.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": dbid})

        if row["entitytype"] != "vdc":
            eve = entity_functions.EntityFunctions(db, dbid)
            return eve.do(db, "command", options=options)

        if options and "commandid" in options:
            commandid = options["commandid"]
        else:
            commandid = cloud_utils.generate_uuid()

        dashboard = entity_utils.DashBoard(db, row["id"], row, row["name"], "Suspend", "SuspensionPending", commandid,
                                           title="Topology suspending")

        dashboard.register_event(db)

        #        add = {"entitytype": "job_queue", "parententityid": dbid, "deleted": 0,
        #               "command": ujson.dumps(options), "status": "Started", "jobserviceentityid": dbid}
        #        jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None, child_table="tblJobsQueue")

        return_object = [{"options": options, "dbid": dbid, "dashboard": dashboard,
                          #                          "jobid": jobid,
                          "caller": suspend_vdc,
                          "entity": row}]

        if row["entitystatus"].lower() == "suspended":
            cloud_utils.log_message(db, dbid, "%s  is already suspended" % row["name"])
            dashboard.final(db, "%s is already  suspended" % row["name"], "ok")
        else:
            dashboard.update_vdc_entitystatus(db, "Suspending")
            eventlet.spawn_n(start_suspend_vdc, return_object)

        return json.dumps({"result_code": 0, "result_message": "provision completed", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def start_suspend_vdc(return_object):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)

        #        jobid = return_object[-1]["jobid"]
        #        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        status = suspend_vdc(db, return_object)
        dashboard.final(db, "%s suspended successfully" % entity["name"], "ok")

        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def suspend_vdc(db, return_object):
    try:
        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        dashboard.clear_service()
        dashboard.bottom_visibility = False
        dashboard.vdc_mode = "Suspend"
        dashboard.footnote = "Suspending all services..."
        dashboard.register_event(db)

        evt = event.Event()
        return_object[-1]["event"] = evt
        return_object[-1]["caller"] = suspend_vdc

        eve = entity_functions.EntityFunctions(db, dbid, return_object=return_object,
                                               callback=done_with_current_service)
        status = eve.do(db, "command", options={"command": "suspend"})
        result = wait_and_log(evt, msg=" Suspend %s " % entity["name"])
        if result["return_status"] != "success":
            return
        cloud_utils.log_message(db, dbid, "%s suspended" % entity["name"])
        dashboard.update_services("Suspended")
        dashboard.update_interfaces("Suspended")
        dashboard.vdc_entitystatus = "Suspended"
        dashboard.register_event(db)
        dashboard.update_vdc_entitystatus(db, "Suspended")
        db.execute_db("UPDATE tblEntities SET EntityStatus = 'Suspended' "
                      "WHERE (EntityType = 'network_interface' AND ParentEntityId='%s' "
                      "AND deleted=0)" % dbid)

        db.execute_db("UPDATE tblEntities SET EntityStatus = 'Suspended' "
                      "WHERE (EntitySubType = 'network_service' AND ParentEntityId='%s' "
                      "AND deleted=0)" % dbid)

        return result["return_status"]
    except:
        cloud_utils.log_exception(sys.exc_info())


def resume_vdc(db, return_object):
    try:
        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        dashboard.clear_service()
        dashboard.bottom_visibility = False
        dashboard.vdc_mode = "Resume"
        dashboard.footnote = "Resuming all services..."
        dashboard.register_event(db)

        evt = event.Event()
        return_object[-1]["event"] = evt
        return_object[-1]["caller"] = resume_vdc

        eve = entity_functions.EntityFunctions(db, dbid, return_object=return_object,
                                               callback=done_with_current_service)
        status = eve.do(db, "command", options={"command": "resume"})
        result = wait_and_log(evt, msg=" Resume %s " % entity["name"])
        if result["return_status"] != "success":
            return
        cloud_utils.log_message(db, dbid, "%s resumed" % entity["name"])
        dashboard.update_services("Active")
        dashboard.update_interfaces("Active")
        dashboard.vdc_entitystatus = "Active"
        dashboard.register_event(db)
        dashboard.update_vdc_entitystatus(db, "Active")
        dashboard.final(db, "%s: Resumed successfully" % entity["name"], "ok")
        db.execute_db("UPDATE tblEntities SET EntityStatus = 'Active' "
                      "WHERE (EntityType = 'network_interface' AND ParentEntityId='%s' "
                      "AND deleted=0)" % dbid)

        db.execute_db("UPDATE tblEntities SET EntityStatus = 'Active' "
                      "WHERE (EntitySubType = 'network_service' AND ParentEntityId='%s' "
                      "AND deleted=0)" % dbid)

        return result["return_status"]
    except:
        cloud_utils.log_exception(sys.exc_info())


def activate_entity(db, dbid, options=None):
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if error:
            return json.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": dbid})

        if options and "commandid" in options:
            commandid = options["commandid"]
        else:
            commandid = cloud_utils.generate_uuid()

        dashboard = entity_utils.DashBoard(db, row["id"], row, row["name"], "Activate", "ActivationPending", commandid,
                                           title="Topology activating")
        dashboard.register_event(db)

        #        add = {"entitytype": "job_queue", "parententityid": dbid, "deleted": 0,
        #             "command": ujson.dumps(options), "status": "Started", "jobserviceentityid": dbid}
        #        jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None, child_table="tblJobsQueue")

        return_object = [{"options": options, "dbid": dbid, "dashboard": dashboard,
                          #                          "jobid": jobid,
                          "caller": activate_entity, "entity": row}]

        if row["entitystatus"].lower() == "active":
            dashboard.final(db, "%s is already  activated" % row["name"], "ok")
            cloud_utils.log_message(db, dbid, "%s is already activated" % row["name"], type="Warn")

        elif row["entitymode"].lower() != "ready" and row["entitymode"].lower() != "suspended":
            dashboard.final(db, "Unable to activate. %s is in %s state." % (row["name"], row["entitymode"]), "ok")
            cloud_utils.log_message(db, dbid,
                                    "Unable to activate. %s is in %s state." % (row["name"], row["entitymode"]),
                                    type="Warn")
        else:
            dashboard.update_vdc_entitystatus(db, "Activating")
            eventlet.spawn_n(start_activate_vdc, return_object)
        return json.dumps({"result_code": 0, "result_message": "provision completed", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def start_activate_vdc(return_object):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)

        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        if entity["entitystatus"].lower() == "provisioning" or \
                        entity["entitystatus"].lower() == "activating" or \
                        entity["entitystatus"].lower() == "suspending" or \
                        entity["entitystatus"].lower() == "deprovisioning":
            status = deprovision_vdc(db, return_object)
            if status != "success":
                db.close(log=None)
                return
            entity, error = entity_utils.read_full_entity_status_tuple(db, dbid)

        if entity["entitystatus"].lower() == "ready":
            status = provision_vdc(db, return_object, vdc_progress=80)
            if status != "success":
                db.close(log=None)
                return
            entity, error = entity_utils.read_full_entity_status_tuple(db, dbid)

        if entity["entitystatus"].lower() == "suspended":
            dashboard.update_vdc_entitystatus(db, "Resuming")
            dashboard.register_event(db)
            status = resume_vdc(db, return_object)

        elif entity["entitystatus"].lower() == "provisioned":
            status = activate_vdc(db, return_object)
        else:
            dashboard.final(db, "Please retry", "error")
            cloud_utils.log_message(db, dbid, "%s: Unable to process command due to current state: %s" %
                                    (entity["name"], entity["entitystatus"]), type="Warn")
        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def activate_vdc(db, return_object):
    try:

        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]

        dashboard.clear_service()
        dashboard.bottom_visibility = False
        dashboard.vdc_mode = "Activate"
        dashboard.footnote = "Activating all services..."

        dashboard.service_type = ""
        dashboard.service_elapsed_time = None
        dashboard.service_progress = 0

        dashboard.register_event(db)

        evt = event.Event()
        return_object[-1]["event"] = evt
        return_object[-1]["caller"] = activate_vdc

        eve = entity_functions.EntityFunctions(db, dbid, return_object=return_object,
                                               callback=done_with_current_service)
        status = eve.do(db, "command", options={"command": "activate"})
        result = wait_and_log(evt, msg=" Activate %s " % entity["name"])

        if result["return_status"] != "success":
            deprovision_vdc_on_error(status, db, dbid, entity, dashboard,
                                     message="%s activation failed - Deprovisioned" % entity["name"])
        else:
            cloud_utils.log_message(db, dbid,
                                    "%s activated in %s seconds" % (entity["name"], dashboard.completion_time()))
            dashboard.update_services("Active")
            dashboard.update_interfaces("Active")
            dashboard.vdc_entitystatus = "Active"
            dashboard.register_event(db)
            dashboard.update_vdc_entitystatus(db, "Active")
            dashboard.final(db,
                            "%s activated successfully in %s seconds" % (entity["name"], dashboard.completion_time()),
                            "ok")
            db.execute_db("UPDATE tblEntities SET EntityStatus = 'Active',  EntityMode = 'Active'"
                          "WHERE (EntityType = 'network_interface' AND ParentEntityId='%s' "
                          "AND deleted=0)" % dbid)

            db.execute_db("UPDATE tblEntities SET EntityStatus = 'Active', EntityMode = 'Active' "
                          "WHERE (EntitySubType = 'network_service' AND ParentEntityId='%s' "
                          "AND deleted=0)" % dbid)

            db.execute_db("UPDATE tblVdcs SET activated_at = NOW() WHERE id=%s" % entity["child_id"])
    except:
        cloud_utils.log_exception(sys.exc_info())


def provision_entity(db, dbid, options=None):
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if error:
            return json.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": dbid})

        if row["entitytype"] in entity_manager.entities:
            function_2be_called = entity_manager.entities[row["entitytype"]].provision_entity_function
        else:
            return json.dumps({"result_code": -1, "result_message": "error in command", "dbid": dbid})

        if function_2be_called is None:
            eve = entity_functions.EntityFunctions(db, dbid)
            return eve.do(db, "command", options=options)

        # jobspec = {"entitytype": "job_queue", "parententityid": dbid, "deleted": 0,
        #              "command": ujson.dumps(options), "status": "Started", "jobserviceentityid": dbid}
        #        jobid = cloud_utils.update_or_insert(db, "tblEntities", jobspec, None, child_table="tblJobsQueue")

        return_object = [{"options": options, "dbid": dbid,
                          #                        "jobid": jobid,
                          "caller": provision_entity, "callback": provision_entity_completed, "entity": row}]

        if options and "commandid" in options:
            commandid = options["commandid"]
        else:
            commandid = cloud_utils.generate_uuid()

        return_object[-1]["commandid"] = commandid

        if row["entitytype"] == "vdc":
            dashboard = entity_utils.DashBoard(db, row["id"], row, row["name"], "Validate", "ValidationPending",
                                               commandid, title="Topology provisioning")
            dashboard.register_event(db)
            return_object[-1]["dashboard"] = dashboard

            if row["entitystatus"].lower() == "active" or row["entitystatus"].lower() == "suspended":
                dashboard.final(db, "%s is already  provisioned" % row["name"], "ok")
                cloud_utils.log_message(db, dbid, "%s is already provisioned" % row["name"])

            elif row["entitystatus"].lower() != "ready":
                dashboard.final(db, "%s is in %s state - Please deprovision before retrying" % (
                    row["name"], row["entitystatus"]), "ok")
                cloud_utils.log_message(db, dbid, "%s is in %s state - Please deprovision before retrying" % (
                    row["name"], row["entitystatus"]), type="Warn")
            else:
                eventlet.spawn_n(start_provision_vdc, return_object)
        else:
            eventlet.spawn_n(function_2be_called, return_object)

        return json.dumps({"result_code": 0, "result_message": "provision in progress", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())
    return json.dumps({"result_code": -1, "result_message": "error in command", "dbid": dbid})


def provision_entity_completed(db, return_object):
    #
    #    jobid = return_object[-1]["jobid"]
    #    entity = return_object[-1]["entity"]
    #    dbid = return_object[-1]["dbid"]
    return_status = return_object[-1]["return_status"]

    # job completed!
    #    cloud_utils.update_only(db, "tblEntities", {"progress": 100, "status": return_status},
    #                            {"id": jobid}, child_table="tblJobsQueue")
    if return_status != "failed":
        if return_object and isinstance(return_object, list):
            if len(return_object) > 0:
                obj = return_object.pop(0)
                if "options" in obj and "dbid" in obj:
                    if "commands" in obj["options"]:
                        entity_commands.entity_commands(db, obj["dbid"], options=obj["options"])


def start_provision_vdc(return_object):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)
        status = provision_vdc(db, return_object)
        if status == "success":
            entity = return_object[-1]["entity"]
            dashboard = return_object[-1]["dashboard"]
            dashboard.final(db,
                            "%s provisioned successfully in %s seconds" % (entity["name"], dashboard.completion_time()),
                            "ok")
        return_object[-1]["return_status"] = status
        provision_entity_completed(db, return_object)
        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def select_vdc_slice(db, dbid, row):
    #    if row["defaultsliceentityId"] == 0:
    system_row = db.get_row_dict("tblEntities", {"entitytype": "system", "deleted": 0}, order="ORDER BY id LIMIT 1")
    for slice in cloud_utils.entity_members(db, system_row["id"], "slice", child_table="tblSlices"):
        if slice["entitystatus"].lower() == "active":
            return slice
    return None


def check_slice_status(db, dbid, sliceid):
    row, error = entity_utils.read_full_entity_status_tuple(db, sliceid)
    if error:
        return "Unknown", None
    if row["entitystatus"].lower() != "active":
        return row["name"], None
    return row["name"], True


def provision_service(return_object):
    try:
        entity = return_object[-1]["entity"]
        dbid = return_object[-1]["dbid"]
        commandid = return_object[-1]["commandid"]

        db = cloud_utils.CloudGlobalBase(log=False)

        vdc_dbid = entity["parententityid"]
        vdc_row, error = entity_utils.read_full_entity_status_tuple(db, vdc_dbid)
        if error:
            cloud_utils.log_message(db, dbid, "Service: %s - Unable to locate VDC record" % entity["name"], type="Warn")
            db.close(log=None)
            return

        dashboard = entity_utils.DashBoard(db, vdc_row["id"], vdc_row, vdc_row["name"], "Validate",
                                           "ValidationPending", commandid, title="Network service provisioning")
        dashboard.register_event(db)
        return_object[-1]["dashboard"] = dashboard

        dashboard.service_name = entity["name"]
        dashboard.service_dbid = entity["id"]
        dashboard.service_type = entity_manager.entities[entity["entitytype"]].rest_header

        if entity["entitymode"].lower() != "ready":
            dashboard.final(db, "Service %s is in %s state - Please deprovision before retrying" % (
                entity["name"], entity["entitystatus"]), "ok")
            cloud_utils.log_message(db, dbid, "%s: is in %s state - Please deprovision before retrying" %
                                    (entity["name"], entity["entitystatus"]), type="Warn")

        dashboard.register_current_service_status(db, "Provisioning")

        cloud_utils.log_message(db, vdc_dbid, "Service: %s - Starting validation" % entity["name"])
        name, status = check_slice_status(db, vdc_dbid, vdc_row["selectedsliceentityid"])

        if not status:
            dashboard.final(db, "Selected slice is unavailable. Provisioning aborted ", "error")
            cloud_utils.log_message(db, vdc_dbid, "%s: Selected slice %s is unavailable" % (vdc_row["name"], name),
                                    type="Warn")
            db.close(log=None)
            return

        event_object = [{"caller": provision_vdc, "dbid": dbid, "entity": entity, "dashboard": dashboard}]

        status = validate_entity.validate_service(event_object)
        if status != "success":
            dashboard.final(db, "Topology validation failed. Provisioning aborted ", "error")
            cloud_utils.log_message(db, dbid, "%s validation failed. Aborting provision" % entity["name"], type="Warn")
            db.close(log=None)
            return

        resources = event_object[-1].get("resources", {})
        status = entity_utils.validate_resources(db, vdc_row["id"], vdc_row, resources, reserve=True)
        if status != "success":
            dashboard.update_db_service_taps(db, dbid, "Ready")
            dashboard.final(db, "%s - Insufficient resources to provision. Provisioning aborted " % entity["name"],
                            "error")
            cloud_utils.log_message(db, dbid,
                                    "%s - Insufficient resources to provision VDC. Aborting provisioning" % entity[
                                        "name"], type="Warn")
            return status

        dashboard.vdc_mode = "Provision"
        dashboard.update_service_taps(db, dbid, "Provisioning")

        status = _provision_a_network_service(db, vdc_dbid, vdc_row, entity, dashboard, deprovision_on_error=False,
                                              final_state='Active')

        if status != "failed" and status != "cancel":
            cloud_utils.log_message(db, vdc_dbid, "Service: %s - Provisioned" % entity["name"])
            dashboard.update_db_service_taps(db, dbid, "Active")
            dashboard.final(db, "Service %s provisioned successfully" % entity["name"], "ok")
            db.execute_db("UPDATE tblEntities SET EntityStatus = 'Active'  WHERE (id='%s')" % dbid)
        else:
            dashboard.final(db, "Network service %s provisioning failed. Provisioning aborted" % entity["name"],
                            "error")

    except:
        cloud_utils.log_exception(sys.exc_info())


def provision_vdc(db, return_object, vdc_progress=100):
    try:
        dashboard = return_object[-1]["dashboard"]
        #        jobid = return_object[-1]["jobid"]
        entity = return_object[-1]["entity"]
        dbid = return_object[-1]["dbid"]

        dashboard.update_vdc_entitystatus(db, "Provisioning")

        cloud_utils.log_message(db, dbid, "Starting %s provision" % entity["name"])
        if entity["selectedsliceentityid"] != 0:
            srow, error = entity_utils.read_full_entity_status_tuple(db, entity["selectedsliceentityid"])
            if error:
                entity["selectedsliceentityid"] = 0
                cloud_utils.log_message(db, dbid,
                                        "%s: - Selected slice no longer exists  - selecting new one" % entity["name"])

        if entity["selectedsliceentityid"] == 0:
            slice = select_vdc_slice(db, dbid, entity)
            if slice:
                entity["selectedsliceentityid"] = slice["id"]
                cloud_utils.update_or_insert(db, "tblEntities", entity, {"id": dbid}, child_table="tblVdcs")
            else:
                dashboard.update_vdc_entitystatus(db, "Ready")
                cloud_utils.log_message(db, dbid, "%s: Unable to find any suitable slice" % entity["name"], type="Warn")
                dashboard.final(db, "No suitable slice availableat this time. Please try again ", "error")
                return "failed"
        name, status = check_slice_status(db, dbid, entity["selectedsliceentityid"])
        if not status:
            dashboard.update_vdc_entitystatus(db, "Ready")
            dashboard.final(db, "Selected slice is unavailable. Provisioning aborted ", "error")
            cloud_utils.log_message(db, dbid, "%s: Selected slice %s is unavailable" % (entity["name"], name),
                                    type="Warn")
            return "failed"

        event_object = [{"caller": provision_vdc, "dbid": dbid, "entity": entity, "dashboard": dashboard}]
        status = validate_vdc(db, event_object, vdc_progress=vdc_progress)
        if status != "success":
            dashboard.update_vdc_entitystatus(db, "Ready")
            dashboard.final(db, "%s failed validation. Provisioning aborted " % entity["name"], "error")
            cloud_utils.log_message(db, dbid, "%s failed validation. Aborting provisioning" % entity["name"],
                                    type="Warn")
            return status

        resources = event_object[-1].get("resources", {})
        status = entity_utils.validate_resources(db, dbid, entity, resources, reserve=True)
        if status != "success":
            dashboard.update_vdc_entitystatus(db, "Ready")
            dashboard.final(db, "%s - Insufficient resources to provision VDC. Provisioning aborted " % entity["name"],
                            "error")
            cloud_utils.log_message(db, dbid,
                                    "%s - Insufficient resources to provision VDC. Aborting provisioning" % entity[
                                        "name"], type="Warn")
            return status

        status = create_vdc_profiles(db, event_object, vdc_progress=vdc_progress)
        if status != "success":
            dashboard.update_vdc_entitystatus(db, "Ready")
            return status

        status = create_vdc_services(db, event_object, mode="Create", vdc_progress=vdc_progress)
        if status != "success":
            dashboard.update_vdc_entitystatus(db, "Ready")
            return

        status = provision_vdc_manager(db, event_object, vdc_progress=vdc_progress)
        if status != "success":
            dashboard.update_vdc_entitystatus(db, "Ready")
            return status

        status = create_vdc_services(db, event_object, mode="Provision", vdc_progress=vdc_progress)
        if status != "success":
            dashboard.update_vdc_entitystatus(db, "Ready")
            return
        # status = provision_vdc_profiles(db, event_object, vdc_progress=vdc_progress)
        #        if status != "success":
        #            dashboard.update_vdc_entitystatus(db, "Ready")
        #            return status

        #        status = provision_vdc_services(db, event_object, vdc_progress=vdc_progress)
        #        if status != "success":
        #            dashboard.update_vdc_entitystatus(db, "Ready")

        return status
    except:
        print sys.exc_info()
        cloud_utils.log_exception(sys.exc_info())


def provision_exit(db, return_object, result):
    event = return_object[-1].get("event", None)
    if event:
        return_object[-1]["return_status"] = result
        event.send({"return_status": result})


def validate_vdc(db, event_object, vdc_progress=100):
    #    evt = event.Event()
    #    event_object[-1]["event"] = evt
    result = validate_entity.validate_vdc(db, event_object, vdc_progress=vdc_progress)
    #    result = evt.wait()
    return result


def provision_vdc_manager(db, event_object, vdc_progress=100):
    try:
        dashboard = event_object[-1]["dashboard"]
        #        jobid = event_object[-1]["jobid"]
        entity = event_object[-1]["entity"]
        dbid = event_object[-1]["dbid"]

        dashboard.clear_service()
        dashboard.vdc_mode = "Provision"
        dashboard.vdc_entitystatus = ""
        dashboard.update_services("ProvisionPending")
        dashboard.update_interfaces("ProvisionPending")
        dashboard.service_name = dashboard.vdc_name
        dashboard.service_type = "VDC Manager"
        dashboard.service_elapsed_time = datetime.datetime.utcnow()
        dashboard.service_last_report_time = ""
        dashboard.footnote = "Provisioning VDC Manager..."
        dashboard.bottom_visibility = True
        dashboard.register_event(db)

        evt = event.Event()
        event_object[-1]["event"] = evt
        event_object[-1]["caller"] = provision_vdc_manager

        eve = entity_functions.EntityFunctions(db, dbid, return_object=event_object, callback=done_with_current_service)
        sts = eve.do(db, "command", options={"command": "reserve-resources"})

        result = wait_and_log(evt, msg=" Provision %s " % entity["name"])

        if result["return_status"] == "failed" or result["return_status"] == "cancel":
            deprovision_vdc_on_error(result["return_status"], db, dbid, entity, dashboard,
                                     message="%s vdc-manager provisioning failed" % entity["name"])
            return result["return_status"]

        if "response" not in event_object[-1] or \
                        "resources" not in event_object[-1]["response"] or \
                        event_object[-1]["response"]["resources"].lower() != "reserved":
            LOG.critical(_("provision failed: event_object:%s" % event_object[-1]))
            deprovision_vdc_on_error(result["return_status"], db, dbid, entity, dashboard,
                                     message="%s vdc-manager provisioning failed due to lack of resources" % entity[
                                         "name"])
            return "failed"

        cloud_utils.log_message(db, dbid, "%s: resources reserved" % entity["name"])

        db.update_db("UPDATE tblVdcs SET lastresynctime = now() WHERE id=%s" % entity["child_id"])

        evt = event.Event()
        event_object[-1]["event"] = evt
        eve = entity_functions.EntityFunctions(db, dbid, return_object=event_object, callback=done_with_current_service)
        sts = eve.do(db, "command", options={"command": "provision"})

        result = wait_and_log(evt, msg=" Provision %s " % entity["name"])

        if result["return_status"] == "failed" or result["return_status"] == "cancel":
            deprovision_vdc_on_error(result["return_status"], db, dbid, entity, dashboard,
                                     message="%s vdc-manager provisioning failed" % entity["name"])
        else:
            cloud_utils.log_message(db, dbid, "%s vdc-manager provisioning completed" % entity["name"])

        dashboard.vdc_progress += ((1 * 80 * vdc_progress) / ((dashboard.vdc_services_count + 1) * 100))
        return result["return_status"]
    except:
        print sys.exc_info()
        cloud_utils.log_exception(sys.exc_info())


def create_vdc_profiles(db, event_object, vdc_progress=100):
    try:
        dashboard = event_object[-1]["dashboard"]
        entity = event_object[-1]["entity"]
        dbid = event_object[-1]["dbid"]

        dashboard.clear_service()
        dashboard.bottom_visibility = True
        dashboard.vdc_mode = "Profiles"
        dashboard.footnote = "Updating profiles..."
        dashboard.register_event(db)

        # Provision all profiles
        status = "success"
        dashboard.current_name_label = "Current Profile"
        dashboard.current_type_label = "Profile Type"

        for profile in entity_utils.get_next_group(db, dbid):
            user_action_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"ParentEntityId": dbid,
                                                                                    "EntityType": "user_action"},
                                                                    order="ORDER BY id LIMIT 1"))
            if user_action_row:
                status = user_action_row["name"]
                db.delete_rows_dict("tblEntities", {"id": user_action_row["id"]})
                deprovision_vdc_on_error(status, db, dbid, entity, dashboard,
                                         message="%s provisioning cancelled by user" % entity["name"])
                break

            dashboard.service_name = profile["name"]
            dashboard.service_type = entity_manager.entities[profile["entitytype"]].rest_header

            dashboard.service_elapsed_time = datetime.datetime.utcnow()
            dashboard.service_last_report_time = ""
            dashboard.register_event(db)
            status = _provision_an_entity(db, dbid, entity, profile, dashboard, deprovision_on_error=True)
            if status == "failed" or status == "cancel":
                break

        dashboard.current_name_label = "Current Service"
        dashboard.current_type_label = "Service Type"

        dashboard.vdc_progress += (10 * vdc_progress / 100)
        return status

    except:
        cloud_utils.log_exception(sys.exc_info())


def create_vdc_services(db, event_object, mode="Create", vdc_progress=100):
    try:
        dashboard = event_object[-1]["dashboard"]
        #        jobid = event_object[-1]["jobid"]
        entity = event_object[-1]["entity"]
        dbid = event_object[-1]["dbid"]

        # Provision all network services
        dashboard.vdc_mode = mode
        dashboard.bottom_visibility = True
        status = "success"

        for service in entity_utils.get_next_service(db, dbid):
            if service["entitytype"] == "tap_network_service":
                continue

            status = _provision_a_network_service(db, dbid, entity, service, dashboard, mode=mode,
                                                  deprovision_on_error=True)
            if status == "failed" or status == "cancel":
                break

            if mode == "Create":
                cloud_utils.log_message(db, dbid, "Service %s created successfully in %s seconds" %
                                        (service["name"], dashboard.service_completion_time()))
                entity_utils.set_entity_mode(db, service["id"], "Created")
            elif mode == "Provision":
                cloud_utils.log_message(db, dbid, "Service %s provisioned successfully in %s seconds" %
                                        (service["name"], dashboard.service_completion_time()))
                entity_utils.set_entity_mode(db, service["id"], "Provisioned")

        if status != "failed" and status != "cancel":
            if mode == "Create":
                cloud_utils.log_message(db, dbid, "%s created successfully in %s seconds" % (
                    entity["name"], dashboard.completion_time()))
                dashboard.update_vdc_entitystatus(db, "Created")
                entity_utils.set_entity_mode(db, dbid, "Created")

            elif mode == "Provision":
                cloud_utils.log_message(db, dbid, "%s provisioned successfully in %s seconds" % (
                    entity["name"], dashboard.completion_time()))
                dashboard.update_vdc_entitystatus(db, "Provisioned")
                entity_utils.set_entity_mode(db, dbid, "Provisioned")

                db.execute_db("UPDATE tblEntities SET EntityStatus = 'ProvisionPending' "
                              "WHERE (EntityType = 'network_interface' AND ParentEntityId='%s' "
                              "AND deleted=0)" % dbid)
                dashboard.vdc_progress += ((1 * 80 * vdc_progress) / ((dashboard.vdc_services_count + 1) * 100))

        return status
    except:
        cloud_utils.log_exception(sys.exc_info())


def _provision_a_network_service(db, dbid, vdc_row, service_row, dashboard, mode="Create", deprovision_on_error=None,
                                 final_state=None):
    try:
        dashboard.service_name = service_row["name"]
        dashboard.service_dbid = service_row["id"]
        dashboard.service_type = entity_manager.entities[service_row["entitytype"]].rest_header
        dashboard.service_elapsed_time = datetime.datetime.utcnow()
        dashboard.service_last_report_time = ""
        dashboard.bottom_visibility = True

        if mode == "Create":
            dashboard.footnote = "Creating " + service_row["name"] + "..."
            dashboard.register_service_status(db, service_row["id"], "Creating")
        elif mode == "Provision":
            dashboard.footnote = "Provisioning " + service_row["name"] + "..."
            dashboard.register_service_status(db, service_row["id"], "Provisioning")

        status = _provision_an_entity(db, dbid, vdc_row, service_row, dashboard, entity_type="service", mode=mode,
                                      deprovision_on_error=deprovision_on_error, final_state=final_state)

        if status != "failed" and status != "cancel":
            dashboard.register_current_service_status(db, "Provisioned")
        return status
    except:
        cloud_utils.log_exception(sys.exc_info())
    return "failed"


http_code_conversion = {400: "Bad Request (HTTP 400) - Missing or invalid configuration data",
                        409: "Conflict (HTTP409) - Name or status conflict with an existing service",
                        500: "Internal Server Error (HTTP500) - Please retry",
                        503: "Invalid configuration (HTTP503) - Resource not available"
                        }


def convert_http_status(code):
    if code in http_code_conversion:
        return http_code_conversion[code]
    else:
        return http_code_conversion[500]


def _provision_an_entity(db, dbid, vdc_row, entity,
                         dashboard, entity_type="profile", mode="Create", deprovision_on_error=None, final_state=None):
    try:
        evt = event.Event()

        #        add = {"entitytype": "job_queue", "parententityid": entity["id"], "jobservicename":entity["name"],
        #              "command": ujson.dumps({"command":"post"}), "status": "Started", "jobserviceentityid": entity["id"], "primaryjobentityid":primary_jobid}

        #        jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None, child_table="tblJobsQueue")
        rtn_obj = [{"dbid": dbid, "event": evt, "dashboard": dashboard,
                    #                    "jobid": jobid,
                    "caller": _provision_an_entity}]
        if final_state:
            rtn_obj[-1]["final_state"] = final_state

        if mode == "Create":
            cloud_utils.log_message(db, dbid, "Creating %s" % (entity["name"]))
            eve = entity_functions.EntityFunctions(db, entity["id"], return_object=rtn_obj,
                                                   callback=done_with_current_service, row=entity, quick_provision=True)
            status = eve.do(db, "provision")
        elif mode == "Provision":
            cloud_utils.log_message(db, dbid, "Provisioning  %s" % (entity["name"]))
            eve = entity_functions.EntityFunctions(db, entity["id"], return_object=rtn_obj,
                                                   callback=done_with_current_service)
            status = eve.do(db, "command", options={"command": "provision"})
        else:
            return "failed"

        result = wait_and_log(evt, msg=" Provision %s " % entity["name"])
        rtn_obj = result.get("return_object", rtn_obj)

        if result["return_status"] == "failed" or result["return_status"] == "cancel":
            if deprovision_on_error and deprovision_on_error == True:
                deprovision_vdc_on_error(result["return_status"], db, dbid, vdc_row,
                                         dashboard, message="Provisioning for service %s failed - %s"
                                                            % (entity["name"], convert_http_status(
                        rtn_obj[-1].get("http_status_code", 500))))
            return "failed"
        else:
            #            cloud_utils.log_message(db, primary_jobid, dbid,
            #                                    "%s provisioned" % (entity["name"]))
            return "success"
    except:
        cloud_utils.log_exception(sys.exc_info())
        return "failed"


def done_with_current_service(dbid, return_status=None, return_object=None):
    try:
        if return_object and isinstance(return_object, list) and "event" in return_object[-1]:
            evt = return_object[-1]["event"]
            evt.send({"return_status": return_status, "return_object": return_object})
        else:
            LOG.critical(_("Unable to locate the eventfunction for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def deprovision_vdc_on_error(status, db, dbid, vdc_row, dashboard, message=None):
    try:
        if not message:
            message = "Deprovisioning due to errors - see message log"

        cloud_utils.log_message(db, dbid, "%s: %s" % (vdc_row["name"], message))

        evt = event.Event()
        rtn_obj = [{"caller": deprovision_vdc_on_error, "dbid": dbid, "event": evt, "dashboard": dashboard}]
        cloud_utils.log_message(db, dbid, "Deprovisioning %s" % vdc_row["name"])
        eve = entity_functions.EntityFunctions(db, dbid, return_object=rtn_obj, callback=done_with_current_service)
        status = eve.do(db, "command", options={"command": "deprovision"})
        result = wait_and_log(evt, msg=" Deprovision %s " % vdc_row["name"])
        cloud_utils.log_message(db, dbid, "%s deprovisioned" % vdc_row["name"])
        dashboard.update_vdc_entitystatus(db, "Ready")
        entity_utils.reset_vdc_entities(db, dbid)
        dashboard.final(db, message, "error")
        db.execute_db("UPDATE tblVdcs SET activated_at = NULL WHERE id=%s" % vdc_row["child_id"])

    except:
        cloud_utils.log_exception(sys.exc_info())


import threading
import eventlet.corolocal


def wait_and_log(evt, msg=""):
    LOG.info(_("Event %s start wait Thread name: %s id:%s green id:%s" % \
               (msg, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
    result = evt.wait()
    LOG.info(_("Event %s end wait Thread name: %s id:%s green id:%s" % \
               (msg, threading.currentThread().name, threading.currentThread().ident, eventlet.corolocal.get_ident())))
    return result
