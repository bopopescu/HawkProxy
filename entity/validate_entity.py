#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import eventlet
import json
import datetime
import ujson

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

from utils.underscore import _

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
import entity.entity_constants as entity_constants

import entity_manager
import entity_utils


def validate_entity(db, dbid, options=None):
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if error:
            return json.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": dbid})

        # add = {"entitytype": "job_queue", "parententityid": dbid, "deleted": 0,
        #                "command": ujson.dumps(options),"status": "Started", "jobserviceentityid": dbid}
        #        jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None, child_table="tblJobsQueue")
        return_object = [{"options": options, "dbid": dbid,
                          #                        "jobid": jobid,
                          "caller": validate_entity, "callback": validate_entity_completed, "entity": row}]

        if row["entitytype"] == "vdc":
            if options and "commandid" in options:
                commandid = options["commandid"]
            else:
                commandid = cloud_utils.generate_uuid()
            dashboard = entity_utils.DashBoard(db, row["id"], row, row["name"], "Validate VDC", "Validating", commandid,
                                               title="Topology validating")
            return_object[-1]["dashboard"] = dashboard

            eventlet.spawn_n(start_validate_vdc, return_object)
            return json.dumps({"result_code": 0, "result_message": "validation in progress", "dbid": dbid})

        eventlet.spawn_n(entity_manager.entities[row["entitytype"]].validate_entity_function, return_object)
        return json.dumps({"result_code": 0, "result_message": "validation in progress", "dbid": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_entity_completed(return_object):
    db = cloud_utils.CloudGlobalBase(log=None)
    # job completed!
    #    jobid = return_object[-1]["jobid"]
    #    cloud_utils.update_only(db, "tblEntities", {"progress": 100, "status": "Completed"},
    #                                 {"id": jobid}, child_table= "tblJobsQueue")
    db.close(log=None)


def validate_service(return_object):
    try:

        db = cloud_utils.CloudGlobalBase(log=None)

        dashboard = return_object[-1]["dashboard"]
        #        event = return_object[-1].get("event", None)
        #        jobid = return_object[-1]["jobid"]
        entity = return_object[-1]["entity"]
        dbid = return_object[-1]["dbid"]

        dashboard.vdc_mode = "Validate"
        dashboard.footnote = "Validating VDC Network Service."

        cloud_utils.log_message(db, dbid, "Starting service %s Validation" % entity["name"])
        result = "success"

        dashboard.service_name = entity["name"]
        dashboard.service_dbid = entity["id"]
        dashboard.service_type = entity_manager.entities[entity["entitytype"]].rest_header
        dashboard.service_elapsed_time = datetime.datetime.utcnow()
        dashboard.service_last_report_time = ""
        dashboard.register_current_service_status(db, "Validating")

        resources = entity_utils.setup_resource_record()
        entity_utils.add_network_resources(resources, entity)
        entity["resources"] = resources

        interface_count = cloud_utils.get_network_interface_count(db, entity["id"])
        status = entity_manager.entities[entity["entitytype"]].validate_entity_function(db, dashboard.vdc_name,
                                                                                        entity["id"], interface_count,
                                                                                        entity)
        if status == "failed":
            result = status
            dashboard.register_current_service_status(db, "ValidationFailed")
            cloud_utils.log_message(db, dbid, "Service: %s failed validation" % entity["name"])
        else:
            dashboard.register_current_service_status(db, "Validated")
            cloud_utils.log_message(db, dbid, "Service: %s passed validation" % entity["name"])

        return_object[-1]["resources"] = resources
        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def start_validate_vdc(return_object):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)

        #        jobid = return_object[-1]["jobid"]
        dbid = return_object[-1]["dbid"]
        entity = return_object[-1]["entity"]
        dashboard = return_object[-1]["dashboard"]
        status = validate_vdc(db, return_object)
        resources = return_object[-1].get("resources", {})
        resource_status = entity_utils.validate_resources(db, dbid, entity, resources, reserve=False)
        if status == "failed" or resource_status == "failed":
            dashboard.final(db, "%s failed validation -- See message log" % entity["name"], "error")
        else:
            dashboard.final(db, "%s passed validation " % entity["name"], "ok")
        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())

# def validate_vdc_api_get_returnobj(db, dbid, options, ent_row):
#     return_object = [{"options": options, "dbid": dbid,
#                     "caller": validate_entity,
#                     #"callback": validate_entity_completed,
#                     "entity": ent_row}]
#
#     if options and "commandid" in options:
#         commandid = options["commandid"]
#     else:
#         commandid = cloud_utils.generate_uuid()
#     dashboard = entity_utils.DashBoard(db, ent_row["id"], ent_row, ent_row["name"], "Validate VDC", "Validating", commandid,
#                                        title="Topology validating")
#     return_object[-1]["dashboard"] = dashboard
#     validate_vdc(db, return_object)
#     return return_object

