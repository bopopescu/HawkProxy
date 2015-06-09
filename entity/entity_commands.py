#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
# import gflags
# import gettext
import time
import eventlet
# import traceback
import ujson
# import Queue
import string

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
# import rest.rest_api as rest_api
from utils.underscore import _
import entity_manager
import provision_entity
import validate_entity
import entity_functions
import entity_file
import tech_support
import entity_utils
# import utils.cache_utils as cache_utils
import utils.cache_utils as cache_utils
import extjs_direct.extjs_commands


def rpc_functions(db, entity, dbid, function, options):
    try:
        if entity.lower() == "direct":
            return extjs_direct.extjs_commands.process_direct_command(db, entity, dbid, function, options)

        if entity.lower() == "entity":
            if options and "usertype" in options and options["usertype"] == "developer":
                return process_developer_api(db, entity, dbid, function, options)
            if function.lower() == "command":
                return entity_commands(db, dbid, options=options)
            elif function.lower() == "delete_multiple":
                return delete_multiple(db, dbid, options=options)
            elif function.lower() == "update_multiple":
                return update_multiple(db, dbid, options=options)
            elif function.lower() == "file":
                return entity_file.file_ops(db, dbid, options=options)
            elif function.lower() == "multiple_functions":
                return multiple_functions(db, dbid, options=options)
            else:
                eve = entity_functions.EntityFunctions(db, dbid)
                return eve.do(db, function, options=options)

        if entity.lower() == "db":
            if function.lower() == "update":
                if "delete" in options and isinstance(options["delete"], list):
                    for row in options["delete"]:
                        db.update_db("DELETE from %s WHERE id='%s'" % (row["table"], row["id"]))

        if entity.lower() == "login":
            return entity_functions.user_login(db, dbid, function, options=options)

        if entity.lower() == "user":
            return entity_functions.user_functions(db, dbid, function, options=options)

            #            if entity.lower() == "validate":
            #                return validate.validate_entity(db, dbid, options=options)

            #            if entity.lower() == "provision":
            #                return provision.provision_entity(db, dbid, function, options=options)

            #            if entity.lower() == "activate":
            #                return provision.activate_entity(db, dbid, options=options)

        if entity.lower() == "slice":
            eve = entity_functions.SliceFunctions(db, dbid)
            return eve.do(db, function, options=options)

        if entity.lower() == "organization":
            eve = entity_functions.OrganizationFunctions(db, dbid)
            return eve.do(db, function, options=options)

        if entity.lower() == "department":
            eve = entity_functions.DepartmentFunctions(db, dbid)
            return eve.do(db, function, options=options)

        if entity.lower() == "vdc":
            eve = entity_functions.VDCFunctions(db, dbid)
            return eve.do(db, function, options=options)

        if entity.lower() == "hawk":
            if function.lower() == "version":
                return ujson.dumps({"version": cloud_utils.get_hawk_version()})

        if entity.lower() == "cloudflow":
            return tech_support.support_commands(db, function, options)

        if entity.lower() == "system":
            eve = entity_functions.SystemFunctions(db)
            status = eve.do(db, function, options=options)
            return ujson.dumps({"result_code": 0, "status": status, "dbid": dbid})

        if entity.lower() == "class":
            return create_update_classes(db, entity, dbid, function, options)

    except:
        cloud_utils.log_exception(sys.exc_info())

    return ujson.dumps({"result_code": -1, "result_message": "invalid function", "dbid": dbid})


