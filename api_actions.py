__author__ = 'vkoro_000'

import entity.validate_entity as validate
import entity.provision_entity as prov
import utils.cloud_utils
import entity.entity_utils
import entity.entity_functions
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

def validate_vdc(db, dbid, options, ent_row): #TODO dont use global object, return dict of status, and the return_object
    ent_row["selectedsliceentityid"] = 0
    ent_row["child_id"] = ent_row["id"]
    _return_object = [{"options": options, "dbid": dbid,
                    "caller": validate.validate_entity,
                    #"callback": validate_entity_completed,
                    "entity": ent_row}]

    if options and "commandid" in options:
        commandid = options["commandid"]
    else:
        commandid = utils.cloud_utils.generate_uuid()
    dashboard = entity.entity_utils.DashBoard(db, ent_row["id"], ent_row, ent_row["name"], "Validate VDC", "Validating", commandid,
                                       title="Topology validating")
    _return_object[-1]["dashboard"] = dashboard
    dashboard.update_vdc_entitystatus(db, "Ready")
    res = validate.validate_vdc(db, _return_object)
    return {"status": res, "return_object": _return_object}

def reserve_resources(db, dbid, options, ent_row, return_obj=None):
    if return_obj is None:
        return_obj = validate_vdc(db, dbid, options, ent_row)["return_object"]
    ent_row = return_obj[-1]["entity"]
    return_obj[-1]["options"] = options
    #return_obj = validate_vdc_api_get_returnobj(db, dbid, options, ent_row)
    resources = return_obj[-1].get("resources", {})
    dashboard = return_obj[-1]["dashboard"]
    res = entity.entity_utils.validate_resources(db, dbid, ent_row, resources, reserve=True)
    #res = prov.provision_vdc(db, return_obj, vdc_progress=100)
    dashboard.update_vdc_entitystatus(db, "Ready")
    return res

# def prov2(db, dbid, options, ent_row):
#     return_object = validate_vdc(db, dbid, options, ent_row)["return_object"]
#     return_object[-1]["options"] = options
#     print return_object
#     return prov.provision_vdc(db, return_object)

def provision(db, dbid, options, ent_row, return_object):
    # if return_obj is None:
    #     return_obj = validate_vdc(db, dbid, options, ent_row)["return_object"]
    # ent_row = return_obj[-1]["entity"]
    # vdc_progress = 100
    # return_obj[-1]["options"] = options
    eve = entity.entity_functions.EntityFunctions(db, dbid, return_object=return_object, quick_provision=True)
    status = eve.do(db, "command", options=options)
    return status

    #return prov.provision_entity(db, dbid, options=options)
    # dashboard = return_obj[-1]["dashboard"]
    # status = prov.create_vdc_profiles(db, return_obj, vdc_progress=vdc_progress)
    # if status != "success":
    #     utils.cloud_utils.log_exception("Failed to create vdc profiles")
    #     dashboard.update_vdc_entitystatus(db, "Ready")
    #     return status
    #
    # status = prov.create_vdc_services(db, return_obj, mode="Create", vdc_progress=vdc_progress)
    # if status != "success":
    #     utils.cloud_utils.log_exception("Failed to create vdc services")
    #     dashboard.update_vdc_entitystatus(db, "Ready")
    #     return status
    #
    # status = prov.provision_vdc_manager(db, return_obj, vdc_progress=vdc_progress)
    # if status != "success":
    #     utils.cloud_utils.log_exception("Failed to provision vdc manager")
    #     dashboard.update_vdc_entitystatus(db, "Ready")
    #     return status
    #
    # status = prov.create_vdc_services(db, return_obj, mode="Provision", vdc_progress=vdc_progress)
    # dashboard.update_vdc_entitystatus(db, "Ready")
    # return status

def activate(db, dbid, command_options, return_object):
    #return prov.activate_vdc(db, return_obj)
    eve = entity.entity_functions.EntityFunctions(db, dbid, return_object=return_object, quick_provision=True)
    status = eve.do(db, "command", options=command_options)
    return status
    #return prov.activate_entity(db, dbid, options=command_options)
    #return prov.start_activate_vdc(return_obj)

def deprovision(db, ent_id, command_options):
    return prov.deprovision_entity(db, ent_id, options=command_options)