def validate_vdc_api(db, dbid, options, ent_row):
    global _return_object
    _return_object = [{"options": options, "dbid": dbid,
                    "caller": validate_entity,
                    #"callback": validate_entity_completed,
                    "entity": ent_row}]

    if options and "commandid" in options:
        commandid = options["commandid"]
    else:
        commandid = cloud_utils.generate_uuid()
    dashboard = entity_utils.DashBoard(db, ent_row["id"], ent_row, ent_row["name"], "Validate VDC", "Validating", commandid,
                                       title="Topology validating")
    _return_object[-1]["dashboard"] = dashboard

    return validate_vdc(db, _return_object)

def reserve_resources_api(db, dbid, options, ent_row):
    global _return_object
    return_obj = _return_object
    #return_obj = validate_vdc_api_get_returnobj(db, dbid, options, ent_row)
    resources = return_obj[0]["resources"]
    return entity_utils.validate_resources(db, dbid, ent_row, resources, reserve=True)

# status = create_vdc_profiles(db, event_object, vdc_progress=vdc_progress)
# if status != "success":
#     dashboard.update_vdc_entitystatus(db, "Ready")
#     return status
#
# status = create_vdc_services(db, event_object, mode="Create", vdc_progress=vdc_progress)
# if status != "success":
#     dashboard.update_vdc_entitystatus(db, "Ready")
#     return
#
# status = provision_vdc_manager(db, event_object, vdc_progress=vdc_progress)
# if status != "success":
#     dashboard.update_vdc_entitystatus(db, "Ready")
#     return status
#
# status = create_vdc_services(db, event_object, mode="Provision", vdc_progress=vdc_progress)
# if status != "success":
#     dashboard.update_vdc_entitystatus(db, "Ready")
#     return


def validate_vdc(db, return_object, vdc_progress=100):
    try:
        db = cloud_utils.CloudGlobalBase(log=None)

        dashboard = return_object[-1]["dashboard"]
        event = return_object[-1].get("event", None)
        #        jobid = return_object[-1]["jobid"]
        entity = return_object[-1]["entity"]
        dbid = return_object[-1]["dbid"]

        dashboard.vdc_mode = "Validate VDC"
        dashboard.footnote = "Validating VDC Network Services..."
        dashboard.vdc_entitystatus = "Validating"

        cloud_utils.log_message(db, dbid, "Starting %s validation" % entity["name"])
        result = "success"

        resources = entity_utils.setup_resource_record()

        for service in entity_utils.get_next_service(db, dbid):
            dashboard.service_name = service["name"]
            dashboard.service_dbid = service["id"]
            dashboard.service_type = entity_manager.entities[service["entitytype"]].rest_header
            dashboard.service_elapsed_time = datetime.datetime.utcnow()
            dashboard.service_last_report_time = ""
            dashboard.register_service_status(db, service["id"], "Validating")

            #            if service["entitytype"] not in resources["network_resources"][0]["0"]:
            #                resources["network_resources"][0]["0"[service["entitytype"]] = {"throughput": 0, "maximum_throughput": 0 }

            entity_utils.add_network_resources(resources, service)
            service["resources"] = resources
            #            resources["network_resources"][0]["0"][service["entitytype"]]["throughput"] += service["throughput"]
            #            resources["network_resources"][0]["0"][service["entitytype"]]["maximum_throughput"] += (service["throughput"]* service["maxinstancescount"])

            dashboard.vdc_progress += ((1 * 10 * vdc_progress) / (dashboard.vdc_services_count * 100))
            dashboard.register_event(db)
            interface_count = cloud_utils.get_network_interface_count(db, service["id"])
            status = entity_manager.entities[service["entitytype"]]. \
                validate_entity_function(db, dashboard.vdc_name, service["id"], interface_count, service)

            if status == "failed":
                result = status
                dashboard.register_service_status(db, service["id"], "ValidationFailed")
            else:
                dashboard.register_service_status(db, service["id"], "Validated")

                #            if "resources" in service:
                #                entity_utils.add_resources(resources, service["resources"])

        dashboard.clear_service()
        dashboard.update_interfaces("Validated")
        dashboard.register_vdc_status(db, "Validated")

        if result == "failed":
            cloud_utils.log_message(db, dbid, "%s Network services failed validation" % entity["name"], type="Warn")
        else:
            cloud_utils.log_message(db, dbid, "%s Network services passed validation" % entity["name"])

        # get and add storage resources
        entity_utils.get_vdc_storage_resources(db, entity, resources=resources)

        return_object[-1]["resources"] = resources
        if event:
            return_object[-1]["return_status"] = result
            event.send({"return_status": result})
        db.close(log=None)
        return result

    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_nat(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "NAT"
        cloud_utils.log_message(db, service["parententityid"],
                                "%s - %s - Starting validation with %s interfaces" % (ntype, service["name"],
                                                                                      interface_count))
        result = "success"
        if interface_count < 2:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 2 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")
        else:
            for row in cloud_utils.network_service_ports(db, dbid):
                drow = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": row["destinationserviceentityid"]},
                                                             order="ORDER BY id LIMIT 1"))
                itype = "south_bound"
                if drow["entitytype"] == "externalnetwork":
                    itype = "north_bound"
                cloud_utils.log_message(db, service["parententityid"], "%s: %s - Interface %s set as %s" % (
                    vdc_name, service["name"], drow["name"], itype))
                cloud_utils.update_only(db, "tblEntities", {"interface_type": itype},
                                        {"id": row["id"]}, child_table="tblServicePorts")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def verify_external_network(db, id):
    if not id or id == 0:
        return None
    # read the attached row - must be only one and must be of type slice external network or intranet
    row = db.get_row_dict("tblAttachedEntities", {"tblEntities": id}, order="ORDER BY id LIMIT 1")
    if row:
        entity = db.get_row_dict("tblEntities", {"id": row["AttachedEntityId"], "deleted": 0},
                                 order="ORDER BY id LIMIT 1")
        if entity:
            return entity
        else:
            row = cloud_utils.lower_key(row)
            if row["attachedentitytype"] == "slice_attached_network":
                slice = db.get_row_dict("tblEntities",
                                        {"name": row["attachedentityparentname"], "entitytype": "slice", "deleted": 0},
                                        order="ORDER BY id LIMIT 1")
                if not slice:
                    return None
                ext_net = db.get_row_dict("tblEntities",
                                          {"name": row["attachedentityname"],
                                           "entitytype": "slice_attached_network", "parententityid": slice["id"],
                                           "deleted": 0},
                                          order="ORDER BY id LIMIT 1")
                if not ext_net:
                    return None
                db.update_db(
                    "UPDATE tblAttachedEntities SET AttachedEntityId='%s' WHERE id='%s'" % (ext_net["id"], row["id"]))
                return ext_net