def entity_commands(db, dbid, options=None):
    try:
        if ("command" not in options.keys() or not isinstance(options["command"], basestring)) and \
                ("commands" not in options.keys() or not isinstance(options["commands"], list)):
            return ujson.dumps(
                {"result_code": -1, "result_message": "invalid parameters - command missing", "dbid": dbid})

        if "commandid" not in options.keys():
            options["commandid"] = cloud_utils.generate_uuid()

        if "command" in options.keys():
            current_options = options
            command = {}
        else:
            if len(options["commands"]) == 0:
                return
            command = options["commands"].pop(0)
            current_options = {"command": command}

        if current_options["command"].lower() == "provision":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return provision_entity.provision_entity(db, dbid, options=options)

        if current_options["command"].lower() == "validate":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return validate_entity.validate_entity(db, dbid, options=options)

        if current_options["command"].lower() == "cancel":
            row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": dbid},
                                                        order="ORDER BY id LIMIT 1"))
            if row:
                db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})

                db.execute_db("INSERT INTO tblEntities (Name, ParentEntityId, EntityType) "
                              "VALUES ('%s', '%s', '%s')" % (current_options["command"], dbid, "user_action"))

        if current_options["command"].lower() == "activate":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return provision_entity.activate_entity(db, dbid, options=options)

        if current_options["command"].lower() == "suspend":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return provision_entity.suspend_entity(db, dbid, options=options)

        if current_options["command"].lower() == "deprovision":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return provision_entity.deprovision_entity(db, dbid, options=options)

        if current_options["command"].lower() == "clear":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return provision_entity.clear_entity(db, dbid, options=options)

        if current_options["command"].lower() == "paste":
            db.delete_rows_dict("tblEntities", {"parententityid": dbid, "entitytype": "user_action"})
            return provision_entity.paste(db, dbid, options=options)

        eve = entity_functions.EntityFunctions(db, dbid, return_object=[options])
        return eve.do(db, "command", options=current_options)

    except:
        cloud_utils.log_exception(sys.exc_info())

    return ujson.dumps({"result_code": -1, "result_message": "exception detected", "dbid": dbid})


def delete_multiple(db, dbid, options=None):
    try:
        if "dbid" not in options.keys() and not isinstance(options["dbid"], list):
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - ids missing", "dbid": 0})

        ids = options["dbid"]
        return_option = "upon_completion"
        if "return_option" in options.keys():
            return_option = options["return_option"]
        if return_option == "upon_completion":
            delete_entities(ids, dbin=db)
        else:
            eventlet.spawn_n(delete_entities, ids)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": 0})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"result_code": -1, "result_message": "exception detected", "dbid": 0})


def delete_entities(ids, dbin=None):
    if dbin:
        db = dbin
    else:
        db = cloud_utils.CloudGlobalBase(log=False)
    for dbid in ids:
        eve = entity_functions.EntityFunctions(db, dbid)
        eve.do(db, "delete")
    if not dbin:
        db.close(log=None)


def update_multiple(db, dbid, options=None):
    try:
        if "entities" not in options.keys() and not isinstance(options["entities"], list):
            return ujson.dumps(
                {"result_code": -1, "result_message": "invalid parameters - entities missing", "dbid": 0})

        entities = options["entities"]
        return_option = "upon_completion"
        if "return_option" in options.keys():
            return_option = options["return_option"]
        if return_option == "upon_completion":
            update_entities(entities, dbin=db)
        else:
            eventlet.spawn_n(update_entities, entities)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": 0})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"result_code": -1, "result_message": "exception detected", "dbid": 0})


def update_entities(entities, dbin=None):
    if dbin:
        db = dbin
    else:
        db = cloud_utils.CloudGlobalBase(log=False)
    for entity in entities:
        dbid = entity.pop("id", 0)
        eve = entity_functions.EntityFunctions(db, dbid)
        eve.do(db, "update", entity)
    if not dbin:
        db.close(log=None)


def do_functions(functions, user_row, dbin=None):
    try:
        if dbin:
            db = dbin
        else:
            db = cloud_utils.CloudGlobalBase(log=False)
        for function in functions:
            if not isinstance(function, dict):
                LOG.critical(_("multilple api functions item %s is not a dict") % function)
                return
            dbid = function.pop("dbid", 0)
            entity = function.pop("entity", "entity")
            func = function.pop("type", "status")
            options = function.pop("options", None)
            if options:
                if isinstance(options, basestring):
                    o = ujson.loads(options)
                    if o:
                        options = dict(zip(map(string.lower, o.keys()), o.values()))
                    else:
                        options = {}
            else:
                options = {}
            if not isinstance(options, dict):
                options = {}
            options["user_row"] = user_row
            rpc_functions(db, entity, dbid, func, options)
        if not dbin:
            db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def multiple_functions(db, dbid, options=None):
    try:
        if "functions" not in options.keys() or not isinstance(options["functions"], list):
            LOG.critical(_("multilple api functions key invalid or missing"))
            return ujson.dumps(
                {"result_code": -1, "result_message": "invalid parameters - functions missing", "dbid": 0})

        functions = options["functions"]
        user_row = options["user_row"]

        eventlet.spawn_n(do_functions, functions, user_row)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": 0})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"result_code": -1, "result_message": "exception detected", "dbid": 0})


