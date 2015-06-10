__author__ = 'vkoro_000'

import entity.validate_entity as validate
import entity.provision_entity as prov
import utils.cloud_utils
import entity.entity_utils
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

def validate_vdc(db, dbid, options, ent_row):
    global _return_object
    _return_object = [{"options": options, "dbid": dbid,
                    "caller": validate.validate_entity,
                    #"callback": validate_entity_completed,
                    "entity": ent_row}]

    if options and "commandid" in options:
        commandid = options["commandid"]
    else:
        commandid = utils.cloud_utils.generate_uuid()

    return validate.validate_vdc(db, _return_object)

def reserve_resources(db, dbid, options, ent_row):
    global _return_object
    return_obj = _return_object
    #return_obj = validate_vdc_api_get_returnobj(db, dbid, options, ent_row)
    resources = return_obj[0]["resources"]
    return entity.entity_utils.validate_resources(db, dbid, ent_row, resources, reserve=True)

def provision(db, dbid, options, ent_row):
    global _return_object
    vdc_progress = 100
    event_object = _return_object
    status = prov.create_vdc_profiles(db, event_object, vdc_progress=vdc_progress)
    if status != "success":
        return status

    status = prov.create_vdc_services(db, event_object, mode="Create", vdc_progress=vdc_progress)
    if status != "success":
        return status

    status = prov.provision_vdc_manager(db, event_object, vdc_progress=vdc_progress)
    if status != "success":
        return status

    status = prov.create_vdc_services(db, event_object, mode="Provision", vdc_progress=vdc_progress)
    return status