def validate_externalnetwork(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "External network"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation  %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 1:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count of %s is fewer than minimum 1 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")
        else:
            if not verify_external_network(db, dbid):
                result = "failed"
                cloud_utils.log_message(db, service["parententityid"],
                                        "%s: %s - Error: An external network must be selected for external network service" %
                                        (vdc_name, service["name"]), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_switch(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Subnet"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation  %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 1:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 1 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_lbs(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Load Balancer"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 2:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 2 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], ntype, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_fws(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Firewall"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 2:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 2 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_rts(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Router"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 2:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 2 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")
        update_log(db, service["parententityid"], vdc_name, service["name"], result)
        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_ips(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "IPS"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 2:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 2 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)
        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_vpn(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Virtual private network"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 2:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 2 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)
        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def update_log(db, serviceid, vdc_name, name, result):
    if result == "failed":
        cloud_utils.log_message(db, serviceid, "%s - failed validation" % name, type="Warn")
    else:
        cloud_utils.log_message(db, serviceid, "%s - passed validation" % name)


def validate_compute(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Compute network service"
        cloud_utils.log_message(db, dbid, "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 1:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 1 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")
        update_log(db, service["parententityid"], vdc_name, service["name"], result)
        entity_utils.get_compute_service_resources(db, service["id"], resources=service["resources"])
        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_storage(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Storage network service"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 1:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 1 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())


def validate_nms(db, vdc_name, dbid, interface_count, service):
    try:
        ntype = "Network monitor"
        cloud_utils.log_message(db, service["parententityid"], "%s - %s - Starting validation with %s interfaces" % (
            ntype, service["name"], interface_count))
        result = "success"
        if interface_count < 1:
            result = "failed"
            cloud_utils.log_message(db, service["parententityid"],
                                    "%s: %s - Error: Interfaces count %s is fewer than minimum 1 required" %
                                    (vdc_name, service["name"], interface_count), type="Error")

        update_log(db, service["parententityid"], vdc_name, service["name"], result)

        return result
    except:
        cloud_utils.log_exception(sys.exc_info())