def process_developer_api(db, entity, dbid, function, options):
    if function.lower() == "create":
        eve = entity_functions.EntityFunctions(db, dbid)
        return eve.do(db, function, options=options)
    elif function.lower() == "update":
        return create_developer_vm(db, entity, dbid, function, options)
    elif function.lower() == "delete":
        return delete_developer_vm(db, entity, dbid, function, options)
    else:
        eve = entity_functions.EntityFunctions(db, dbid)
        return eve.do(db, function, options=options)


def old_create_developer_vm(db, entity, dbid, function, options):
    try:
        volume_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                           {"tblEntities": dbid,
                                                            "attachedentitytype": "volume_boot"},
                                                           order="ORDER BY id LIMIT 1"))
        if volume_row:
            return ujson.dumps({"result_code": -1, "result_message": "boot-volume duplicate", "dbid": dbid})

        eve = entity_functions.EntityFunctions(db, 0)
        response = eve.do(db, "create", options={"entitytype": "volume",
                                                 "capacity": options["bootvolumestorage"],
                                                 "parententityid": options["containerentityid"]})
        if not response:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to create boot-volume", "dbid": dbid})
        response = ujson.loads(response)
        if "dbid" not in response:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to create boot-volume", "dbid": dbid})

        volume_id = response["dbid"]
        cloud_utils.insert_db(db, "tblAttachedEntities", {"tblEntities": dbid, "AttachedEntityId": volume_id,
                                                          "AttachedEntityType": "volume_boot"})
        options["boot_storage_type"] = "volume"
        eve = entity_functions.EntityFunctions(db, dbid)
        response = eve.do(db, "update", options=options)
        if not response:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to create update server", "dbid": dbid})

        response = ujson.loads(response)
        eve = entity_functions.EntityFunctions(db, dbid)
        return eve.do(db, "command", options={"command": "provision"})
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_developer_vm(db, entity, dbid, function, options):
    try:
        if "user_row" not in options:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to create locate user rowr", "dbid": dbid})

        if "flavor" in options:
            flavor_row = cloud_utils.lower_key(db.get_row_dict("tblFlavors",
                                                               {"id": options["flavor"]}, order="ORDER BY id LIMIT 1"))
            if flavor_row:
                options["bootvolumestorage"] = flavor_row["storage"]
                options["cpuvcpu"] = flavor_row["cpu"]
                options["memory"] = flavor_row["memory"]
                options["tblFlavors"] = options["flavor"]
        else:
            options["tblFlavors"] = 0

        deployed_compute = db.get_row("tblResourcesCompute",
                                      "tblEntities = %s AND catagory = 'deployed' " % (options["user_row"]["id"]),
                                      order="ORDER BY id LIMIT 1")

        cloud_utils.update_or_insert(db, "tblResourcesCompute", {"tblentities": options["user_row"]["id"],
                                                                 "cpu": (options["cpuvcpu"] + deployed_compute["CPU"]),
                                                                 "ram": (options["memory"] + deployed_compute["RAM"]),
                                                                 "catagory": "deployed"},
                                     {"tblentities": options["user_row"]["id"], "catagory": "deployed"})

        deployed_storage = db.get_row("tblResourcesStorage",
                                      "tblEntities = %s AND catagory = 'deployed' AND type ='Gold' " % (
                                          options["user_row"]["id"]),
                                      order="ORDER BY id LIMIT 1")

        cloud_utils.update_or_insert(db, "tblResourcesStorage", {"tblentities": options["user_row"]["id"],
                                                                 "capacity": (
                                                                     options["bootvolumestorage"] + deployed_storage[
                                                                         "Capacity"]),
                                                                 "type": "gold", "catagory": "deployed"},
                                     {"tblentities": options["user_row"]["id"], "catagory": "deployed", "type": "gold"})
        if options["tblFlavors"] != 0:
            db.execute_db("UPDATE tblResourcesFlavors SET Quantity = Quantity+1, updated_at=now() "
                          " WHERE (tblEntities  = %s AND tblFlavors = %s AND  catagory = 'deployed' ) "
                          % (options["user_row"]["id"], options["tblFlavors"]))

        user = cache_utils.get_cache("db|tblUsers|tblEntities|%s" % options["user_row"]["id"], None, db_in=db)
        options["boot_storage_type"] = user["boot_storage_type"]
        if user["boot_storage_type"].lower() == "volume":
            volume_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                               {"tblEntities": dbid,
                                                                "attachedentitytype": "volume_boot"},
                                                               order="ORDER BY id LIMIT 1"))
            if volume_row:
                volume_id = volume_row["attachedentityid"]
            else:
                eve = entity_functions.EntityFunctions(db, 0)
                response = eve.do(db, "create", options={"entitytype": "volume",
                                                         "usertype": "developer",
                                                         "tblFlavors": options["tblFlavors"],
                                                         "capacity": options.get("bootvolumestorage", 8),
                                                         "parententityid": options["containerentityid"]})
                if not response:
                    return ujson.dumps(
                        {"result_code": -1, "result_message": "Unable to create boot-volume", "dbid": dbid})
                response = ujson.loads(response)
                if "dbid" not in response:
                    return ujson.dumps(
                        {"result_code": -1, "result_message": "Unable to create boot-volume", "dbid": dbid})
                volume_id = response["dbid"]

                cloud_utils.insert_db(db, "tblAttachedEntities", {"tblEntities": dbid, "AttachedEntityId": volume_id,
                                                                  "AttachedEntityType": "volume_boot"})
            options["volume_id"] = volume_id
            eventlet.spawn_n(developer_volume, options)

        options["command"] = "provision"
        options["entitystatus"] = "Processing"

        eve = entity_functions.EntityFunctions(db, dbid)
        return eve.do(db, "update", options=options)
    except:
        cloud_utils.log_exception(sys.exc_info())


