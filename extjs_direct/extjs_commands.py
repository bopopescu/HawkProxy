#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import time
import eventlet
import ujson
import string

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
from utils.underscore import _
import entity.entity_utils
import entity.entity_constants as entity_constants
import utils.cache_utils as cache_utils


def process_direct_command(db, entity, dbid, function, options):
    if function and function in globals():
        return globals()[function](db, entity, dbid, function, options)
    return ujson.dumps({"success": "False"})


def anyDevicesExtraSpec(db, entity, dbid, function, options):
    try:
        type = options["body"]["type"]
        id = options["body"]["id"]
        class_extra_specs = options["body"]["extra_specs"]
        if not class_extra_specs:
            return ujson.dumps({"success": "True", "devices": []})
        devices = []
        for dev in get_next_device(db, class_extra_specs, type, process_class_id=False):
            devices.append({"description": dev["description"], "id": dev["id"], "name": dev["name"]})
        return ujson.dumps({"success": "True", "devices": devices})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def get_next_device(db, class_extra_specs, class_type, class_id=0, slice_id=0, process_class_id=True):
    try:
        entitytype = entity_constants.class_device_entitytype[class_type]
        if entitytype == "slice_network_entity":
            entitykey = "entitysubtype"
        else:
            entitykey = "entitytype"

        search_string = "%s = '%s' " % (entitykey, entitytype)
        if slice_id:
            search_string += " and parententityid = %s" % slice_id

        for dev in cloud_utils.get_generic_search(db, "tblEntities", search_string,
                                                  entity_constants.class_physical_child_tables[class_type]):
            if dev["entitystatus"].lower() != "active" or dev["entitypool"].lower() != "virtual":
                continue

            if not class_id and process_class_id:
                yield dev
                continue
            if class_id:
                attach_row = db.get_row_dict("tblAttachedEntities",
                                             {"tblEntities": class_id, "AttachedEntityId": dev["id"],
                                              "AttachedEntityType": entitytype}, order="ORDER BY id LIMIT 1")
                if attach_row:
                    yield dev
                    continue

            if not class_extra_specs:
                #                yield dev
                continue

            if "extra_specs" in dev and dev["extra_specs"]:
                try:
                    if dev["physical_specs"]:
                        dev_specs = ujson.loads(dev["physical_specs"])
                    else:
                        dev_specs = {}
                    if dev["extra_specs"]:
                        dev_specs.update(ujson.loads(dev["extra_specs"]))
                except:
                    continue
                matched = True
                for key, value in class_extra_specs.iteritems():
                    if ":" in key:  # skip over vendor scope
                        continue
                    if key not in dev_specs or value != dev_specs[key]:
                        matched = False
                        break
                if matched:
                    yield dev
    except:
        cloud_utils.log_exception(sys.exc_info())