def developer_volume(options):
    time.sleep(5)
    db = cloud_utils.CloudGlobalBase(log=False)
    retry = 100
    try:
        while True:
            time.sleep(3)
            uri = db.get_row_dict("tblUris", {"tblEntities": options["volume_id"]}, order="ORDER BY id LIMIT 1")
            if uri:
                break
            retry -= 1
            if retry == 0:
                LOG.critical(_(
                    "Unable to get desired status after 100 reties in 3 second intervals for dbid: %s" % options[
                        "volume_id"]))
                return
        eve = entity_functions.EntityFunctions(db, options["volume_id"])
        eve.do(db, "status", options=options)
    except:
        cloud_utils.log_exception(sys.exc_info())
    finally:
        db.close()


def wait_for_status(db, dbid, status_list):
    retry = 100
    while True:
        time.sleep(3)
        entity = db.get_row_dict("tblEntities", {"id": dbid}, order="ORDER BY id LIMIT 1")
        if entity and entity["EntityStatus"].lower() in status_list:
            return entity
        retry -= 1
        if not entity or retry == 0:
            LOG.critical(_("Unable to get desired status after 100 reties in 3 second intervals for dbid: %s" % dbid))
            return


completion_status = ["ready", "aborted"]


def delete_developer_vm(db, entity, dbid, function, options):
    try:
        if "user_row" not in options:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to create locate user rowr", "dbid": dbid})

        volume_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                           {"tblEntities": dbid,
                                                            "attachedentitytype": "volume_boot"},
                                                           order="ORDER BY id LIMIT 1"))

        server = db.get_row_dict("tblEntities", {"id": dbid}, order="ORDER BY id LIMIT 1")
        if not server:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to delete developer vm", "dbid": dbid})

        if server["EntityStatus"].lower() == "active":
            eve = entity_functions.EntityFunctions(db, dbid)
            response = ujson.loads(eve.do(db, "command", options={"command": "deprovision"}))
            if not response or "result_code" not in response or response["result_code"] != 0:
                return ujson.dumps({"result_code": -1, "result_message": "Unable to delete developer vm", "dbid": dbid})

            result = wait_for_status(db, dbid, completion_status)
            if not result:
                return ujson.dumps(
                    {"result_code": -1, "result_message": "Unable to deprovisoin developer vm", "dbid": dbid})

        eve = entity_functions.EntityFunctions(db, dbid)
        response = ujson.loads(eve.do(db, "delete"))

        if not volume_row:
            entity_utils.update_developer_resources(db, options["user_row"]["id"])
            LOG.critical(_("Unable to locate volume associated with a developer vm: %s" % dbid))
            return ujson.dumps(response)

        volume = db.get_row_dict("tblEntities", {"id": volume_row["attachedentityid"]}, order="ORDER BY id LIMIT 1")
        if not volume:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to delete developer vm",
                                "dbid": volume_row["attachedentityid"]})
        eventlet.spawn_n(delete_developer_volume, volume)
        entity_utils.update_developer_resources(db, options["user_row"]["id"])
        return ujson.dumps(response)

        '''
        if volume["EntityStatus"].lower() == "active" or volume["EntityStatus"].lower() == "allocated":
            eve = entity_functions.EntityFunctions(db, volume["id"])
            response = ujson.loads(eve.do(db, "command", options={"command":"deprovision"}))

            if not response or "result_code" not in response or response["result_code"] != 0:
                return ujson.dumps({"result_code": -1, "result_message": "Unable to delete developer volume", "dbid": volume["id"]})

            result = wait_for_status(db, volume["id"], completion_status)
            if not result:
                return ujson.dumps({"result_code": -1, "result_message": "Unable to deprovisoin developer volume", "dbid": volume["id"]})

        eve = entity_functions.EntityFunctions(db, volume["id"])
        return eve.do(db, "delete")
        '''

    except:
        cloud_utils.log_exception(sys.exc_info())


def delete_developer_volume(volume):
    db = cloud_utils.CloudGlobalBase(log=False)
    try:
        if not volume:
            return ujson.dumps({"result_code": -1, "result_message": "Unable to delete developer vm",
                                "dbid": volume["attachedentityid"]})

        if volume["EntityStatus"].lower() == "active" or volume["EntityStatus"].lower() == "allocated":
            eve = entity_functions.EntityFunctions(db, volume["id"])
            response = ujson.loads(eve.do(db, "command", options={"command": "deprovision"}))

            if not response or "result_code" not in response or response["result_code"] != 0:
                return ujson.dumps(
                    {"result_code": -1, "result_message": "Unable to delete developer volume", "dbid": volume["id"]})

            result = wait_for_status(db, volume["id"], completion_status)
            if not result:
                return ujson.dumps({"result_code": -1, "result_message": "Unable to deprovisoin developer volume",
                                    "dbid": volume["id"]})

        eve = entity_functions.EntityFunctions(db, volume["id"])
        eve.do(db, "delete")

    except:
        cloud_utils.log_exception(sys.exc_info())
    finally:
        db.close()


def create_update_classes(db, entity, dbid, function, options):
    eve = entity_functions.EntityFunctions(db, dbid)
    json_result = eve.do(db, function, options=options)
    result_dict = ujson.loads(json_result)
    if "result_code" in result_dict and result_dict["result_code"] == 0:
        eventlet.spawn_n(update_slices, function, result_dict["dbid"])
    return json_result


def update_slices(function, dbid):
    db = cloud_utils.CloudGlobalBase(log=False)
    try:
        if function == "create" or function == "update":
            function = "provision"
        for item in cloud_utils.get_entity(db, "slice", child_table=entity_manager.entities["slice"].child_table):
            if "virtual_infrastructure_url" not in item or item["entitystatus"].lower() != "active":
                continue
            if function == "provision":
                eve = entity_functions.EntityFunctions(db, dbid, slice_row=item, quick_provision=True)
                result = eve.do(db, function)
            else:
                uri_row = cloud_utils.lower_key(
                    db.get_row_dict("tblUris", {"tblEntities": dbid, "tblSlices": item["id"],
                                                "type": "home"}, order="ORDER BY id LIMIT 1", ignore_deleted=True))
                if uri_row:
                    entity_utils.delete_entity(uri_row["uri"])

    except:
        cloud_utils.log_exception(sys.exc_info())
    finally:
        db.close()