def getOrganizationComputePopupDetails(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("organizationid", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        class_id = int(options.get("filterclass", 0))
        return get_entity_compute(db, entityid, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def getDepartmentComputePopupDetails(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("departmentid", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        class_id = int(options.get("filterclass", 0))
        return get_entity_compute(db, entityid, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def getOrganizationStoragePopupDetails(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("organizationid", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        class_id = int(options.get("filterclass", 0))
        return get_entity_storage(db, entityid, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def getDepartmentStoragePopupDetails(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("departmentid", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        class_id = int(options.get("filterclass", 0))
        return get_entity_storage(db, entityid, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def getOrganizationNetworkPopupDetails(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("organizationid", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        class_id = int(options.get("filterclass", 0))
        return get_entity_network(db, entityid, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def getDepartmentNetworkPopupDetails(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("departmentid", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        class_id = int(options.get("filterclass", 0))
        return get_entity_network(db, entityid, class_id)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def get_entity_compute(db, entityid, class_id):
    try:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % entityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})
        parent_entity = cache_utils.get_cache("db|tblEntities|id|%s" % req_entity["parententityid"], None, db_in=db)
        total = get_total_compute_resources(db, parent_entity, class_id, req_entity["parententityid"])
        allocated = get_allocated_compute_resources(db, parent_entity, class_id, req_entity["parententityid"])
        allocate = get_total_compute_resources(db, req_entity, class_id, entityid)
        if req_entity["entitytype"] == "organization":
            consumption = get_system_consumption(db, req_entity["parententityid"], compute_class_id=class_id,
                                                 storage_enabled=False, network_enabled=False)
        elif req_entity["entitytype"] == "department":
            consumption = get_organization_consumption(db, req_entity["parententityid"], compute_class_id=class_id,
                                                       storage_enabled=False, network_enabled=False)
        else:
            consumption = {}
        deployed = consumption["compute"]
        compute = [{"Catagory": "total", "CPU": total["cores"], "RAM": total["ram"], "Network": total["net"]},
                   {"Catagory": "allocated", "CPU": allocated["cores"], "RAM": allocated["ram"],
                    "Network": allocated["net"]},
                   {"Catagory": "remaining", "CPU": total["cores"] - allocated["cores"],
                    "RAM": total["ram"] - allocated["ram"], "Network": total["net"] - allocated["net"]},
                   {"Catagory": "deployed", "CPU": deployed["cores"], "RAM": deployed["ram"],
                    "Network": deployed["net"]},
                   {"Catagory": "blank_row", "CPU": "", "RAM": "", "Network": ""},
                   {"Catagory": "allocate", "CPU": allocate["cores"], "RAM": allocate["ram"],
                    "Network": allocate["net"]},
                   ]
        return ujson.dumps({"success": "True", "compute": compute})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def get_entity_storage(db, entityid, class_id):
    try:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % entityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})
        parent_entity = cache_utils.get_cache("db|tblEntities|id|%s" % req_entity["parententityid"], None, db_in=db)
        total = get_total_storage_resources(db, parent_entity, class_id, req_entity["parententityid"])
        allocated = get_allocated_storage_resources(db, parent_entity, class_id, req_entity["parententityid"])
        allocate = get_total_storage_resources(db, req_entity, class_id, entityid)
        if req_entity["entitytype"] == "organization":
            consumption = get_system_consumption(db, req_entity["parententityid"], storage_class_id=class_id,
                                                 compute_enabled=False, network_enabled=False)
        elif req_entity["entitytype"] == "department":
            consumption = get_organization_consumption(db, req_entity["parententityid"], storage_class_id=class_id,
                                                       compute_enabled=False, network_enabled=False)
        else:
            consumption = {}
        deployed = consumption["storage"]
        storage = [{"catagory": "total", "capacity": total["capacity"], "iops": total["iops"], "network": total["net"]},
                   {"catagory": "allocated", "capacity": allocated["capacity"], "iops": allocated["iops"],
                    "network": allocated["net"]},
                   {"catagory": "remaining", "capacity": total["capacity"] - allocated["capacity"],
                    "iops": total["iops"] - allocated["iops"], "network": total["net"] - allocated["net"]},
                   {"catagory": "deployed", "capacity": deployed["capacity"], "iops": deployed["iops"],
                    "network": deployed["net"]},
                   {"catagory": "blank_row", "capacity": "", "IOPS": "", "network": ""},
                   {"catagory": "allocate", "capacity": allocate["capacity"], "iops": allocate["iops"],
                    "network": allocate["net"]},
                   ]
        return ujson.dumps({"success": "True", "storage": storage})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def get_entity_network(db, entityid, class_id):
    try:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % entityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})
        parent_entity = cache_utils.get_cache("db|tblEntities|id|%s" % req_entity["parententityid"], None, db_in=db)
        total = get_total_network_resources(db, parent_entity, class_id, req_entity["parententityid"])
        allocated = get_allocated_network_resources(db, parent_entity, class_id, req_entity["parententityid"])
        allocate = get_total_network_resources(db, req_entity, class_id, entityid)

        if req_entity["entitytype"] == "organization":
            consumption = get_system_consumption(db, req_entity["parententityid"], network_class_id=class_id,
                                                 storage_enabled=False, compute_enabled=False)
        elif req_entity["entitytype"] == "department":
            consumption = get_organization_consumption(db, req_entity["parententityid"], network_class_id=class_id,
                                                       storage_enabled=False, compute_enabled=False)
        else:
            consumption = {}
        deployed = consumption["network"]

        f_total = {"catagory": "total"}
        f_allocated = {"catagory": "allocated"}
        f_allocate = {"catagory": "allocate"}
        f_deployed = {"catagory": "deployed"}
        f_remaining = {"catagory": "remaining"}
        f_blank_row = {"catagory": "blank_row"}
        for item in entity_constants.resource_network_services:
            key = item.lower()
            f_total[key] = total[item]["throughput"]
            f_allocated[key] = allocated[item]["throughput"]
            f_allocate[key] = allocate[item]["throughput"]
            f_deployed[key] = deployed[item]["throughput"]
            f_remaining[key] = total[item]["throughput"] - allocated[item]["throughput"]
            f_blank_row[key] = ""
        return ujson.dumps(
            {"success": "True", "network": [f_total, f_allocated, f_remaining, f_deployed, f_blank_row, f_allocate]})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def postCreateOrganizationComputePopup(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("organizationid", 0))
        if not entityid:
            entityid = int(options.get("entityid", 0))
        class_id = int(options.get("filterclass", 0))
        if "organizationcompute" not in options or entityid == 0:
            return ujson.dumps({"success": "False"})
        record = None
        for item in options["organizationcompute"]:
            if "Catagory" in item and item["Catagory"] == "allocate":
                record = item
                break
        if not record:
            return ujson.dumps({"success": "False"})
        allocate_compute_resources(db, entityid, class_id, cloud_utils.to_lower(record))
        return ujson.dumps({"success": "True"})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def postCreateDepartmentComputePopup(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("departmentid", 0))
        if not entityid:
            entityid = int(options.get("entityid", 0))
        class_id = int(options.get("filterclass", 0))
        if "departmentcompute" not in options or entityid == 0:
            return ujson.dumps({"success": "False"})
        record = None
        for item in options["departmentcompute"]:
            if "Catagory" in item and item["Catagory"] == "allocate":
                record = item
                break
        if not record:
            return ujson.dumps({"success": "False"})
        allocate_compute_resources(db, entityid, class_id, cloud_utils.to_lower(record))
        return ujson.dumps({"success": "True"})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def allocate_compute_resources(db, entityid, class_id, record):
    try:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % entityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})
        cloud_utils.update_or_insert(db, "tblResourcesCompute",
                                     {"tblentities": entityid, "catagory": "total",
                                      "parententityid": req_entity["parententityid"],
                                      "entitytype": req_entity["entitytype"],
                                      "computeclassesid": class_id,
                                      "cpu": record["cpu"], "ram": record["ram"], "network": record["network"]},
                                     {"tblentities": entityid, "catagory": "total", "computeclassesid": class_id})

    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def postCreateOrganizationStoragePopup(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("organizationid", 0))
        if not entityid:
            entityid = int(options.get("entityid", 0))
        class_id = int(options.get("filterclass", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        record = None
        for index in xrange(0, 3):
            if unicode(index) in options:
                if "catagory" in options[unicode(index)] and options[unicode(index)]["catagory"] == "allocate":
                    record = options[unicode(index)]
                    break
        if not record:
            return ujson.dumps({"success": "False"})
        allocate_storage_resources(db, entityid, class_id, cloud_utils.to_lower(record))
        return ujson.dumps({"success": "True"})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def postCreateDepartmentStoragePopup(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("departmentid", 0))
        if not entityid:
            entityid = int(options.get("entityid", 0))
        class_id = int(options.get("filterclass", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        record = None
        for index in xrange(0, 3):
            if unicode(index) in options:
                if "catagory" in options[unicode(index)] and options[unicode(index)]["catagory"] == "allocate":
                    record = options[unicode(index)]
                    break
        if not record:
            return ujson.dumps({"success": "False"})
        allocate_storage_resources(db, entityid, class_id, cloud_utils.to_lower(record))
        return ujson.dumps({"success": "True"})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def allocate_storage_resources(db, entityid, class_id, record):
    try:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % entityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})
        cloud_utils.update_or_insert(db, "tblResourcesStorage",
                                     {"tblentities": entityid, "catagory": "total",
                                      "parententityid": req_entity["parententityid"],
                                      "entitytype": req_entity["entitytype"],
                                      "storageclassesid": class_id,
                                      "capacity": record["capacity"], "iops": record["iops"],
                                      "network": record["network"]},
                                     {"tblentities": entityid, "catagory": "total", "storageclassesid": class_id})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def postCreateOrganizationNetworkPopup(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("organizationid", 0))
        if not entityid:
            entityid = int(options.get("entityid", 0))
        class_id = int(options.get("filterclass", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        record = None
        for index in xrange(0, 3):
            if unicode(index) in options:
                if "catagory" in options[unicode(index)] and options[unicode(index)]["catagory"] == "allocate":
                    record = options[unicode(index)]
                    break
        if not record:
            return ujson.dumps({"success": "False"})
        allocate_network_resources(db, entityid, class_id, cloud_utils.to_lower(record))
        return ujson.dumps({"success": "True"})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def postCreateDepartmentNetworkPopup(db, entity, dbid, function, options):
    try:
        entityid = int(options.get("departmentid", 0))
        if not entityid:
            entityid = int(options.get("entityid", 0))
        class_id = int(options.get("filterclass", 0))
        if entityid == 0:
            return ujson.dumps({"success": "False"})
        record = None
        for index in xrange(0, 3):
            if unicode(index) in options:
                if "catagory" in options[unicode(index)] and options[unicode(index)]["catagory"] == "allocate":
                    record = options[unicode(index)]
                    break
        if not record:
            return ujson.dumps({"success": "False"})
        allocate_network_resources(db, entityid, class_id, cloud_utils.to_lower(record))
        return ujson.dumps({"success": "True"})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def allocate_network_resources(db, entityid, class_id, record):
    try:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % entityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})
        for item in entity_constants.resource_network_services:
            key = item.lower()
            if key in record:
                cloud_utils.update_or_insert(db, "tblResourcesNetwork",
                                             {"tblentities": entityid, "catagory": "total",
                                              "parententityid": req_entity["parententityid"],
                                              "entitytype": req_entity["entitytype"],
                                              "networkclassesid": class_id,
                                              "type": key, "throughput": record[key]},
                                             {"tblentities": entityid, "catagory": "total", "type": key,
                                              "networkclassesid": class_id})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def getVirtualResources(db, entity, dbid, function, options):
    try:
        parententityid = int(options.get("entityid", 0))
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % parententityid, None, db_in=db)
        if not req_entity:
            return ujson.dumps({"success": "False"})

        requested_resources = int(options.get("resourcetype", 0))
        if requested_resources == 1:
            compute_enabled = True
            storage_enabled = False
            network_enabled = False
        elif requested_resources == 2:
            compute_enabled = False
            storage_enabled = False
            network_enabled = True
        elif requested_resources == 3:
            compute_enabled = False
            storage_enabled = True
            network_enabled = False
        else:
            compute_enabled = True
            storage_enabled = True
            network_enabled = True

        compute_class_id = int(options.get("computeid", 0))
        network_class_id = int(options.get("networkid", 0))
        storage_class_id = int(options.get("storageid", 0))

        slice_id = 0

        virtual = []
        if req_entity["entitytype"] == "system":
            consumption = get_system_consumption(db, parententityid,
                                                 compute_class_id=compute_class_id, storage_class_id=storage_class_id,
                                                 network_class_id=network_class_id,
                                                 compute_enabled=compute_enabled, storage_enabled=storage_enabled,
                                                 network_enabled=network_enabled)
        elif req_entity["entitytype"] == "organization":
            consumption = get_organization_consumption(db, parententityid,
                                                       compute_class_id=compute_class_id,
                                                       storage_class_id=storage_class_id,
                                                       network_class_id=network_class_id,
                                                       compute_enabled=compute_enabled, storage_enabled=storage_enabled,
                                                       network_enabled=network_enabled)
        elif req_entity["entitytype"] == "department":
            consumption = get_department_consumption(db, parententityid,
                                                     compute_class_id=compute_class_id,
                                                     storage_class_id=storage_class_id,
                                                     network_class_id=network_class_id,
                                                     compute_enabled=compute_enabled, storage_enabled=storage_enabled,
                                                     network_enabled=network_enabled)
        elif req_entity["entitytype"] == "slice":
            slice_id = req_entity["id"]
            consumption = get_vdc_consumption(db, parententityid,
                                              compute_class_id=compute_class_id, storage_class_id=storage_class_id,
                                              network_class_id=network_class_id, slice_id=parententityid,
                                              compute_enabled=compute_enabled, storage_enabled=storage_enabled,
                                              network_enabled=network_enabled)
        else:
            consumption = {"compute": {}, "network": {}, "storage": {}}

        if compute_enabled:
            virtual.extend(
                get_compute_resources(db, req_entity, compute_class_id, parententityid, consumption, slice_id=slice_id))
        if network_enabled:
            virtual.extend(
                get_network_resources(db, req_entity, network_class_id, parententityid, consumption, slice_id=slice_id))
        if storage_enabled:
            virtual.extend(
                get_storage_resources(db, req_entity, storage_class_id, parententityid, consumption, slice_id=slice_id))

        return ujson.dumps({"success": "True", "virtual_resource": virtual})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"success": "False"})


def get_compute_resources(db, req_entity, class_id, parententityid, consumption, slice_id=0):
    compute = {}
    try:
        total = get_total_compute_resources(db, req_entity, class_id, parententityid, slice_id=slice_id)
        allocated = get_allocated_compute_resources(db, req_entity, class_id, parententityid, slice_id=slice_id)
        compute = [{"PoolType": "Compute", "resource": "CPU", "total": total["cores"], "allocated": allocated["cores"],
                    "deployed": consumption["compute"].get("cores", 0),
                    "remaining": total["cores"] - allocated["cores"]},
                   {"PoolType": "Compute", "resource": "RAM", "total": total["ram"], "allocated": allocated["ram"],
                    "deployed": consumption["compute"].get("ram", 0), "remaining": total["ram"] - allocated["ram"]},
                   {"PoolType": "Compute", "resource": "Network", "total": total["net"], "allocated": allocated["net"],
                    "deployed": consumption["compute"].get("net", 0), "remaining": total["net"] - allocated["net"]}]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return compute


def get_total_compute_resources(db, req_entity, class_id, entityid, slice_id=0):
    cores = 0
    mhz = 0
    ram = 0
    net = 0
    try:
        if req_entity["entitytype"] == "system" or req_entity["entitytype"] == "slice":
            compute_class_specs = {}
            if class_id:
                class_row = entity.entity_utils.read_full_entity(db, class_id)
                if class_row and "extra_specs" in class_row:
                    try:
                        compute_class_specs = ujson.loads(class_row["extra_specs"])
                    except:
                        pass

            for dev in get_next_device(db, compute_class_specs, "compute_class", class_id=class_id, slice_id=slice_id):
                cores += dev["vcpu"]
                mhz += dev["mhz"]
                ram += dev["memory"]
                net += dev["totalbandwidth"]
        else:
            current_index = 0
            while True:
                row = db.get_row("tblResourcesCompute",
                                 "catagory = 'total' AND tblentities = %s AND id > %s" % (entityid, current_index),
                                 order="ORDER BY id LIMIT 1")
                if not row:
                    break
                current_index = row['id']
                if class_id == 0 or class_id == row["ComputeClassesId"]:
                    cores += row["CPU"]
                    ram += row["RAM"]
                    net += row["Network"]
    except:
        cloud_utils.log_exception(sys.exc_info())

    return {"cores": cores, "ram": ram, "net": net}


def get_allocated_compute_resources(db, req_entity, class_id, entityid, slice_id=0):
    cores = 0
    mhz = 0
    ram = 0
    net = 0
    try:
        current_index = 0
        while True:
            row = db.get_row("tblResourcesCompute", "entitytype != 'slice' and "
                                                    "catagory = 'total' AND parententityid = %s "
                                                    "AND id > '%s'" % (entityid, current_index),
                             order="ORDER BY id LIMIT 1")
            if not row:
                break
            current_index = row['id']
            if class_id == 0 or class_id == row["ComputeClassesId"]:
                cores += row["CPU"]
                ram += row["RAM"]
                net += row["Network"]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return {"cores": cores, "ram": ram, "net": net}


def get_system_consumption(db, dbid, compute_enabled=True, storage_enabled=True, network_enabled=True,
                           compute_class_id=0, storage_class_id=0, network_class_id=0):
    compute = {}
    storage = {}
    network = {}
    consumption = {"compute": compute, "storage": storage, "network": network}
    try:
        current_index = 0
        while True:
            row = db.get_row("tblEntities",
                             "deleted=0 and entitytype = 'organization' AND parententityid = %s AND id > '%s'" % (
                                 dbid, current_index),
                             order="ORDER BY id LIMIT 1")
            if not row:
                break
            current_index = row['id']
            child_consumption = get_organization_consumption(db, row["id"], compute_enabled=compute_enabled,
                                                             storage_enabled=storage_enabled,
                                                             network_enabled=network_enabled,
                                                             compute_class_id=compute_class_id,
                                                             storage_class_id=storage_class_id,
                                                             network_class_id=network_class_id)

            update_consumption(consumption, child_consumption)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return consumption


def get_organization_consumption(db, dbid, compute_enabled=True, storage_enabled=True, network_enabled=True,
                                 compute_class_id=0, storage_class_id=0, network_class_id=0):
    compute = {}
    storage = {}
    network = {}
    consumption = {"compute": compute, "storage": storage, "network": network}
    try:
        current_index = 0
        while True:
            row = db.get_row("tblEntities",
                             "deleted=0 and entitytype = 'department' AND parententityid = %s AND id > '%s'" % (
                                 dbid, current_index),
                             order="ORDER BY id LIMIT 1")
            if not row:
                break
            current_index = row['id']
            child_consumption = get_department_consumption(db, row["id"], compute_enabled=compute_enabled,
                                                           storage_enabled=storage_enabled,
                                                           network_enabled=network_enabled,
                                                           compute_class_id=compute_class_id,
                                                           storage_class_id=storage_class_id,
                                                           network_class_id=network_class_id)

            update_consumption(consumption, child_consumption)

    except:
        cloud_utils.log_exception(sys.exc_info())
    return consumption


def get_department_consumption(db, dbid, compute_enabled=True, storage_enabled=True, network_enabled=True,
                               compute_class_id=0, storage_class_id=0, network_class_id=0):
    compute = {}
    storage = {}
    network = {}
    consumption = {"compute": compute, "storage": storage, "network": network}
    try:
        current_index = 0
        while True:
            row = db.get_row("tblEntities", "deleted=0 and entitytype = 'vdc' AND parententityid = %s AND id > '%s'" % (
                dbid, current_index),
                             order="ORDER BY id LIMIT 1")
            if not row:
                break
            current_index = row['id']
            child_consumption = get_vdc_consumption(db, row["id"], compute_enabled=compute_enabled,
                                                    storage_enabled=storage_enabled, network_enabled=network_enabled,
                                                    compute_class_id=compute_class_id,
                                                    storage_class_id=storage_class_id,
                                                    network_class_id=network_class_id)

            update_consumption(consumption, child_consumption)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return consumption


def update_consumption(master, child):  # add to masters records from child records.
    for key in child:
        if key in master:
            if isinstance(child[key], dict):
                update_consumption(master[key], child[key])
            else:
                master[key] += child[key]
        else:
            master[key] = child[key]


def get_vdc_consumption(db, dbid, compute_enabled=True,
                        storage_enabled=True, network_enabled=True,
                        compute_class_id=0, storage_class_id=0, network_class_id=0, slice_id=0):
    consumption = {"compute": {}, "storage": {}, "network": {}}
    try:
        if slice_id:
            check_for = "sliceid = %s" % slice_id
        else:
            check_for = "tblentities = %s" % dbid
        if compute_enabled:
            cores = 0
            ram = 0
            net = 0
            current_index = 0
            while True:
                row = db.get_row("tblResourcesCompute",
                                 "catagory = 'deployed' AND %s AND id > '%s'" % (check_for, current_index),
                                 order="ORDER BY id LIMIT 1")
                if not row:
                    break
                current_index = row['id']
                if compute_class_id == 0 or compute_class_id == row["ComputeClassesId"]:
                    cores += row["CPU"]
                    ram += row["RAM"]
                    net += row["Network"]
            consumption["compute"] = {"cores": cores, "ram": ram, "net": net}

        if storage_enabled:
            capacity = 0
            iops = 0
            net = 0
            current_index = 0
            while True:
                row = db.get_row("tblResourcesStorage",
                                 "catagory = 'deployed' AND %s AND id > '%s'" % (check_for, current_index),
                                 order="ORDER BY id LIMIT 1")
                if not row:
                    break
                current_index = row['id']
                if storage_class_id == 0 or storage_class_id == row["StorageClassesId"]:
                    capacity += row["Capacity"]
                    iops += row["IOPS"]
                    net += row["Network"]
            consumption["storage"] = {"capacity": capacity, "iops": iops, "net": net}

        if network_enabled:
            network = {}
            for item in entity_constants.resource_network_services:
                network[item] = {}
                network[item]["throughput"] = 0

                current_index = 0
                while True:
                    row = db.get_row("tblResourcesNetwork",
                                     "catagory = 'deployed' AND type = '%s' and %s AND id > '%s'" % (
                                         item, check_for, current_index),
                                     order="ORDER BY id LIMIT 1")
                    if not row:
                        break
                    current_index = row['id']
                    if network_class_id == 0 or network_class_id == row["NetworkClassesId"]:
                        network[item]["throughput"] += row["Throughput"]
            consumption["network"] = network

    except:
        cloud_utils.log_exception(sys.exc_info())
    return consumption


def get_storage_resources(db, req_entity, class_id, parententityid, consumption, slice_id=0):
    storage = {}
    try:
        total = get_total_storage_resources(db, req_entity, class_id, parententityid, slice_id=slice_id)
        allocated = get_allocated_storage_resources(db, req_entity, class_id, parententityid, slice_id=slice_id)
        storage = [
            {"PoolType": "Storage", "resource": "Capacity", "total": total["capacity"],
             "allocated": allocated["capacity"],
             "deployed": consumption["storage"].get("capacity", 0),
             "remaining": total["capacity"] - allocated["capacity"]},
            {"PoolType": "Storage", "resource": "IOPS", "total": total["iops"], "allocated": allocated["iops"],
             "deployed": consumption["storage"].get("cores", 0), "remaining": total["iops"] - allocated["iops"]},
            {"PoolType": "Storage", "resource": "Network", "total": total["net"], "allocated": allocated["net"],
             "deployed": consumption["storage"].get("net", 0), "remaining": total["net"] - allocated["net"]}]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return storage


def get_total_storage_resources(db, req_entity, class_id, entityid, slice_id=0):
    capacity = 0
    iops = 0
    net = 0
    try:
        if req_entity["entitytype"] == "system" or req_entity["entitytype"] == "slice":
            storage_class_specs = {}
            if class_id:
                class_row = entity.entity_utils.read_full_entity(db, class_id)
                if class_row and "extra_specs" in class_row:
                    try:
                        storage_class_specs = ujson.loads(class_row["extra_specs"])
                    except:
                        pass
            for dev in get_next_device(db, storage_class_specs, "storage_class", class_id=class_id, slice_id=slice_id):
                capacity += dev["totalstorage"]
                iops += dev["totaliops"]
                net += dev["totalbandwidth"]
        else:
            current_index = 0
            while True:
                row = db.get_row("tblResourcesStorage",
                                 "catagory = 'total' AND tblentities = %s AND id > '%s'" % (entityid, current_index),
                                 order="ORDER BY id LIMIT 1")
                if not row:
                    break
                current_index = row['id']
                if class_id == 0 or class_id == row["StorageClassesId"]:
                    capacity += row["Capacity"]
                    iops += row["IOPS"]
                    net += row["Network"]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return {"capacity": capacity, "iops": iops, "net": net}


def get_allocated_storage_resources(db, req_entity, class_id, entityid, slice_id=0):
    capacity = 0
    iops = 0
    net = 0
    try:
        current_index = 0
        while True:
            row = db.get_row("tblResourcesStorage", "entitytype != 'slice' "
                                                    "and catagory = 'total' AND "
                                                    "parententityid = %s AND id > '%s'" % (entityid, current_index),
                             order="ORDER BY id LIMIT 1")
            if not row:
                break
            current_index = row['id']
            if class_id == 0 or class_id == row["StorageClassesId"]:
                capacity += row["Capacity"]
                iops += row["IOPS"]
                net += row["Network"]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return {"capacity": capacity, "iops": iops, "net": net}


def get_network_resources(db, req_entity, class_id, parententityid, consumption, slice_id=0):
    response = []
    try:
        total = get_total_network_resources(db, req_entity, class_id, parententityid, slice_id=slice_id)
        allocated = get_allocated_network_resources(db, req_entity, class_id, parententityid, slice_id=slice_id)
        for item in entity_constants.resource_network_services:
            response.append({"PoolType": "Network", "resource": item, "total": total[item]["throughput"],
                             "allocated": allocated[item]["throughput"],
                             "deployed": consumption["network"].get(item, {}).get("throughput", 0),
                             "remaining": total[item]["throughput"] - allocated[item]["throughput"]})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return response


def get_total_network_resources(db, req_entity, class_id, entityid, slice_id=0):
    network = {}
    for item in entity_constants.resource_network_services:
        network[item] = {}
        network[item]["throughput"] = 0
    try:
        if req_entity["entitytype"] == "system" or req_entity["entitytype"] == "slice":
            network_class_specs = {}
            if class_id:
                class_row = entity.entity_utils.read_full_entity(db, class_id)
                if class_row and "extra_specs" in class_row:
                    try:
                        network_class_specs = ujson.loads(class_row["extra_specs"])
                    except:
                        pass
            for dev in get_next_device(db, network_class_specs, "network_class", class_id=class_id, slice_id=slice_id):
                if dev["entitytype"] in entity_constants.physical_entitytype_2_network_services:
                    network[entity_constants.physical_entitytype_2_network_services[dev["entitytype"]]]["throughput"] += \
                        dev["licensedthroughput"]
        else:
            for item in entity_constants.resource_network_services:
                current_index = 0
                while True:
                    row = db.get_row("tblResourcesNetwork",
                                     "catagory = 'total' AND type ='%s' and tblentities = %s AND id > '%s'" % (
                                         item, entityid, current_index),
                                     order="ORDER BY id LIMIT 1")
                    if not row:
                        break
                    current_index = row['id']
                    if class_id == 0 or class_id == row["NetworkClassesId"]:
                        network[item]["throughput"] += row["Throughput"]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return network


def get_allocated_network_resources(db, req_entity, class_id, entityid, slice_id=0):
    network = {}
    for item in entity_constants.resource_network_services:
        network[item] = {}
        network[item]["throughput"] = 0
    try:
        for item in entity_constants.resource_network_services:
            current_index = 0
            while True:
                row = db.get_row("tblResourcesNetwork", "entitytype != 'slice' and "
                                                        "catagory = 'total' AND type ='%s' and "
                                                        "parententityid = %s AND id > '%s'" % (
                                     item, entityid, current_index),
                                 order="ORDER BY id LIMIT 1")
                if not row:
                    break
                current_index = row['id']
                if class_id == 0 or class_id == row["NetworkClassesId"]:
                    network[item]["throughput"] += row["Throughput"]
    except:
        cloud_utils.log_exception(sys.exc_info())
    return network
