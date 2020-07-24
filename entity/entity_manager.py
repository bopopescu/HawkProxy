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

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

from utils.underscore import _

import validate_entity
import provision_entity

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
import utils.cache_utils as cache_utils
import entity_utils
import rpcResync as entity_resync

import cfd_keystone.cfd_keystone

import entity_constants


class Entity(object):
    def __init__(self, child_table,
                 post_db_create_function,
                 pre_db_delete_function,
                 post_rest_get_function,
                 parent_uri_type,
                 rest_header,
                 rest_json_keys,
                 rest_build_function,
                 pre_db_create_function=None,
                 validate_entity_function=None,
                 provision_entity_function=None,
                 post_db_delete_function=None,
                 pre_rest_status_check_function=None,
                 post_entity_final_status_function=None,
                 entity_pending_states=entity_constants.default_entity_pending_states,
                 entity_completed_states=entity_constants.default_entity_completed_states,
                 entity_failed_states=entity_constants.default_entity_failed_states,
                 periodic_status_check_time=entity_constants.default_periodic_status_check_time,
                 periodic_max_status_check_iterations=entity_constants.default_periodic_max_status_check_iterations,

                 default_entity_name_prefix=None,
                 statistics_manager=None
                 ):
        self.child_table = child_table

        # called after a row in tblentities and child table is created
        if post_db_create_function:
            self.post_db_create_function = post_db_create_function
        else:
            # assign a null function if nothing to call...
            self.post_db_create_function = lambda *args, **kwargs: None

        if pre_db_create_function:
            self.pre_db_create_function = pre_db_create_function
        else:
            self.pre_db_create_function = lambda *args, **kwargs: None

        # called after each get, post, or put response
        if post_rest_get_function:
            self.post_rest_get_function = post_rest_get_function
        else:
            # assign a null function if nothing to call...
            self.post_rest_get_function = lambda *args, **kwargs: None

        self.parent_uri_type = parent_uri_type

        self.rest_header = rest_header

        if post_db_delete_function:
            self.post_db_delete_function = post_db_delete_function
        else:
            self.post_db_delete_function = lambda *args, **kwargs: None

        # function to be called before REST API
        self.pre_rest_status_check_function = pre_rest_status_check_function
        # function to be called after the entity is in its "final" status
        self.post_entity_final_status_function = post_entity_final_status_function

        self.rest_json_keys = rest_json_keys
        if rest_build_function:
            self.rest_build_function = rest_build_function
        else:
            self.rest_build_function = None

        if validate_entity_function:
            self.validate_entity_function = validate_entity_function
        else:
            self.validate_entity_function = lambda *args, **kwargs: None

        if pre_db_delete_function:
            self.pre_db_delete_function = pre_db_delete_function
        else:
            self.pre_db_delete_function = lambda *args, **kwargs: None

        if provision_entity_function:
            self.provision_entity_function = provision_entity_function
        else:
            self.provision_entity_function = None

        self.entity_pending_states = entity_pending_states
        self.entity_completed_states = entity_completed_states
        self.entity_failed_states = entity_failed_states
        self.periodic_status_check_time = periodic_status_check_time
        self.periodic_max_status_check_iterations = periodic_max_status_check_iterations
        if default_entity_name_prefix:
            self.default_entity_name_prefix = default_entity_name_prefix
        else:
            self.default_entity_name_prefix = "entity-"

        self.statistics_manager = statistics_manager


def entity_rest_api_enabled(db, dbid, row, parent_row=None):
    if "entitytype" not in row:
        return None
    entitytype = row["entitytype"]

    '''if entitytype in skip_dept_org_group_child:
        parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": row["parententityid"]}, order="ORDER BY id LIMIT 1"))
        if parent_row:
            if parent_row["entitytype"] == "department" or parent_row["entitytype"] == "organization":
                return
    elif entitytype in skip_dept_org__child_group:
        parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": row["parententityid"]}, order="ORDER BY id LIMIT 1"))
        if parent_row:
            grandparent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": parent_row["parententityid"]}, order="ORDER BY id LIMIT 1"))
            if grandparent_row:
                if grandparent_row["entitytype"] == "department" or parent_row["entitytype"] == "organization":
                    return
    '''
    if not entities[entitytype].pre_rest_status_check_function or \
            entities[entitytype].pre_rest_status_check_function(db, dbid, row):
        return True
    return None


# build entity json string
def get_entity_json(db, dbid, row, options=None, quick_provision=False):
    if "entitytype" not in row:
        return None, "Invalid database row dictionary"
    entitytype = row["entitytype"]
    try:
        if entitytype not in entities.keys():
            return None, "Unknown entity type %s" % entitytype
        if quick_provision or entity_rest_api_enabled(db, dbid, row):
            if not entities[entitytype].rest_build_function:
                return None, None
            return entities[entitytype].rest_build_function(db, dbid, row, entities[entitytype].rest_json_keys,
                                                            options=options)
        else:
            return None, None
    except:
        cloud_utils.log_exception(sys.exc_info())

    return None, "Error in processing %s " % entitytype


def entitytype_rest(s):
    if s in entities.keys():
        return entities[s].rest_header
    LOG.critical(_("Key %s not found  in entites: %s" % (s, str(entities.keys()))))
    return "Error"


def _copy_kv(row, keys):
    j = {}
    if keys:
        for i in keys:
            if i in row.keys():
                if isinstance(row[i], (int, long)) or row[i]:
                    j[i] = row[i]
    # else:
    #            LOG.warn(_("Key %s not found  in row %s  from keys %s" % (i, row, keys)))
    return j


def str_list(s):
    if s:
        if isinstance(s, basestring):
            return s.split(",")
        else:
            LOG.warn(_("Input %s is not a string" % s))
    return []


def date_str(s):
    if s:
        return str(s)
    return ""


import base64


def save_ssh_keys(db, dbid, options):
    if "ssh_keys" in options and isinstance(options["ssh_keys"], list):
        for key in options["ssh_keys"]:
            if "name" in key and "public_key" in key:
                cloud_utils.insert_db(db, "tblSSHPublicKeys", {"tblEntities": dbid, "name": key["name"],
                                                               "public_key": base64.b64encode(key["public_key"])})
            else:
                LOG.critical(_("Skipping SSH key: %s for dbid %s" % (key, dbid)))


def save_user_data(db, dbid, options):
    cloud_utils.update_or_insert(db, "tblUserData", {"tblEntities": dbid, "user_data": options["user_data"]},
                                 {"tblentities": dbid})


def save_entity_policy(db, dbid, options):
    cloud_utils.update_or_insert(db, "tblEntityPolicies", {"tblEntities": dbid, "policy": options["policy"]},
                                 {"tblentities": dbid})


def save_entity_classes(db, dbid, row, options):
    if "classes" in options and isinstance(options["classes"], list):
        if len(options["classes"]) == 0:
            db.execute_db("DELETE FROM tblAttachedEntities WHERE (AttachedEntityId = %s AND EntityType='%s') " %
                          (dbid, entity_constants.entitytype_class[row["entitytype"]]))
        else:
            db.execute_db(
                "UPDATE tblAttachedEntities SET internal_updated_flag=0 WHERE (AttachedEntityId = %s AND EntityType='%s') " %
                (dbid, entity_constants.entitytype_class[row["entitytype"]]))
            for device in options["classes"]:
                if "id" in device:
                    search_dict = {"tblEntities": device["id"], "AttachedEntityId": dbid,
                                   "attachedentityname": row["name"],
                                   "AttachedEntityUniqueId": row["uniqueid"], "AttachedEntityType": row["entitytype"],
                                   "entitytype": entity_constants.entitytype_class[row["entitytype"]]}
                    ndbid = cloud_utils.update_or_insert(db, "tblAttachedEntities", search_dict, search_dict)
                    db.execute_db("UPDATE tblAttachedEntities SET internal_updated_flag=1 WHERE id=%s " % ndbid)

            db.execute_db(
                "DELETE FROM tblAttachedEntities WHERE (AttachedEntityId = %s AND EntityType='%s' AND  internal_updated_flag=0) " %
                (dbid, entity_constants.entitytype_class[row["entitytype"]]))


def save_entity_flavors(db, dbid, options):
    if "flavors" in options and isinstance(options["flavors"], list):
        #        db.delete_rows_dict("tblFlavors", {"tblentities": dbid})
        for flavor in options["flavors"]:
            if "type" in flavor:
                if flavor["type"] == "create":
                    flavor["tblEntities"] = dbid
                    cloud_utils.insert_db(db, "tblFlavors", flavor)
                    continue
                elif flavor["type"] == "delete" and "dbid" in flavor:
                    db.delete_rows_dict("tblFlavors", {"tblentities": dbid, "id": flavor["dbid"]})
                    continue
                elif flavor["type"] == "update" and "dbid" in flavor:
                    cloud_utils.update_only(db, "tblFlavors", flavor, {"tblentities": dbid, "id": flavor["dbid"]})
                    continue
            LOG.critical(_("Skipping flavor: %s for dbid %s" % (flavor, dbid)))


entity_keys = ["name", "description", "email", "administrator", "location"]


def _entity(db, dbid, row, keys, **kwargs):
    j = _copy_kv(row, keys)
    if "sortsequenceid" in row and row["sortsequenceid"] != 0:
        j.update({"sequence_number": row["sortsequenceid"]})
    return j


def _get_domain_row(db, dbid):
    parent, error = entity_utils.read_full_entity_status_tuple(db, dbid)
    if error:
        return None
    if parent["entitytype"] == "system":
        pass
    elif parent["entitytype"] == "organization":
        pass
    elif parent["entitytype"] == "department":
        parent, error = entity_utils.read_full_entity_status_tuple(db, parent["parententityid"])
    elif parent["entitytype"] == "vdc":
        parent, error = entity_utils.read_full_entity_status_tuple(db, parent["parententityid"])
        parent, error = entity_utils.read_full_entity_status_tuple(db, parent["parententityid"])
    else:
        return None
    return parent


def _add_acl_roles(db, dbid, options, mode=None):
    try:
        if "aclrole" in options and "acl_dbids" in options and isinstance(options["acl_dbids"], list):
            # delete old entries
            db.delete_rows_dict("tblEntitiesACL", {"tblentities": dbid})
            for id in options["acl_dbids"]:
                if not id:
                    id = 0
                db.execute_db(
                    "INSERT INTO tblEntitiesACL (tblEntities, AclRole, AclEntityId, ContainerEntityId) VALUES ('%s', '%s', '%s','%s')" %
                    (dbid, options["aclrole"], id, options.get("containerentityid", 0)))
    except:
        cloud_utils.log_exception(sys.exc_info())


def _add_developer_resources(db, dbid, options, mode=None):
    try:
        if "aclrole" in options and options["aclrole"].lower() == "developer":
            resources = {"tblentities": dbid,
                         "entitytype": "user",
                         "parententityid": options["parententityid"],
                         "catagory": "allocated",
                         "typetitle": "Compute",
                         "type": "Default",
                         "ram": options.get("ram", 0),
                         "network": options.get("network", 0),
                         "cpu": options.get("cpu", 0),
                         }
            cloud_utils.update_or_insert(db, "tblResourcesCompute", resources,
                                         {"tblentities": dbid, "catagory": "allocated"})

            resources = {"tblentities": dbid,
                         "entitytype": "user",
                         "parententityid": options["parententityid"],
                         "catagory": "deployed",
                         "typetitle": "Compute",
                         "type": "Default",
                         # "ram":0,
                         # "network":0,
                         # "cpu":0,
                         }
            cloud_utils.update_or_insert(db, "tblResourcesCompute", resources,
                                         {"tblentities": dbid, "catagory": "deployed"})

            resources = {"tblentities": dbid,
                         "entitytype": "user",
                         "parententityid": options["parententityid"],
                         "catagory": "allocated",
                         "typetitle": "Latency",
                         "capacity": options.get("capacity", 0),
                         "type": options.get("type", "gold")
                         }
            cloud_utils.update_or_insert(db, "tblResourcesStorage", resources,
                                         {"tblentities": dbid, "catagory": "allocated"})

            resources = {"tblentities": dbid,
                         "entitytype": "user",
                         "parententityid": options["parententityid"],
                         "catagory": "deployed",
                         "typetitle": "Latency",
                         # "capacity":0,
                         "type": options.get("type", "gold")
                         }
            cloud_utils.update_or_insert(db, "tblResourcesStorage", resources,
                                         {"tblentities": dbid, "catagory": "deployed"})

            if "flavors" in options:
                for flavor in options["flavors"]:
                    resources = {"tblentities": dbid,
                                 "entitytype": "user",
                                 "parententityid": options["parententityid"],
                                 "catagory": "allocated",
                                 "quantity": flavor.get("quantity", 0),
                                 "tblflavors": flavor.get("tblflavors", 0),
                                 }
                    cloud_utils.update_or_insert(db, "tblResourcesFlavors", resources,
                                                 {"tblentities": dbid, "tblflavors": flavor.get("tblflavors", 0),
                                                  "catagory": "allocated"})
                    resources = {"tblentities": dbid,
                                 "entitytype": "user",
                                 "parententityid": options["parententityid"],
                                 "catagory": "deployed",
                                 #        "quantity":flavor.get("quantity",0),
                                 "tblflavors": flavor.get("tblflavors", 0)
                                 }
                    cloud_utils.update_or_insert(db, "tblResourcesFlavors", resources,
                                                 {"tblentities": dbid, "tblflavors": flavor.get("tblflavors", 0),
                                                  "catagory": "deployed"})

    except:
        cloud_utils.log_exception(sys.exc_info())


def _group_post_db_create(db, dbid, options, mode=None, **kwargs):
    _add_acl_roles(db, dbid, options, mode=mode)

    domain = _get_domain_row(db, options["parententityid"])
    if not domain:
        return None
    cfd_keystone.cfd_keystone.get_create_group(db, cfd_keystone.cfd_keystone.system_token,
                                               {"name": domain["name"], "description": domain["description"]},
                                               {"name": options["name"], "description": options.get("description", "")})


def _group_pre_delete(db, dbid, options):
    domain = _get_domain_row(db, options["parententityid"])
    if not domain:
        return None
    cfd_keystone.cfd_keystone.delete_group(db, cfd_keystone.cfd_keystone.system_token,
                                           {"name": domain["name"], "description": domain["description"]},
                                           {"name": options["name"], "description": options.get("description", "")})


def _user_pre_db_create(db, options, mode=None, parent_row=None):
    return entity_utils.confirm_options_keys(options, ["loginid", "password"])


def _user_post_db_create(db, dbid, options, mode=None, **kwargs):
    try:
        if not mode:
            return
        if "parententityid" not in options:
            return
        _add_acl_roles(db, dbid, options, mode=mode)
        _add_developer_resources(db, dbid, options, mode=mode)
        group, error = entity_utils.read_full_entity_status_tuple(db, options["parententityid"])
        domain = _get_domain_row(db, group["parententityid"])
        if not domain or not group:
            return None
        if mode == "create":
            cfd_keystone.cfd_keystone.get_create_user(db, cfd_keystone.cfd_keystone.system_token,
                                                      {"name": domain["name"], "description": domain["description"]},
                                                      {"name": group["name"], "description": group["description"]},
                                                      {"name": options["loginid"],
                                                       "description": options.get("description", ""),
                                                       "enabled": options.get("enabled", True),
                                                       "email": options.get("email", ""),
                                                       "password": options["password"]})
            return
        if mode == "update":
            if "user_row" in options:
                #            options["loginid"] = options["user_row"]["loginid"]
                if options["user_row"]["entitydisabled"] == 1:
                    options["enabled"] = False
                else:
                    options["enabled"] = True
            if "password" in options:
                cfd_keystone.cfd_keystone.update_user(db, cfd_keystone.cfd_keystone.system_token,
                                                      {"name": domain["name"], "description": domain["description"]},
                                                      {"name": group["name"], "description": group["description"]},
                                                      {"name": options["loginid"],
                                                       "description": options.get("description", ""),
                                                       "enabled": options.get("enabled", True),
                                                       "email": options.get("email", ""),
                                                       "password": options["password"]})
    except:
        cloud_utils.log_exception(sys.exc_info())


def _user_pre_delete(db, dbid, options):
    group, error = entity_utils.read_full_entity_status_tuple(db, options["parententityid"])
    db.delete_rows_dict("tblResourcesCompute", {"tblentities": dbid})
    db.delete_rows_dict("tblResourcesStorage", {"tblentities": dbid})
    db.delete_rows_dict("tblEntitiesACL", {"tblentities": dbid})

    domain = _get_domain_row(db, group["parententityid"])
    if not domain or not group:
        return None

    cfd_keystone.cfd_keystone.delete_user(db, cfd_keystone.cfd_keystone.system_token,
                                          {"name": domain["name"], "description": domain["description"]},
                                          {"name": group["name"], "description": group["description"]},
                                          {"name": options["loginid"], "description": options.get("description", "")})


def _rest_disabled(db, dbid, row):
    return False


def delete_interface_ports(db, dbid, index):
    try:
        interface = db.get_row_dict("tblServicesInterfaces", {"tblEntities": dbid}, order="ORDER BY id LIMIT 1")
        if interface:
            db.execute_db("DELETE FROM tblAttachedEntities WHERE tblEntities = '%s' " % interface["BeginServicePortId"])
            db.execute_db("DELETE FROM tblAttachedEntities WHERE tblEntities = '%s' " % interface["EndServicePortId"])

        count = db.execute_db("UPDATE tblEntities JOIN tblServicePorts SET tblEntities.deleted=1, "
                              "tblEntities.deleted_at= now()  "
                              " WHERE  (tblEntities.EntityType = 'service_port' AND tblEntities.deleted=0 AND "
                              " tblServicePorts.tblEntities = tblEntities.id AND "
                              " tblServicePorts.ServiceInterfaceEntityId='%s' AND "
                              " tblServicePorts.InterfacePortIndex ='%s') "
                              % (dbid, index))
    except:
        cloud_utils.log_exception(sys.exc_info())


def _storage_class_post_db_delete(db, dbid, row):
    db.execute_db(
        "UPDATE tblContainers SET tblStorageClassesId=0, Security='None', Iops=0 WHERE tblStorageClassesId = '%s' " % dbid)


def _compute_class_post_db_delete(db, dbid, row):
    db.execute_db("UPDATE tblServerFarms SET tblComputeClassesId=0 WHERE tblcomputeClassesId = '%s' " % dbid)


def create_class_json(db, dbid, row):
    result, status = _class(db, dbid, row, _class_keys)
    return result


def get_iops_source(source):
    if source.lower() == "fixed":
        return "class"
    return "containers"


_class_keys = ["extra_specs", "metadata"]


def _class(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    j.update({"type": row["entitytype"]})
    if row["entitytype"] == "storage_class":
        j.update({"storage_type": row["storagetype"], "storage_security": row["security"],
                  "storage_data_reduction": row["datareduction"], "storage_latency": row["latency"],
                  "storage_iops_source": get_iops_source(row["iops_selection"]),
                  "iops": row["minimumiops"], "maximum_iops": row["maximumiops"], "burst_iops": row["burstiops"]
                  })
        attached_entitytype = "slice_storage_entity"
    elif row["entitytype"] == "compute_class":
        attached_entitytype = "slice_compute_entity"
    elif row["entitytype"] == "network_class":
        attached_entitytype = "slice_network_entity"
    else:
        attached_entitytype = None

    devs = []
    for row in cloud_utils.entity_attach(db, dbid, entitytype=attached_entitytype):
        devs.append(row["name"])
    j.update({"devices": devs})

    return j, None


container_keys = ["iops", "capacity", "type", "latency", "security", "datareduction"]


def _container(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    j.update({"iops": row["minimumiops"], "maximum_iops": row["maximumiops"], "burst_iops": row["burstiops"]})
    if row["tblstorageclassesid"] != 0:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % row["tblstorageclassesid"], None, db_in=db)
        j.update({"storage_class": req_entity["name"]})
    return j, None


volume_keys = ["capacity", "volumeclass", "voltype"]
volume_command = ["capacity", "volumeclass", "voltype", "entity_name", "entity_container", "command"]


def _volume(db, dbid, row, keys, **kwargs):
    try:
        j = _entity(db, dbid, row, entity_keys)
        j.update(_copy_kv(row, keys))

        j.update({"uuid": row["uniqueid"]})

        if "options" in kwargs and kwargs["options"]:
            j.update(_copy_kv(kwargs["options"], volume_command))

            if "mained" in kwargs["options"]:
                if "create_from" in kwargs["options"] and kwargs["options"]["create_from"] == "snapshot":
                    j.update({"command": "create_volume",
                              "create_from_type": "snapshot",
                              "create_from": get_snapshot_volume_container_dict(db, kwargs["options"]["mained"])})

        if "voltype" in j:
            j["volume_type"] = j["voltype"]
            del j["voltype"]

        j.update({"snapshot_params": {"snapshot_policy": row["snapshotpolicy"],
                                      "policy_type": row["snpolicytype"],
                                      "policy_limit": row["snpolicylimit"],
                                      "policy_hours": str_list(row["snpolicyhrs"]),
                                      }
                  })

        j.update({"backup_params": {"backup_policy": row["backuppolicy"],
                                    "policy_type": row["bkpolicytype"],
                                    "policy_time": date_str(row["bkpolicytime"]),
                                    "policy_limit": row["bkpolicylimit"],
                                    "policy_weekdays": str_list(row["bkpolicyweekdays"]),
                                    "policy_monthdays": str_list(row["bkpolicymonthdays"])
                                    }
                  })

        j.update({"archive_params": {"archive_policy": row["archivepolicy"],
                                     "policy_type": row["arpolicytype"],
                                     "policy_time": date_str(row["arpolicytime"]),
                                     "policy_limit": row["arpolicylimit"],
                                     "policy_weekdays": str_list(row["arpolicyweekdays"]),
                                     "policy_monthdays": str_list(row["arpolicymonthdays"])
                                     }
                  })
        return j, None
    except:
        cloud_utils.log_exception(sys.exc_info())


# add any new snapshots, arhives, and backup records in the database
def post_rest_get_function_volume(db, dbid, rest_me, rest=None):
    if not rest_me:
        return
    if "snapshots" in rest_me:
        pass
    if "archives" in rest_me:
        pass
    if "backups" in rest_me:
        pass


def volume_post_final_status_function(db, dbid):
    pass


disk_keys = ["capacity"]


def _disk(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


partition_keys = ["capacity"]


def _partition(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


bucket_keys = ["capacity"]


def _bucket(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


object_keys = ["capacity"]


def _object(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


serverfarm_keys = ["initial", "min", "max", "scale_option"]


def _serverfarm(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))

    entity_utils.add_ssh_keys(db, dbid, j)
    add_user_data(db, dbid, j)
    net_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                    {"AttachedEntityId": dbid,
                                                     "AttachedEntityType": "serverfarm"},
                                                    order="ORDER BY id LIMIT 1"))
    if net_row:
        cns = cloud_utils.lower_key(
            db.get_row("tblEntities", "id='%s' AND deleted = 0" % net_row["tblentities"], order="ORDER BY id LIMIT 1"))
        if cns:
            j.update({"compute_service": cns["name"]})
        else:
            db.execute_db("DELETE FROM tblAttachedEntities WHERE id='%s' " % net_row["id"])
            LOG.critical(_("Serverfarm: %s: AttachedEntity %s deleted - Unable to find parent compute "
                           "service at %s" % (dbid, net_row["id"], net_row["tblentities"])))

    if row["dynopram"] == 0:
        row["ram_green"] = row["ram_red"] = 0
    if row["dynopcpu"] == 0:
        row["cpu_green"] = row["cpu_red"] = 0
    if row["dynopbandwidth"] == 0:
        row["bandwidth_green"] = row["bandwidth_red"] = 0

    j.update({"dynamic_option":
                  {"cpu": [row["cpu_green"], row["cpu_red"]],
                   "ram": [row["ram_green"], row["ram_red"]],
                   "bandwidth": [row["bandwidth_green"], row["bandwidth_red"]]
                   }
              })

    j.update({"uuid": row["uniqueid"]})
    j.update({"volumes": json_shared_volumes(db, dbid)})
    if row["tblcomputeclassesid"] != 0:
        req_entity = cache_utils.get_cache("db|tblEntities|id|%s" % row["tblcomputeclassesid"], None, db_in=db)
        j.update({"compute_class": req_entity["name"]})

    return j, None


def _serverfarm_post_db_create(db, dbid, options, mode=None, **kwargs):
    update_db_shared_volumes(db, dbid, options)
    update_db_metadata_keyvalue(db, dbid, options)


#### not  used any more
def update_db_shared_volumes(db, dbid, options):
    try:
        if options and "volumes" in options:
            # delete all old entries
            db.execute_db("DELETE tblAttachedEntities FROM tblAttachedEntities JOIN tblEntities "
                          " WHERE ( tblAttachedEntities.AttachedEntityId = tblEntities.id AND "
                          "         tblAttachedEntities.tblEntities = '%s' AND "
                          "         tblEntities.EntityType = 'volume') " % dbid)
            # add all listed entries
            order = 1
            for vid in options["volumes"]:
                cloud_utils.insert_db(db, "tblAttachedEntities", {"tblEntities": dbid,
                                                                  "AttachedEntityId": vid,
                                                                  "AttachedEntityType": "volume",
                                                                  "AttachedSortSequenceId": order})
                order += 1
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_child_parent_name(db, dbid, child=None, unique_id=None):
    if not child:
        child = cloud_utils.lower_key(
            db.get_row("tblEntities", "id='%s' AND deleted = 0" % dbid, order="ORDER BY id LIMIT 1"))
        if not child and unique_id:
            child = cloud_utils.lower_key(
                db.get_row("tblEntities", "uniqueid='%s' AND deleted = 0" % unique_id, order="ORDER BY id LIMIT 1"))
    if child:
        parent = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" %
                                                  child["parententityid"], order="ORDER BY id LIMIT 1"))
        if parent:
            vdc = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" %
                                                   parent["parententityid"], order="ORDER BY id LIMIT 1"))
            if not vdc:
                return child["name"], parent["name"], {}

            if vdc["entitytype"] == "organization":
                return child["name"], parent["name"], {vdc["entitytype"]: vdc["name"]}

            dept = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" %
                                                    vdc["parententityid"], order="ORDER BY id LIMIT 1"))
            if not dept:
                return child["name"], parent["name"], {vdc["entitytype"]: vdc["name"]}

            if dept["entitytype"] == "organization":
                return child["name"], parent["name"], {vdc["entitytype"]: vdc["name"], dept["entitytype"]: dept["name"]}

            org = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" %
                                                   dept["parententityid"], order="ORDER BY id LIMIT 1"))
            if org:
                return child["name"], parent["name"], \
                       {vdc["entitytype"]: vdc["name"], dept["entitytype"]: dept["name"],
                        org["entitytype"]: org["name"]}
            else:
                return child["name"], parent["name"], {vdc["entitytype"]: vdc["name"], dept["entitytype"]: dept["name"]}

    return None, None, None


def get_server_serverfarm_dict(db, dbid):
    child, parent, hierarchy = get_child_parent_name(db, dbid)
    if child:
        return {"server_name": child, "serverfarm_name": parent, "hierarchy": hierarchy}
    return {}


def get_image_library_dict(db, dbid, unique_id=None):
    child, parent, hierarchy = get_child_parent_name(db, dbid, unique_id=unique_id)
    if child:
        return {"image_name": child, "library_name": parent, "hierarchy": hierarchy}
    return {}


def get_snapshot_volume_container_dict(db, dbid):
    snapshot = cloud_utils.lower_key(
        db.get_row("tblEntities", "id='%s' AND deleted = 0" % dbid, order="ORDER BY id LIMIT 1"))
    if not snapshot:
        return {}
    child, parent, hierarchy = get_child_parent_name(db, snapshot["parententityid"])
    if child:
        return {"snapshot_name": snapshot["name"], "volume_name": child, "container_name": parent,
                "hierarchy": hierarchy}
    return {}


def get_volume_container_dict(db, dbid, unique_id=None):
    child, parent, hierarchy = get_child_parent_name(db, dbid, unique_id=unique_id)
    if child:
        return {"volume_name": child, "container_name": parent, "hierarchy": hierarchy}
    return {}


def get_group_connection_dict(db, dbid):
    child, parent, hierarchy = get_child_parent_name(db, dbid)
    if child:
        return {"tunnel_name": child, "group_name": parent, "hierarchy": hierarchy}
    return {}


def json_shared_volumes(db, dbid):
    volumes = []
    for shr in cloud_utils.entity_attach(db, dbid, entitytype="volume"):
        cv = get_volume_container_dict(db, shr["id"])
        if cv:
            volumes.append(cv)
    return volumes


def update_db_virtual_networks(db, dbid, options):
    try:
        if options and "mappings" in options:
            # delete all old entries
            db.execute_db("DELETE tblAttachedEntities FROM tblAttachedEntities JOIN tblEntities "
                          " WHERE ( tblAttachedEntities.AttachedEntityId = tblEntities.id AND "
                          "         tblAttachedEntities.tblEntities = '%s' "
                          "         ) " % dbid)
            # add all listed entries
            order = 1
            for vid in options["mappings"]:
                cloud_utils.insert_db(db, "tblAttachedEntities", {"tblEntities": dbid,
                                                                  "AttachedEntityId": vid,
                                                                  "AttachedEntityType": "virtual_network",
                                                                  "AttachedSortSequenceId": order})
                order += 1
    except:
        cloud_utils.log_exception(sys.exc_info())


virtual_networks_keys = ["networktype", "throughput"]


def _virtual_networks(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    j.update({"mappings": json_virtual_networks(db, dbid)})
    return j, None


def _virtual_networks_pre_db_delete(db, dbid, options, mode=None, **kwargs):
    db.execute_db("UPDATE tblServices SET SharedExternalNetworkEntityId = 0, "
                  "SharedExternalNetworkUniqueId=NULL  WHERE SharedExternalNetworkEntityId = '%s' " % dbid)


def _virtual_networks_post_db_create(db, dbid, options, mode=None, **kwargs):
    update_db_virtual_networks(db, dbid, options)


def json_virtual_networks(db, dbid):
    entity = []
    for row in cloud_utils.entity_attach(db, dbid):
        cv = {}
        if row["entitytype"] == "department":
            cv = {"department_name": row["name"]}
        else:
            child, parent, heirarcy = get_child_parent_name(db, row["id"], child=row)
            if child and parent:
                cv = {"vdc_name": child, "department_name": parent, "heirarcy": heirarcy}
        if cv:
            entity.append(cv)
    return entity


server_keys = ["hypervisor", "boot_storage_type", "ephemeral_storage", "memory", "weight"]


def update_db_metadata_keyvalue(db, dbid, options):
    if options and "metadata" in options:
        # delete all old entries
        db.execute_db("DELETE FROM tblKeyValuePairs WHERE (tblEntities = '%s') " % dbid)
        # add all listed entries
        for meta in options["metadata"]:
            cloud_utils.insert_db(db, "tblKeyValuePairs", {"tblEntities": dbid,
                                                           "thekey": meta["thekey"], "thevalue": meta["thevalue"]})


def add_user_data(db, dbid, j):
    user_data = db.get_row_dict("tblUserData", {"tblEntities": dbid}, order="ORDER BY id LIMIT 1")
    if user_data:
        j.update({"user_data": user_data["User_Data"]})

    metadata = entity_utils.json_metadata_keyvalue(db, dbid)
    if metadata:
        j.update({"metadata": metadata})


def _server(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    entity_utils.add_ssh_keys(db, dbid, j)

    groups = {}
    grp = []
    for item in cloud_utils.entity_attach(db, dbid, entitytype="nat_network_service"):
        nat = {"nat_service": item["name"], "type": item["ipaddresstype"], "priority": item["attachedsortsequenceid"]}
        if item["ipaddresstype"].lower() == "static":
            nat["static_ip"] = item["staticipaddress"]
        grp.append(nat)
        if len(grp) > 0:
            groups["nat"] = grp
    if groups:
        j.update(groups)
    j.update({"cpu": [date_str(row["cpuvcpu"]), date_str(row["cpumhz"])]})
    j.update({"volumes": json_shared_volumes(db, dbid)})

    add_user_data(db, dbid, j)

    options = kwargs.get("options", None)

    boot = {}
    volume_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                       {"tblEntities": dbid,
                                                        "attachedentitytype": "volume_boot"},
                                                       order="ORDER BY id LIMIT 1"))
    if volume_row:
        boot = {"boot_volume": get_volume_container_dict(db, volume_row["attachedentityid"])}

        if options and "usertype" in options and options["usertype"] == "developer":
            boot.update({"options": {"create": "true",
                                     "capacity": options["bootvolumestorage"]}})
    if options and "command" in options:
        j.update({"command": options["command"]})

    image_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                      {"tblEntities": dbid,
                                                       "attachedentitytype": "image"},
                                                      order="ORDER BY id LIMIT 1"))
    if image_row:
        boot.update({"boot_image": get_image_library_dict(db, image_row["attachedentityid"],
                                                          unique_id=image_row["attachedentityuniqueid"])})

    # if row["bootimageentityid"] and row["bootimageentityid"] != 0:
    #        boot.update({"boot_image": get_image_library_dict(db, row["bootimageentityid"])})

    if boot:
        j.update({"server_boot": boot})
    return j, None


def _server_pre_db_create(db, options, mode=None, parent_row=None, **kwargs):
    try:
        if mode != "create" or not parent_row:
            return
        last_server_entity = db.get_row("tblEntities",
                                        " EntityType = 'server' AND deleted=0 AND ParentEntityId = '%s'" % parent_row[
                                            "id"],
                                        " ORDER BY id DESC LIMIT 1")
        if not last_server_entity:
            return
        last_server = cloud_utils.lower_key(
            db.get_row("tblServers", "tblEntities = '%s'" % last_server_entity["id"], "LIMIT 1"))
        if not last_server:
            return
        if "hypervisor" not in options:
            options["hypervisor"] = last_server["hypervisor"]
        if "cpuvcpu" not in options:
            options["cpuvcpu"] = last_server["cpuvcpu"]
        if "memory" not in options:
            options["memory"] = last_server["memory"]
        if "ephemeral_storage" not in options:
            options["ephemeral_storage"] = last_server["ephemeral_storage"]
    except:
        cloud_utils.log_exception(sys.exc_info())


def _server_post_db_create(db, dbid, options, mode=None, **kwargs):
    try:
        update_db_shared_volumes(db, dbid, options)
        update_db_metadata_keyvalue(db, dbid, options)

        if "nats" in options and not options["nats"]:
            db.execute_db("DELETE FROM tblAttachedEntities  "
                          " WHERE ( tblEntities = '%s' AND AttachedEntityType = 'nat_network_service' ) " % dbid)
        last_library = None
        if "boot_image" in options and "parententityid" in options:
            cluster = cloud_utils.lower_key(
                db.get_row_dict("tblEntities", {"id": options["parententityid"]}, order="ORDER BY id LIMIT 1"))
            if not cluster:
                return

            vdc = cloud_utils.lower_key(
                db.get_row_dict("tblEntities", {"id": cluster["parententityid"], "entitytype": "vdc",
                                                }, order="ORDER BY id LIMIT 1"))
            if not vdc:
                return

            if "image_name" in options["boot_image"] and "library_name" in options["boot_image"]:
                library = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                {"name": options["boot_image"]["library_name"],
                                                                 "entitytype": "imagelibrary", "deleted": 0,
                                                                 }, order="ORDER BY id LIMIT 1"))
                if not library:
                    return
                image = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                              {"name": options["boot_image"]["image_name"],
                                                               "entitytype": "image", "deleted": 0,
                                                               "parententityid": library["id"]
                                                               }, order="ORDER BY id LIMIT 1"))
                if not image:
                    return
                options["bootimageentityid"] = image["id"]
                cloud_utils.update_or_insert(db, "tblEntities", options, {"id": dbid},
                                             child_table=entities[options["entitytype"]].child_table)
            return
        elif mode == "create":
            last_image = None
            parent = entity_utils.read_partial_entity(db, options["parententityid"])
            last_server = db.execute_db("SELECT * FROM tblEntities  "
                                        " WHERE  (  "
                                        " EntityType = 'server' AND deleted=0 AND "
                                        " id != '%s' AND ParentEntityId = '%s')"
                                        " ORDER BY id DESC LIMIT 1" % (dbid, parent["id"]))
            if last_server:
                last_image = db.execute_db("SELECT * FROM tblAttachedEntities  "
                                           " WHERE  (  "
                                           " AttachedEntityType = 'image'  AND "
                                           " tblEntities = '%s')"
                                           " ORDER BY id DESC LIMIT 1" % last_server[0]["id"])
                if last_image:
                    cloud_utils.insert_db(db, "tblAttachedEntities", {"tblEntities": dbid,
                                                                      "AttachedEntityId": last_image[0][
                                                                          "AttachedEntityId"],
                                                                      "attachedentityname": last_image[0][
                                                                          "AttachedEntityName"],
                                                                      "attachedentityparentname": last_image[0][
                                                                          "AttachedEntityParentName"],
                                                                      "AttachedEntityUniqueId": last_image[0][
                                                                          "AttachedEntityUniqueId"],
                                                                      "AttachedEntityType": "image"})
            if not last_image:
                slice_row = db.execute_db(
                    "SELECT * FROM tblEntities WHERE EntityType = 'slice' AND deleted=0 ORDER BY id DESC LIMIT 1")
                last_library = db.execute_db("SELECT * FROM tblEntities  "
                                             " WHERE  (  "
                                             " EntityType = 'imagelibrary' AND deleted=0 AND "
                                             " ParentEntityId = '%s')"
                                             " ORDER BY id DESC LIMIT 1" % slice_row[0]["id"])
                if last_library:
                    last_image = db.execute_db("SELECT * FROM tblEntities  "
                                               " WHERE  (  "
                                               " EntityType = 'image' AND deleted=0 AND "
                                               " ParentEntityId = '%s')"
                                               " ORDER BY id DESC LIMIT 1" % last_library[0]["id"])
                    if last_image:
                        cloud_utils.insert_db(db, "tblAttachedEntities", {"tblEntities": dbid,
                                                                          "AttachedEntityId": last_image[0]["id"],
                                                                          "attachedentityname": last_image[0]["Name"],
                                                                          "attachedentityparentname": last_library[0][
                                                                              "Name"],
                                                                          "AttachedEntityUniqueId": last_image[0][
                                                                              "UniqueId"],
                                                                          "AttachedEntityType": "image"})

    except:
        cloud_utils.log_exception(sys.exc_info())


vdc_accepting_profiles = ["suspended", "suspending", "provisioned", "provisioning", "activated", "activating", "active"]


def _volume_pre_db_create(db, options, mode=None, parent_row=None, **kwargs):
    try:
        if mode != "create" or not parent_row:
            return
        last_volume_entity = db.get_row("tblEntities",
                                        " EntityType = 'volume' AND deleted=0 AND ParentEntityId = '%s'" % parent_row[
                                            "id"],
                                        " ORDER BY id DESC LIMIT 1")
        if not last_volume_entity:
            return
        last_volume = cloud_utils.lower_key(
            db.get_row("tblContainerVolumes", "tblEntities = '%s'" % last_volume_entity["id"], "LIMIT 1"))
        if not last_volume:
            return
        if "capacity" not in options:
            options["capacity"] = last_volume["capacity"]
        if "voltype" not in options:
            options["voltype"] = last_volume["voltype"]
        if "permissions " not in options:
            options["permissions "] = last_volume["permissions"]

    except:
        cloud_utils.log_exception(sys.exc_info())


def _check_profile_parent_status(db, dbid, row):
    if row["entitytype"] == "system":
        return None
    elif row["entitytype"] == "organization":
        return None
    elif row["entitytype"] == "department":
        return None
    elif row["entitytype"] == "vdc":
        if row["entitystatus"].lower() in vdc_accepting_profiles:
            return row
        else:
            return None
    else:
        parent, error = entity_utils.read_full_entity_status_tuple(db, row["parententityid"])
        if error or not parent:
            return None
        return _check_profile_parent_status(db, parent["id"], parent)


def _cfa_post_db_create(db, dbid, options, mode=None, **kwargs):
    row = db.get_row("tblComputeEntities", "tblEntities=%s" % dbid, order="ORDER BY id LIMIT 1")
    if not row:
        return
    vcpu = row["Sockets"] * row["Cores"] * row["Threads"] * row["CPU_OverAllocation"]
    db.update_db("UPDATE tblComputeEntities SET vcpu=%s WHERE id = %s" % (vcpu, row['id']))


def post_rest_get_function_slice_entities(db, dbid, rest_me, rest=None):
    if not rest_me:
        return
    rest_me.pop("description", None)
    rest_me.pop("extra_specs", None)


def _slice_physical_json(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    j.update({"pool": row["entitypool"]})
    classes = []
    for e_row in entity_utils.get_next_attached_parent_entity(db, dbid, entitytype=entity_constants.entitytype_class[
        row["entitytype"]]):
        classes.append(e_row["name"])
    j.update({"classes": classes})
    if "entitytype" in row and row["entitytype"] == "slice_compute_entity" and "cpu_overallocation" in row:
        j.update({"cpu_overallocation": row["cpu_overallocation"]})
    j.update({"extra_specs": row["extra_specs"]})

    return j, None


slice_attached_network_keys = ["foreign_addresses"]


def _slice_attached_network(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


def _slice_attached_network_post_db_create(db, dbid, options, mode=None, **kwargs):
    if mode == "update" and "foreign_addresses" in options:
        db.update_db("UPDATE tblAttachedNetworkEntities SET  user_foreign_addresses='%s' WHERE tblEntities='%s'" %
                     (options["foreign_addresses"], dbid))


image_library_keys = []


def _image_library(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


def _image_post_db_create(db, dbid, options, mode=None, **kwargs):
    try:
        options["command"] = "get_token"
    except:
        cloud_utils.log_exception(sys.exc_info())


image_keys = ["version", "architecture", "image_state", "min_disk", "min_ram", "image_size", "disk_format",
              "container_format", "ostype",
              "hw_disk_bus", "hw_cdrom_bus", "hw_vif_model"]


def _image(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update({"uuid": row["uniqueid"]})
    if "options" in kwargs and kwargs["options"]:
        if "command" in kwargs["options"]:
            j.update({"command": kwargs["options"]["command"]})

        if "mained" in kwargs["options"]:
            if "create_from" in kwargs["options"] and kwargs["options"]["create_from"] == "volume":
                j.update({"command": "create_image",
                          "create_from_type": "volume",
                          "create_from": get_volume_container_dict(db, kwargs["options"]["mained"])})

            elif "create_from" in kwargs["options"] and kwargs["options"]["create_from"] == "server":
                j.update({"command": "create_image",
                          "create_from_type": "server",
                          "create_from": get_server_serverfarm_dict(db, kwargs["options"]["mained"])})
    j.update(_copy_kv(row, keys))
    return j, None


def post_rest_get_function_image(db, dbid, rest_me, rest=None):
    if not rest_me:
        return

    if "glance_url" in rest_me:
        db.update_db("UPDATE tblLibraryImages SET  glance_url='%s' WHERE tblEntities='%s'" %
                     (rest_me["glance_url"], dbid))

    if "glance_token" in rest_me and "token_expires_at" in rest_me:
        db.update_db(
            "UPDATE tblLibraryImages SET  glance_token='%s', glance_token_expires_at='%s' WHERE tblEntities='%s'" %
            (rest_me["glance_token"], rest_me["token_expires_at"], dbid))


security_group_keys = []


def _security_group(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


security_rule_keys = ["action", "alarm_threshold", "from_port", "to_port", "source_ip", "destination_ip",
                      "track", "traffic_direction", "protocol", "fw_application"]


def _security_rule(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    j.update({"start_time": date_str(row["start_time"])})
    j.update({"stop_time": date_str(row["stop_time"])})

    net_row = cloud_utils.lower_key(db.get_row_dict("tblAttachedEntities",
                                                    {"tblEntities": dbid,
                                                     "attachedentitytype": "vpn_connection"},
                                                    order="ORDER BY id LIMIT 1"))
    if net_row:
        j.update({"vpn_tunnel": get_group_connection_dict(db, net_row["attachedentityid"])})
    return j, None


lbs_group_keys = []


def _lbs_group(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


lbs_service_keys = ["port", "method", "health_monitor", "health_check_interval",
                    "health_check_retries", "persistence", "persistencetimeout",
                    "frontend_timeout", "frontend_mode",
                    "frontend_cookie", "frontend_accept_proxy",
                    "backend_port", "backend_mode", "backend_timeout",
                    "backend_connect_timeout", "backend_connect_retries",
                    "backend_forwardfor", "backend_send_proxy"]


def _lbs_service(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


acl_group_keys = []


def _acl_group(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


acl_rule_keys = ["action", "from_port", "to_port", "source_ip", "destination_ip",
                 "traffic_direction", "protocol", "service"]


def _acl_rule(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


vpn_group_keys = []


def _vpn_group(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


vpn_connection_keys = ["authenticationmode",
                       "p1authentication", "p1encryption", "p1ikemode", "p1ikeversion", "p1salifetime", "p1keepalive"
                                                                                                        "p1nattraversal",
                       "p1pfs",
                       "p2activeprotocol", "p2authentication", "p2encapsulatioprotocol",
                       "p2encryption", "p2pfs", "p2replaydetection", "p1salifetime",
                       "peeraddress", "peersubnets", "psk", "peerid",
                       "initiator", "dpdaction", "dpdinterval", "dpdtimeout", "remotename"
                       ]


def _vpn_connection(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


def _check_vdc_status(db, dbid, row):
    return _check_profile_parent_status(db, dbid, row)


def vdc_post_final_status_function(db, dbid):
    pass


def _interface_pre_db_create(db, options, mode=None, **kwargs):
    try:
        error = entity_utils.confirm_options_keys(options, ["beginserviceentityid", "endserviceentityid"])
        begin_row = end_row = None
        if error:
            if not "beginserviceentityid" in options:
                if not "beginserviceentityname" in options:
                    return error
                begin_row = cloud_utils.lower_key(
                    db.get_row_dict("tblEntities", {"parententityid": options["parententityid"],
                                                    "name": options["beginserviceentityname"],
                                                    "entitysubtype": "network_service"
                                                    }, order="ORDER BY id LIMIT 1"))
                if not begin_row:
                    return error
                options["beginserviceentityid"] = begin_row["id"]

            if not "endserviceentityid" in options:
                if not "endserviceentityname" in options:
                    return error
                end_row = cloud_utils.lower_key(
                    db.get_row_dict("tblEntities", {"parententityid": options["parententityid"],
                                                    "name": options["endserviceentityname"],
                                                    "entitysubtype": "network_service"
                                                    }, order="ORDER BY id LIMIT 1"))
                if not end_row:
                    return error
                options["endserviceentityid"] = end_row["id"]

        if not begin_row:
            begin_row = entity_utils.read_partial_entity(db, options["beginserviceentityid"])
        if not end_row:
            end_row = entity_utils.read_partial_entity(db, options["endserviceentityid"])

        if not begin_row or not end_row:
            return "error"

        if begin_row["entitytype"] == "nms_network_service" or end_row["entitytype"] == "nms_network_service":
            options["interfacetype"] = "tap"

        if "interfaceindex" not in options:
            options["interfaceindex"] = 0

        if "ports" not in options or not isinstance(options["ports"][0]["serviceentityid"],
                                                    (int, long)) or not isinstance(
            options["ports"][1]["serviceentityid"], (int, long)):
            options["ports"] = [{"serviceentityid": options["beginserviceentityid"]},
                                {"serviceentityid": options["endserviceentityid"]}]

        rows = db.execute_db(
            "SELECT tblEntities.*, tblServicesInterfaces.* FROM tblEntities JOIN tblServicesInterfaces   "
            " WHERE ( tblServicesInterfaces.tblEntities = tblEntities.id AND "
            " tblServicesInterfaces.InterfaceIndex = '%s' AND "
            "         (tblServicesInterfaces.BeginServiceEntityId = '%s' OR "
            "          tblServicesInterfaces.EndServiceEntityId = '%s')) " %
            (options["interfaceindex"], options["beginserviceentityid"], options["beginserviceentityid"]))
        if not rows:
            return None
        for row in rows:
            row = cloud_utils.lower_key(row)
            if row["beginserviceentityid"] == options["beginserviceentityid"]:
                if row["endserviceentityid"] != options["endserviceentityid"]:
                    continue
            else:
                # row's end must match with options begin
                if row["beginserviceentityid"] != options["endserviceentityid"]:
                    continue
            delete_interface_ports(db, row["id"], options["interfaceindex"])
            entity_utils.delete_entity_recursively(db, row["id"])
    except:
        cloud_utils.log_exception(sys.exc_info())
    return None


import ujson


def create_switch_gateways(db, dbid, skip_dbid):
    try:
        gateways = []
        for interface in cloud_utils.network_service_interfaces(db, dbid):
            remote_service = find_remote_service(db, dbid, interface)
            if remote_service["id"] != skip_dbid:
                remote_service = entity_utils.read_partial_entity(db, remote_service["id"])
                gateways.append({"name": remote_service["name"], "dbid": remote_service["id"]})
        return gateways
    except:
        cloud_utils.log_exception(sys.exc_info())


def find_remote_service(db, dbid, interface):
    try:
        if interface["beginserviceentityid"] == dbid:
            remote_dbid = interface["endserviceentityid"]
        else:
            remote_dbid = interface["beginserviceentityid"]
        remote_service = entity_utils.read_partial_entity(db, remote_dbid)
        if remote_service["entitytype"] == "tap_network_service":
            for tap_interface in cloud_utils.network_service_interfaces(db, remote_dbid):
                if tap_interface["interfacetype"] == "tap":
                    continue
                if tap_interface["beginserviceentityid"] == remote_dbid:
                    if tap_interface["endserviceentityid"] == dbid:
                        continue
                    remote_dbid = tap_interface["endserviceentityid"]
                    break
                else:
                    if tap_interface["beginserviceentityid"] == dbid:
                        continue
                    remote_dbid = tap_interface["beginserviceentityid"]
                    break
            remote_service = entity_utils.read_partial_entity(db, remote_dbid)
        return remote_service
    except:
        cloud_utils.log_exception(sys.exc_info())


def update_default_gateways(db, service, parent_svcid):
    try:
        if service["entitytype"] == "fws_network_service" or service["entitytype"] == "rts_network_service" or \
                        service["entitytype"] == "lbs_network_service" or service[
            "entitytype"] == "ipsecvpn_network_service":
            gateways = [{"name": "Default", "dbid": 0}]
            for interface in cloud_utils.network_service_interfaces(db, service["id"]):
                remote_service = find_remote_service(db, service["id"], interface)
                if remote_service["entitytype"] == "switch_network_service":
                    gateways.extend(create_switch_gateways(db, remote_service["id"], service["id"]))
                else:
                    gateways.append({"name": remote_service["name"], "dbid": remote_service["id"]})
            cloud_utils.update_only(db, "tblServices", {"defaultgateways": ujson.dumps(gateways)},
                                    {"tblEntities": service["id"]})

        if service["entitytype"] == "switch_network_service":
            for interface in cloud_utils.network_service_interfaces(db, service["id"]):
                remote_service = find_remote_service(db, service["id"], interface)
                if remote_service["id"] == parent_svcid:
                    continue
                update_default_gateways(db, remote_service, service["id"])
    except:
        cloud_utils.log_exception(sys.exc_info())


def _interface_post_db_create(db, dbid, options, mode=None, **kwargs):
    try:
        if "vertices" in options and isinstance(options["vertices"], list):
            db.execute_db("DELETE FROM tblInterfaceVertices WHERE tblentities='%s' " % dbid)
            for vertex in options["vertices"]:
                vertex["tblEntities"] = dbid
                cloud_utils.insert_db(db, "tblInterfaceVertices", vertex)

        if "beginserviceentityid" in options and "endserviceentityid" in options:
            if "ports" in options:
                index = options.get("interface_index", 0)
                beginportid = endportid = 0
                # delete any leftover ports
                services = []
                delete_interface_ports(db, dbid, index)
                for config in options["ports"]:
                    if "serviceentityid" in config:
                        source_dbid = config["serviceentityid"]
                        if options["beginserviceentityid"] == source_dbid:
                            destination_dbid = options["endserviceentityid"]
                        else:
                            destination_dbid = options["beginserviceentityid"]

                        if "name" not in config:
                            destination_service = entity_utils.read_partial_entity(db, destination_dbid)
                            services.append(destination_service)
                            #                                cloud_utils.lower_key(db.get_row_dict("tblEntities",
                            #                                                                                        {"id": destination_dbid}, order="ORDER BY id LIMIT 1"))
                            #                            config["name"] = cloud_utils.generate_uuid()
                            config["name"] = destination_service["name"]

                        config.update({"destinationserviceentityid": destination_dbid,
                                       "finaldestinationserviceid": destination_dbid,
                                       "serviceinterfaceentityid": dbid,
                                       "entitytype": "service_port",
                                       "interfaceportindex": index,
                                       "parententityid": source_dbid})

                        pid = cloud_utils.update_or_insert(db, "tblEntities", config, None,
                                                           child_table="tblServicePorts")
                        remove_and_add_attached_entities(db, pid, config, mode="create")

                        if options["beginserviceentityid"] == source_dbid:
                            beginportid = pid
                        else:
                            endportid = pid
                cloud_utils.update_or_insert(db, "tblEntities", {"BeginServicePortId": beginportid,
                                                                 "EndServicePortId": endportid}, {"id": dbid},
                                             child_table="tblServicesInterfaces")

                for service in services:
                    update_default_gateways(db, service, 0)

    except:
        cloud_utils.log_exception(sys.exc_info())


def _interface_post_db_delete(db, dbid, interface_row):
    service = cloud_utils.lower_key(
        db.get_row("tblEntities", "id='%s' AND deleted = 0" % interface_row["beginserviceentityid"],
                   order="ORDER BY id LIMIT 1"))
    if service:
        update_default_gateways(db, service, 0)
    service = cloud_utils.lower_key(
        db.get_row("tblEntities", "id='%s' AND deleted = 0" % interface_row["endserviceentityid"],
                   order="ORDER BY id LIMIT 1"))
    if service:
        update_default_gateways(db, service, 0)


def _delete_tap_interface(db, dbid, interface_row, tap_service):
    # we need to delete the tap interface; all "tap" type interfaces and the other regular
    north_interface_dbid = _tap_network_service_pre_db_delete(db, tap_service["id"], tap_service)
    entity_utils.delete_entity_recursively(db, tap_service["id"])
    return north_interface_dbid


def _interface_pre_db_delete(db, dbid, interface_row):
    try:
        if (interface_row["interfacetype"]) != "tap":
            north_service = cloud_utils.lower_key(
                db.get_row("tblEntities", "id='%s' AND deleted = 0" % interface_row["beginserviceentityid"],
                           order="ORDER BY id LIMIT 1"))
            if north_service and north_service["entitytype"] == "tap_network_service":
                return _delete_tap_interface(db, dbid, interface_row, north_service)
            south_service = cloud_utils.lower_key(
                db.get_row("tblEntities", "id='%s' AND deleted = 0" % interface_row["endserviceentityid"],
                           order="ORDER BY id LIMIT 1"))
            if south_service and south_service["entitytype"] == "tap_network_service":
                return _delete_tap_interface(db, dbid, interface_row, south_service)
        delete_interface_ports(db, dbid, interface_row.get("interface_index", 0))
        return 0

    except:
        cloud_utils.log_exception(sys.exc_info())


def _delete_an_interface_and_ports(db, dbid, index):
    delete_interface_ports(db, dbid, index)
    db.execute_db("UPDATE tblEntities SET tblEntities.deleted=1, tblEntities.deleted_at= now() "
                  " WHERE id = '%s' " % dbid)


def _tap_network_service_pre_db_delete(db, dbid, service_row):
    try:
        north_interface = south_interface = None
        for int in cloud_utils.get_next_service_interface(db, dbid):
            if int["interfacetype"] == "tap":
                _delete_an_interface_and_ports(db, int["id"], int["interfaceindex"])

            elif not north_interface:
                north_interface = int
            elif not south_interface:
                south_interface = int
            else:
                _delete_an_interface_and_ports(db, int["id"], int["interfaceindex"])
                LOG.critical(
                    _("More than 2 non-tap interfaces with a tap at: %s and interface at %s" % (dbid, int["id"])))

        if not south_interface or not north_interface:
            LOG.critical(_("Less than 2 non-tap interfaces with a tap at: %s" % dbid))
            if south_interface:
                entity_utils.delete_entity_recursively(db, south_interface["id"])
            if north_interface:
                entity_utils.delete_entity_recursively(db, north_interface["id"])
            return

        # we are now left with north and south interfaces and associated ports.  We will keep the north interface and remove the south interface.
        north_interface_south_port_dbid = north_interface["endserviceportid"]

        south_interface_south_port_dbid = south_interface["endserviceportid"]

        # fix up south service's port's name and interface id
        north_port = entity_utils.read_full_entity(db, north_interface_south_port_dbid)
        config = {"name": north_port["name"], "serviceinterfaceentityid": north_interface["id"]}
        cloud_utils.update_or_insert(db, "tblEntities", config, {"id": south_interface_south_port_dbid},
                                     child_table="tblServicePorts")

        # fix up north service's port's name
        tap_service_north_port = entity_utils.read_full_entity(db, south_interface["beginserviceportid"])

        config = {"name": tap_service_north_port["name"]}
        cloud_utils.update_or_insert(db, "tblEntities", config, {"id": north_interface["beginserviceportid"]},
                                     child_table="tblServicePorts")

        save_endserviceentityid = north_interface["endserviceentityid"]
        save_endserviceportid = north_interface["endserviceportid"]

        north_interface["endserviceentityid"] = south_interface["endserviceentityid"]
        north_interface["endserviceportid"] = south_interface["endserviceportid"]

        cloud_utils.update_or_insert(db, "tblEntities", north_interface, {"id": north_interface["id"]},
                                     child_table="tblServicesInterfaces")

        entity_utils.delete_entity_recursively(db, save_endserviceportid)
        entity_utils.delete_entity_recursively(db, south_interface["beginserviceportid"])
        entity_utils.delete_entity_recursively(db, south_interface["id"])

        #        db.execute_db("UPDATE tblEntities SET tblEntities.deleted=1, tblEntities.deleted_at= now() "
        #                          " WHERE id = '%s' " % save_endserviceportid)
        #
        #        db.execute_db("UPDATE tblEntities SET tblEntities.deleted=1, tblEntities.deleted_at= now() "
        #                          " WHERE id = '%s' " % south_interface["beginserviceportid"])
        #
        #        db.execute_db("UPDATE tblEntities SET tblEntities.deleted=1, tblEntities.deleted_at= now() "
        #                          " WHERE id = '%s' " % south_interface["id"])

        return north_interface["id"]
    except:
        cloud_utils.log_exception(sys.exc_info())


def _network_service_pre_db_delete(db, dbid, service_row):
    try:

        for interface_row in cloud_utils.get_next_service_interface(db, dbid):
            if (interface_row["interfacetype"]) != "tap":
                if interface_row["beginserviceentityid"] == int(dbid):
                    remote_dbid = interface_row["endserviceentityid"]
                else:
                    remote_dbid = interface_row["beginserviceentityid"]
                remote_service = cloud_utils.lower_key(
                    db.get_row("tblEntities", "id='%s' AND deleted = 0" % remote_dbid,
                               order="ORDER BY id LIMIT 1"))
                if remote_service and remote_service["entitytype"] == "tap_network_service":
                    _delete_tap_interface(db, dbid, interface_row, remote_service)

            delete_interface_ports(db, interface_row["id"], interface_row.get("interface_index", 0))
            db.execute_db("UPDATE tblEntities SET deleted=1, deleted_at= now() "
                          " WHERE id = '%s' " % interface_row["id"])


            ##delete all ports
            #        db.execute_db("UPDATE tblEntities JOIN tblServicePorts SET tblEntities.deleted=1, tblEntities.deleted_at= now() "
            #                          " WHERE ( tblServicePorts.tblEntities = tblEntities.id AND "
            #                          "        (tblServicePorts.DestinationServiceEntityId = '%s' OR "
            #                          "         tblEntities.ParentEntityId = '%s')) " % (dbid, dbid))
            #
            # delete all interfaces
            #        db.execute_db("UPDATE tblEntities JOIN tblServicesInterfaces SET tblEntities.deleted=1, tblEntities.deleted_at= now()  "
            #                          " WHERE ( tblServicesInterfaces.tblEntities = tblEntities.id AND "
            #                          "         (tblServicesInterfaces.BeginServiceEntityId = '%s' OR "
            #                          "          tblServicesInterfaces.EndServiceEntityId = '%s')) " % (dbid, dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_service_port(db, dbid):
    current_index = 0
    while True:
        row = db.get_row("tblEntities", "entitytype = 'service_port' "
                                        "AND deleted=0 AND parententityid=%s AND id > '%s'" % (dbid, current_index),
                         order="ORDER BY id LIMIT 1")
        if row:
            current_index = row['id']
            yield row
        else:
            break


def _ext_network_service_pre_db_delete(db, dbid, service_row):
    _network_service_pre_db_delete(db, dbid, service_row)
    net_row = cloud_utils.lower_key(
        db.get_row_dict("tblAttachedEntities", {"tblEntities": dbid}, order="ORDER BY id LIMIT 1"))
    if net_row and net_row["attachedentitytype"] == "virtual_network":
        _ext_remove_priors(db, dbid, service_row, net_row)


def _ext_remove_priors(db, dbid, service_row, net_row):
    for service in entity_utils.get_next_service(db, service_row["parententityid"]):
        if service["id"] != dbid:
            for sport in get_service_port(db, service["id"]):
                db.execute_db("DELETE FROM tblAttachedEntities "
                              " WHERE (tblEntities = %s AND AttachedEntityId = %s ) " % (
                                  sport["id"], net_row["attachedentityid"]))


organization_keys = []


def _organization(db, dbid, row, keys, **kwargs):
    j = entity_utils.build_entity(db, dbid)
    return j, None


department_keys = []


def _department(db, dbid, row, keys, **kwargs):
    j = entity_utils.build_entity(db, dbid)
    return j, None


vdc_keys = []


def _vdc(db, dbid, row, keys, **kwargs):
    j = entity_utils.build_entity(db, dbid)
    '''
    if "email" in row:
        j["email"] = row["email"]
    if "administrator" in row:
        j["administrator"] = row["administrator"]
    if "location" in row:
        j["location"] = row["location"]
    entity_utils.add_ssh_keys(db, dbid, j)
    if "user_data" in row and row["user_data"]:
        j["user_data"] = row["user_data"]
    add_user_data(db, dbid, j)
    '''
    return j, None


switch_keys = ["bandwidth"]


def _switch(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_copy_kv(row, keys))
    return j, None


network_service_keys = ["throughput", "maxinstancescount", "throughputinc",
                        "availability_option", "qos", "latency",
                        "default_gateway"]


def _get_entity_name(db, dbid, default=None):
    if dbid == 0:
        if default:
            return default
        return "Default"
    row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": dbid}, order="ORDER BY id LIMIT 1"))
    if row:
        return row["name"]
    else:
        return "None"


##                        "external_address_type": row["externalipaddresstype"],
#                        "external_address": row["externalipaddress"],
#                        "external_address_nat": _get_entity_name(db, row["externaladdressnatentityid"], default="none"),


def _network_services_common(db, dbid, row):
    try:
        if row["maxinstancescount"] < row["begininstancescount"]:
            row["maxinstancescount"] = row["begininstancescount"]
            row["begininstancescount"] = 1

        return {"params": {"availability_option": row["highavailabilityoptions"],
                           "default_gateway": _get_entity_name(db, row["defaultgatewayentityid"], default="default"),
                           "qos": row["qos"],
                           "throughput": row["throughputinc"],
                           "begin_instances_count": row["begininstancescount"],
                           "max_instances_count": row["maxinstancescount"],
                           "northbound": row["northbound_port"]
                           },
                "uuid": row['uniqueid'],
                "policy": {"sla": row["servicelevelagreement"], "sla_policy": row["servicelevelagreementpolicy"]
                           }
                }
    except:
        cloud_utils.log_exception(sys.exc_info())


def _network_services_autoscale(db, dbid, row):
    try:
        return {"autoscale": {"throughput_enabled": row["dynopbandwidth"], "throughput_red": row["throughtput_red"],
                              "throughput_green": row["throughput_green"],
                              "compute_enabled": row["dynopcpu"], "compute_red": row["cpu_red"],
                              "compute_green": row["cpu_green"],
                              "ram_enabled": row["dynopram"], "ram_red": row["ram_red"], "ram_green": row["ram_green"],
                              "cooldown_add": row["cooldown_up"], "cooldown_remove": row["cooldown_down"]}}
    except:
        cloud_utils.log_exception(sys.exc_info())


def _network_services_interfaces(db, dbid, svc):
    try:
        interfaces = []
        for row in cloud_utils.network_service_ports(db, dbid):
            interfaces.append({"subnet": _get_entity_name(db, row["destinationserviceentityid"], default="unknown"),
                               "name": row["name"],
                               "interface_type": row["interface_type"],
                               "params":
                                   {"guaranteed_bandwidth": row["guarbandwidth"],
                                    "maximum_bandwidth": row["maxbandwidth"],
                                    "maximum_iops": row["maxiops"],
                                    "guaranteed_iops": row["guariops"],
                                    "securityzone": row["securityzone"],
                                    "qos": row["qos"],
                                    "mtu": row["mtu"]
                                    }
                               })
        if interfaces:
            return {"interfaces": interfaces}
        else:
            return {}
    except:
        cloud_utils.log_exception(sys.exc_info())


def provision_network_service_ports(db, port_dbid):
    try:
        groups = {}
        grp = []
        for item in cloud_utils.entity_attach(db, port_dbid, entitytype="nat_network_service"):
            nat = {"nat_service": item["name"], "type": item["ipaddresstype"],
                   "priority": item["attachedsortsequenceid"]}
            if item["ipaddresstype"].lower() == "static":
                nat["static_ip"] = item["staticipaddress"]
            grp.append(nat)
        if len(grp) > 0:
            groups["nat"] = grp

        grp = []
        for item in cloud_utils.entity_attach(db, port_dbid, entitytype="virtual_network"):
            nat = {"network": item["name"]}
            grp.append(nat)
        if len(grp) > 0:
            groups["virtual_networks"] = grp

        for group in entity_constants.port_groups:
            grp = []
            for item in cloud_utils.entity_attach(db, port_dbid, entitytype=group["name"]):
                grp.append({group["item"]: item["name"], "priority": item["attachedsortsequenceid"]})
            if len(grp) > 0:
                groups[group["type"]] = grp

        return groups
    except:
        cloud_utils.log_exception(sys.exc_info())


nat_keys = []


def _service_port(db, dbid, row, keys, **kwargs):
    j = provision_network_service_ports(db, dbid)
    #    j.update({"subnet" : row['name']})
    #   return j, None
    j.update({"subnet": row["name"],
              "name": row["name"],
              "interface_type": row["interface_type"],
              "params":
                  {"guaranteed_bandwidth": row["guarbandwidth"],
                   "maximum_bandwidth": row["maxbandwidth"],
                   "maximum_iops": row["maxiops"],
                   "guaranteed_iops": row["guariops"],
                   "securityzone": row["securityzone"],
                   "qos": row["qos"],
                   "mtu": row["mtu"]
                   }})

    return j, None


def _nat(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_autoscale(db, dbid, row))
    j.update({"pat_mode": row["nat_pat_mode"],
              "nat_address_type": row["nat_address_type"],
              "nat_static_address": row["nat_static_address"]})

    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


def _post_rest_get_function_nat(db, dbid, rest_me, rest=None):
    pass


lbs_keys = []


def _lbs(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_autoscale(db, dbid, row))
    j.update(_network_services_interfaces(db, dbid, row))
    j.update({"lbs_mode": row["lbs_mode"]})
    return j, None


def _post_rest_get_function_lbs(db, dbid, rest_me, rest=None):
    pass


fws_keys = []


def _fws(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_autoscale(db, dbid, row))
    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


def _post_rest_get_function_fws(db, dbid, rest_me, rest=None):
    pass


rts_keys = []


def _rts(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_autoscale(db, dbid, row))
    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


def _post_rest_get_function_rts(db, dbid, rest_me, rest=None):
    pass


vpn_keys = []


def _vpn(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


def _post_rest_get_function_vpn(db, dbid, rest_me, rest=None):
    pass


nms_keys = []


def _nms(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    service_pairs = []
    for int in cloud_utils.get_next_service_interface(db, dbid):
        if int["interfacetype"] != "tap":
            continue
        if int["beginserviceentityid"] == dbid:
            tap_dbid = int["endserviceentityid"]
        else:
            tap_dbid = int["beginserviceentityid"]

        tap = entity_utils.read_partial_entity(db, tap_dbid)

        if not tap or tap["entitytype"] != "tap_network_service":
            continue

        north_service = south_service = None
        for intc in cloud_utils.get_next_service_interface(db, tap_dbid):
            if intc["interfacetype"] == "tap":
                continue
            if intc["beginserviceentityid"] == dbid or intc["beginserviceentityid"] == dbid:
                continue

            if intc["beginserviceentityid"] == tap_dbid:
                svc_dbid = intc["endserviceentityid"]
            else:
                svc_dbid = intc["beginserviceentityid"]

            if not north_service:
                north_service = entity_utils.read_partial_entity(db, svc_dbid)
            else:
                south_service = entity_utils.read_partial_entity(db, svc_dbid)
        if not north_service or not south_service:
            continue
        service_pairs.append({"services": north_service["name"] + ":" + south_service["name"]})
    j.update({"service_pairs": service_pairs})

    return j, None


def _post_rest_get_function_nms(db, dbid, rest_me, rest=None):
    pass


compute_keys = []


def _compute(db, dbid, row, keys, **kwargs):
    try:
        j = _entity(db, dbid, row, entity_keys)
        entity_utils.add_ssh_keys(db, dbid, j)
        add_user_data(db, dbid, j)
        j.update(_network_services_common(db, dbid, row))
        j.update(_network_services_interfaces(db, dbid, row))

        grp = []
        for item in cloud_utils.entity_attach(db, dbid, entitytype="serverfarm"):
            grp.append(item["name"])
        if len(grp) > 0:
            j.update({"serverfarm": grp})

        return j, None

    except:
        cloud_utils.log_exception(sys.exc_info())
    return {}, None


def _post_rest_get_function_compute(db, dbid, rest_me, rest=None):
    pass


storage_keys = []


def _storage(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


def _post_rest_get_function_storage(db, dbid, rest_me, rest=None):
    pass


ips_keys = []


def _ips(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    j.update(_network_services_common(db, dbid, row))
    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


def _tap_service_pre_db_create(db, options, mode=None, parent_row=None):
    if not parent_row:
        return "Invalid parent entity id"

    current_interface = entity_utils.read_full_entity(db, options.get("network_interface", 0))

    if not current_interface:
        return "Invalid interface row  id"

    north_service = entity_utils.read_full_entity(db, current_interface.get("beginserviceentityid", 0))
    if not north_service:
        return "Invalid interface row id - no begin service row id"
    if north_service["entitytype"] == "tap_network_service":
        return "Invalid interface row id - already a tapped interface"
    south_service = entity_utils.read_full_entity(db, current_interface.get("endserviceentityid", 0))

    if not south_service:
        return "Invalid interface row id - no begin service row id"
    if south_service["entitytype"] == "tap_network_service":
        return "Invalid interface row id - already a tapped interface"


def _tap_service_post_db_create(db, dbid, options, mode=None, **kwargs):
    try:
        if not mode or mode != "create":
            return 0

        current_interface = entity_utils.read_full_entity(db, options.get("network_interface", 0))

        new_interface = {}
        new_interface["entitytype"] = "network_interface"
        new_interface["name"] = entity_utils.create_entity_name(db, new_interface["entitytype"])
        new_interface["parententityid"] = current_interface["parententityid"]

        new_interface_dbid = cloud_utils.update_or_insert(db, "tblEntities", new_interface, None,
                                                          child_table=entities[new_interface["entitytype"]].child_table)

        new_interface = entity_utils.read_full_entity(db, new_interface_dbid)
        if not current_interface or not new_interface:
            return
        north_port = entity_utils.read_full_entity(db, current_interface.get("beginserviceportid", 0))
        south_port = entity_utils.read_full_entity(db, current_interface.get("endserviceportid", 0))

        north_service = entity_utils.read_full_entity(db, current_interface.get("beginserviceentityid", 0))


        # add north port for tap
        config = {}
        config["name"] = north_service["name"]

        config.update({"destinationserviceentityid": north_service["id"],
                       "finaldestinationserviceentityid": north_service["id"],
                       "serviceinterfaceentityid": options.get("network_interface", 0),
                       "entitytype": "service_port",
                       "interfaceportindex": current_interface["interfaceindex"],
                       "parententityid": dbid})

        north_pid = cloud_utils.update_or_insert(db, "tblEntities", config, None, child_table="tblServicePorts")

        south_service = entity_utils.read_full_entity(db, current_interface.get("endserviceentityid", 0))

        # add south port for tap
        config = {}
        config["name"] = south_service["name"]

        config.update({"destinationserviceentityid": south_service["id"],
                       "finaldestinationserviceentityid": south_service["id"],
                       "serviceinterfaceentityid": new_interface["id"],
                       "entitytype": "service_port",
                       "interfaceportindex": new_interface["interfaceindex"],
                       "parententityid": dbid})

        south_pid = cloud_utils.update_or_insert(db, "tblEntities", config, None, child_table="tblServicePorts")

        # Update name only in the north port -- while keeping the destination service id
        config = {"name": options["name"]}
        cloud_utils.update_or_insert(db, "tblEntities", config, {"id": current_interface["beginserviceportid"]})

        # update port with new name and new interface id for south service -- while keeping the destination service id
        config = {"name": options["name"], "serviceinterfaceentityid": new_interface["id"]}
        cloud_utils.update_or_insert(db, "tblEntities", config, {"id": current_interface["endserviceportid"]},
                                     child_table="tblServicePorts")

        new_interface["beginserviceentityid"] = dbid
        new_interface["beginserviceportid"] = south_pid
        new_interface["entitystatus"] = current_interface["entitystatus"]

        new_interface["endserviceentityid"] = current_interface["endserviceentityid"]
        new_interface["endserviceportid"] = current_interface["endserviceportid"]

        current_interface["endserviceentityid"] = dbid
        current_interface["endserviceportid"] = north_pid

        cloud_utils.update_or_insert(db, "tblEntities", current_interface, {"id": current_interface["id"]},
                                     child_table="tblServicesInterfaces")

        cloud_utils.update_or_insert(db, "tblEntities", new_interface, {"id": new_interface["id"]},
                                     child_table="tblServicesInterfaces")
    except:
        cloud_utils.log_exception(sys.exc_info())


def _post_rest_get_function_ips(db, dbid, rest_me, rest=None):
    pass


def _service_pre_db_create(db, options, mode=None, **kwargs):
    pass


def _network_service_post_db_create(db, dbid, options, mode=None, **kwargs):
    #    remove_and_add_attached_entities(db, dbid, options, mode)
    update_db_metadata_keyvalue(db, dbid, options)


def _port_post_db_create(db, dbid, options, mode=None, **kwargs):
    #    remove_and_add_attached_entities(db, dbid, options, mode)
    pass


def remove_and_add_attach_to_entities(db, dbid, options, mode=None):
    try:
        if not "attach_to" in options:
            return
        if not isinstance(options["attach_to"], list):
            LOG.critical(
                _("update attach to entities for dbid %s is not a list: %s" % (dbid, str(options["attach_to"]))))
            return

        current_rows = db.get_multiple_row("tblAttachedEntities", "AttachedEntityId = '%s'" % dbid)
        desired_row_ids = options["attach_to"]

        for row in current_rows:
            if row["tblEntities"] in desired_row_ids:
                desired_row_ids.remove(row["tblEntities"])
            else:
                db.execute_db("DELETE FROM tblAttachedEntities WHERE id='%s'" % row["id"])

        for row_id in desired_row_ids:
            cloud_utils.insert_db(db, "tblAttachedEntities", {"tblentities": row_id,
                                                              "attachedentityid": dbid,
                                                              "attachedentitytype": options["entitytype"]})
    except:
        cloud_utils.log_exception(sys.exc_info())


def remove_and_add_attached_entities(db, dbid, options, mode=None, entity_row=None):
    try:
        if not "attached_entities" in options:
            return

        if not isinstance(options["attached_entities"], list):
            LOG.critical(
                _("update attached entities for dbid %s is not a list: %s" % (dbid, str(options["attached_entities"]))))
            return

        for ent in options["attached_entities"]:
            if not isinstance(ent, dict):
                LOG.critical(_("update attached entities item for dbid %s is not a dict: %s" % (dbid, str(ent))))
                return
            if "entitytype" in ent:
                # this is a special case!  externla network may be attached to only one type of network
                if "entitytype" in options and options["entitytype"] == "externalnetwork":
                    net_row = cloud_utils.lower_key(
                        db.get_row_dict("tblAttachedEntities", {"tblEntities": dbid}, order="ORDER BY id LIMIT 1"))
                    if net_row and entity_row and net_row["attachedentitytype"] == "virtual_network":
                        _ext_remove_priors(db, dbid, entity_row, net_row)

                    if ent["entitytype"] == "virtual_network":
                        delete_entity = "slice_attached_network"
                    elif ent["entitytype"] == "slice_attached_network":
                        delete_entity = "virtual_network"

                    else:
                        delete_entity = ent["entitytype"]

                    db.execute_db("DELETE FROM tblAttachedEntities  "
                                  " WHERE ( tblEntities = '%s' AND AttachedEntityType = '%s' ) " % (
                                      dbid, delete_entity))

                if ent["entitytype"] != "ssh_user":
                    while True:
                        tmp = db.execute_db("SELECT * FROM tblAttachedEntities  "
                                            " WHERE ( tblEntities = '%s' AND AttachedEntityType = '%s'  ) LIMIT 1" % (
                                                dbid, ent["entitytype"]))
                        if not tmp:
                            break
                        tmp = tmp[0]
                        db.execute_db("DELETE FROM tblAttachedEntities WHERE (id = '%s' ) " % tmp["id"])
                        db.execute_db("UPDATE tblEntities SET EntityBridgeId=0 WHERE (EntityBridgeId = '%s') " % tmp[
                            "tblEntities"])

                if ent["entitytype"] == "acl_group":
                    pass
                # remove all old entities
                order = 0
                if "entities" in ent:
                    if not isinstance(ent["entities"], list):
                        LOG.critical(_("update attached_entities entities item for dbid %s is not a list: %s" % (
                            dbid, str(ent["entities"]))))
                        continue
                    for pri in ent["entities"]:
                        if not isinstance(pri, dict):
                            LOG.critical(_("update attached_entities entities item for dbid %s is not adict: %s" % (
                                dbid, str(pri))))
                            continue
                        if "AttachedSortSequenceId" in pri:
                            order = pri["AttachedSortSequenceId"]
                        else:
                            order += 1
                            pri["AttachedSortSequenceId"] = order

                        pri["tblEntities"] = dbid
                        if "entitytype" in options:
                            pri["entitytype"] = options["entitytype"]
                        else:
                            pri["entitytype"] = ""

                        pri["attachedentitytype"] = ent["entitytype"]

                        if "attachedentityid" in pri:
                            attach_entity = cloud_utils.lower_key(
                                db.get_row_dict("tblEntities", {"id": pri["attachedentityid"]},
                                                order="ORDER BY id LIMIT 1"))
                            if not attach_entity:
                                continue
                            attach_entity_parent = cloud_utils.lower_key(
                                db.get_row_dict("tblEntities", {"id": attach_entity["parententityid"]},
                                                order="ORDER BY id LIMIT 1"))
                            if not attach_entity_parent:
                                continue
                            pri["attachedentityname"] = attach_entity["name"]
                            pri["attachedentityuniqueid"] = attach_entity["uniqueid"]
                            pri["attachedentityparentname"] = attach_entity_parent["name"]

                            cloud_utils.update_or_insert(db, "tblAttachedEntities",
                                                         pri, {"tblentities": dbid,
                                                               "attachedentityid": pri["attachedentityid"],
                                                               })

                            #                            db.execute_db("INSERT INTO tblAttachedEntities (tblEntities, AttachedEntityId, AttachedSortSequenceId) VALUES ('%s', '%s', '%s')" %
                            #                              (dbid, i["dbid"], order))

    except:
        cloud_utils.log_exception(sys.exc_info())


externalnetwork_keys = []


def get_first_active_slice(db):
    slice = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"EntityType": "slice", "EntityStatus": "active"},
                                                  order="ORDER BY id LIMIT 1"))
    if not slice:
        slice = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"EntityType": "slice"},
                                                      order="ORDER BY id LIMIT 1"))
    return slice


def _externalnetwork_post_db_create(db, dbid, options, mode=None, **kwargs):
    if mode != "create":
        return
    try:
        net = None
        if "network" in options and "name" in options["network"] and "slice" in options["network"]:
            net = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                        {"ParentEntityId": options["network"]["slice"],
                                                         "EntityType": "slice_attached_network",
                                                         "Name": options["network"]["name"]},
                                                        order="ORDER BY id LIMIT 1"))
        elif "parententityid" in options:
            parent_row, status = entity_utils.read_full_entity_status_tuple(db, options["parententityid"])
            if "selectedsliceentityid" in parent_row:
                if parent_row["selectedsliceentityid"] == 0:
                    slice = get_first_active_slice(db)
                else:
                    slice = cloud_utils.lower_key(
                        db.get_row_dict("tblEntities", {"id": parent_row["selectedsliceentityid"]},
                                        order="ORDER BY id LIMIT 1"))
                if slice:
                    net = db.execute_db("SELECT * FROM tblEntities JOIN tblAttachedNetworkEntities "
                                        " WHERE  (  "
                                        " tblEntities.EntityType = 'slice_attached_network' AND tblEntities.deleted=0 AND "
                                        " tblAttachedNetworkEntities.NetworkType = 'external' AND "
                                        " tblAttachedNetworkEntities.tblEntities = tblEntities.id AND tblEntities.ParentEntityId = '%s')"
                                        " ORDER BY tblEntities.id LIMIT 1" % slice["id"])
                    if net and isinstance(net, (list, tuple)):
                        net = cloud_utils.lower_key(net[0])

        if net:
            attach_request = {
                "attached_entities": [{"entitytype": net["entitytype"], "entities": [{"attachedentityid": net["id"]}]}]}
            remove_and_add_attached_entities(db, dbid, attach_request, mode)
            # cloud_utils.update_or_insert(db, "tblServices", {"SharedExternalNetworkEntityId": net["id"]}, {"tblEntities": dbid})

    except:
        cloud_utils.log_exception(sys.exc_info())


def _externalnetwork(db, dbid, row, keys, **kwargs):
    j = _entity(db, dbid, row, entity_keys)
    #    j.update(_network_services_common(db, dbid, row))
    net_row = cloud_utils.lower_key(
        db.get_row_dict("tblAttachedEntities", {"tblEntities": dbid}, order="ORDER BY id LIMIT 1"))
    if net_row:
        j.update({"params": {"external_network": _get_entity_name(db, net_row["attachedentityid"], default="none")}})
    j.update(_network_services_interfaces(db, dbid, row))
    return j, None


entities = {
    "slice": Entity("tblSlices", None, None, None, "home", None,
                    None, None, default_entity_name_prefix="Slice-"),

    "system": Entity(None, None, None, None, "home", None,
                     None, None, default_entity_name_prefix="System-"),

    "slice_attached_network": Entity("tblAttachedNetworkEntities", _slice_attached_network_post_db_create,
                                     None, None, "home", "SliceAttachedNetwork",
                                     slice_attached_network_keys, _slice_attached_network),

    "slice_compute_entity": Entity("tblComputeEntities", _cfa_post_db_create, None,
                                   post_rest_get_function_slice_entities, "home", "Host", None, _slice_physical_json),
    "slice_storage_entity": Entity("tblStorageEntities", None, None, post_rest_get_function_slice_entities, "home",
                                   "Stor", None, _slice_physical_json),
    "slice_network_entity": Entity("tblNetworkEntities", None, None, post_rest_get_function_slice_entities, "home",
                                   "NetworkDevice", None, _slice_physical_json),
    "slice_ipsecvpn_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                     _slice_physical_json),
    "slice_fws_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),
    "slice_sslaccelerator_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                           _slice_physical_json),
    "slice_nat_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),
    "slice_lbs_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),
    "slice_ips_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),
    "slice_wan_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),
    "slice_rts_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),
    "slice_nms_service": Entity("tblNetworkEntities", None, None, None, "home", "NetworkDevice", None,
                                _slice_physical_json),

    "user_group": Entity(None, _group_post_db_create, _group_pre_delete,
                         None, None, None, None, None,
                         default_entity_name_prefix="UserGroup-",
                         pre_rest_status_check_function=_rest_disabled
                         ),

    "user": Entity("tblUsers", _user_post_db_create, _user_pre_delete,
                   None, None, None, None, None,
                   pre_db_create_function=_user_pre_db_create,
                   pre_rest_status_check_function=_rest_disabled
                   ),

    "widget": Entity("tblWidgets", None, None, None, "home", None,
                     None, None, default_entity_name_prefix="Widget-",
                     pre_rest_status_check_function=_rest_disabled),

    "template": Entity("tblVDCTemplates", None, None, None, "home", None,
                       None, None, default_entity_name_prefix="Template-",
                       pre_rest_status_check_function=_rest_disabled),

    "imagelibrary": Entity("tblImageLibrary", None, None, None, "home", "ImageLibrary",
                           image_library_keys, _image_library, default_entity_name_prefix="ImageLibrary-"),

    "image": Entity("tblLibraryImages", _image_post_db_create, None, post_rest_get_function_image, "home", "Image",
                    image_keys, _image, default_entity_name_prefix="Image-"),

    "organization": Entity("tblOrganizations", None, None, None, "home", "Organization",
                           organization_keys, _organization, default_entity_name_prefix="Organization-"),

    "department": Entity("tblDepartments", None, None, None, "home", "Department",
                         department_keys, _department, default_entity_name_prefix="Department-"),

    "vdc": Entity("tblVdcs", None, None, None, "home", "Vdc",
                  vdc_keys, _vdc, post_entity_final_status_function=vdc_post_final_status_function,
                  validate_entity_function=validate_entity.validate_vdc,
                  provision_entity_function=provision_entity.provision_vdc, default_entity_name_prefix="Vdc-"
                  ),

    "container": Entity("tblContainers", None, None, None, "storage", "Container",
                        container_keys, _container, default_entity_name_prefix="Container-"),

    "volume": Entity("tblContainerVolumes", None, None, post_rest_get_function_volume, "home", "Volume",
                     volume_keys, _volume, default_entity_name_prefix="Volume-",
                     post_entity_final_status_function=volume_post_final_status_function,
                     pre_db_create_function=_volume_pre_db_create),

    "snapshot": Entity("tblContainerVolumes", None, None, post_rest_get_function_volume, "home", "Volume",
                       volume_keys, _volume, ),

    "archive": Entity("tblContainerVolumes", None, None, post_rest_get_function_volume, "home", "Volume",
                      volume_keys, _volume, ),

    "backup": Entity("tblContainerVolumes", None, None, post_rest_get_function_volume, "home", "Volume",
                     volume_keys, _volume, ),

    "virtual_network": Entity("tblVirtualNetworks", _virtual_networks_post_db_create, _virtual_networks_pre_db_delete,
                              None, "home",
                              "VirtualNetwork",
                              virtual_networks_keys, _virtual_networks, default_entity_name_prefix="VirtualNetwork-"),

    "disk": Entity("tblDisks", None, None, None, "storage", "Disk",
                   disk_keys, _disk, default_entity_name_prefix="Disk-"),

    "partition": Entity("tblDiskPartitions", None, None, None, "home", "Partition",
                        partition_keys, _partition, default_entity_name_prefix="Partition-"),

    "bucket": Entity("tblBuckets", None, None, None, "storage", "Bucket",
                     bucket_keys, _bucket, default_entity_name_prefix="Bucket-"),

    "object": Entity("tblBucketObjects", None, None, None, "home", "BucketObject",
                     object_keys, _object, default_entity_name_prefix="Object-"),

    "serverfarm": Entity("tblServerFarms", _serverfarm_post_db_create, None, None, "compute", "ServerFarm",
                         serverfarm_keys, _serverfarm,
                         default_entity_name_prefix="Cluster-",
                         pre_rest_status_check_function=_check_profile_parent_status,
                         # statistics_manager=entity_resync.compute_statisics_manager
                         ),

    "server": Entity("tblServers", _server_post_db_create, None, None, "home", "Server",
                     server_keys, _server,
                     default_entity_name_prefix="Server-",
                     pre_db_create_function=_server_pre_db_create,
                     pre_rest_status_check_function=_check_profile_parent_status,
                     statistics_manager=entity_resync.compute_statisics_manager),

    "security_group": Entity(None, None, None, None, "network", "SecurityGroup",
                             security_group_keys, _security_group,
                             pre_rest_status_check_function=_check_profile_parent_status,
                             default_entity_name_prefix="SecurityGroup-"),

    "security_rule": Entity("tblSecurityRules", None, None, None, "home", "SecurityRule",
                            security_rule_keys, _security_rule,
                            pre_rest_status_check_function=_check_profile_parent_status,
                            default_entity_name_prefix="SecurityRule-"),

    "lbs_group": Entity(None, None, None, None, "network", "LbsGroup",
                        lbs_group_keys, _lbs_group,
                        pre_rest_status_check_function=_check_profile_parent_status,
                        default_entity_name_prefix="LoadBalancerGroup-"),

    "lbs_service": Entity("tblLBSServices", None, None, None, "home", "LbsService",
                          lbs_service_keys, _lbs_service,
                          pre_rest_status_check_function=_check_profile_parent_status,
                          default_entity_name_prefix="LBSService-"),

    "acl_group": Entity(None, None, None, None, "network", "AccessGroup",
                        acl_group_keys, _acl_group,
                        pre_rest_status_check_function=_check_profile_parent_status,
                        default_entity_name_prefix="ACLGroup-"),

    "acl_rule": Entity("tblACLRules", None, None, None, "home", "AccessRule",
                       acl_rule_keys, _acl_rule,
                       pre_rest_status_check_function=_check_profile_parent_status,
                       default_entity_name_prefix="ACLRule-"),

    "vpn_group": Entity(None, None, None, None, "network", "VpnGroup",
                        vpn_group_keys, _vpn_group,
                        pre_rest_status_check_function=_check_profile_parent_status,
                        default_entity_name_prefix="VPNGroup-"),

    "vpn_connection": Entity("tblVPNConnections", None, None, None, "home", "VpnConnection",
                             vpn_connection_keys,
                             _vpn_connection,
                             pre_rest_status_check_function=_check_profile_parent_status,
                             default_entity_name_prefix="VPNSession-"),

    "switch_network_service": Entity("tblServices", _network_service_post_db_create,
                                     _network_service_pre_db_delete, None, "home", "Subnet", switch_keys,
                                     _switch,
                                     validate_entity_function=validate_entity.validate_switch,
                                     pre_rest_status_check_function=_check_vdc_status,
                                     pre_db_create_function=_service_pre_db_create,
                                     default_entity_name_prefix="Switch-",
                                     statistics_manager=entity_resync.network_service_statisics_manager),

    "nat_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_nat, "home", "Nat",
                                  nat_keys, _nat,
                                  validate_entity_function=validate_entity.validate_nat,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,
                                  default_entity_name_prefix="Nat-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "lbs_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_lbs, "home",
                                  "Loadbalancer", lbs_keys, _lbs,
                                  validate_entity_function=validate_entity.validate_lbs,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,
                                  default_entity_name_prefix="LoadBalancer-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "rts_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_rts, "home", "Router",
                                  rts_keys, _rts,
                                  validate_entity_function=validate_entity.validate_rts,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,
                                  default_entity_name_prefix="Router-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "ipsecvpn_network_service": Entity("tblServices", _network_service_post_db_create,
                                       _network_service_pre_db_delete, _post_rest_get_function_vpn, "home", "Vpn",
                                       vpn_keys, _vpn,
                                       validate_entity_function=validate_entity.validate_vpn,
                                       pre_rest_status_check_function=_check_vdc_status,
                                       pre_db_create_function=_service_pre_db_create,
                                       default_entity_name_prefix="Vpn-",
                                       statistics_manager=entity_resync.network_service_statisics_manager),

    "sslvpn_network_service": Entity("tblServices", _network_service_post_db_create,
                                     _network_service_pre_db_delete, _post_rest_get_function_vpn, "home", "Vpn",
                                     vpn_keys, _vpn,
                                     validate_entity_function=validate_entity.validate_vpn,
                                     pre_rest_status_check_function=_check_vdc_status,
                                     pre_db_create_function=_service_pre_db_create,
                                     default_entity_name_prefix="Ssl-",
                                     statistics_manager=entity_resync.network_service_statisics_manager),

    "fws_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_fws, "home",
                                  "Firewall", fws_keys, _fws,
                                  validate_entity_function=validate_entity.validate_fws,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,
                                  default_entity_name_prefix="Firewall-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "amazon_network_service": Entity("tblServices", _network_service_post_db_create,
                                     _network_service_pre_db_delete, _post_rest_get_function_rts, "home", "Router",
                                     rts_keys, _rts,
                                     validate_entity_function=validate_entity.validate_rts,
                                     pre_rest_status_check_function=_check_vdc_status,
                                     pre_db_create_function=_service_pre_db_create,
                                     default_entity_name_prefix="Aws-",
                                     statistics_manager=entity_resync.network_service_statisics_manager),

    "rackspace_network_service": Entity("tblServices", _network_service_post_db_create,
                                        _network_service_pre_db_delete, _post_rest_get_function_rts, "home", "Router",
                                        rts_keys, _rts,
                                        validate_entity_function=validate_entity.validate_rts,
                                        pre_rest_status_check_function=_check_vdc_status,
                                        pre_db_create_function=_service_pre_db_create,
                                        default_entity_name_prefix="Rks-",
                                        statistics_manager=entity_resync.network_service_statisics_manager),

    "sslaccelerator_network_service": Entity("tblServices", _network_service_post_db_create,
                                             _network_service_pre_db_delete, _post_rest_get_function_rts, "home",
                                             "Router",
                                             rts_keys, _rts,
                                             validate_entity_function=validate_entity.validate_rts,
                                             pre_rest_status_check_function=_check_vdc_status,
                                             pre_db_create_function=_service_pre_db_create,
                                             default_entity_name_prefix="Assl-",
                                             statistics_manager=entity_resync.network_service_statisics_manager),

    "wan_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_rts, "home", "Router",
                                  rts_keys, _rts,
                                  validate_entity_function=validate_entity.validate_rts,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,
                                  default_entity_name_prefix="Wan-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "thirdparty_network_service": Entity("tblServices", _network_service_post_db_create,
                                         _network_service_pre_db_delete, _post_rest_get_function_rts, "home", "Router",
                                         rts_keys, _rts,
                                         validate_entity_function=validate_entity.validate_rts,
                                         pre_rest_status_check_function=_check_vdc_status,
                                         pre_db_create_function=_service_pre_db_create,
                                         default_entity_name_prefix="Tpy-",
                                         statistics_manager=entity_resync.network_service_statisics_manager),

    "cloudservice_network_service": Entity("tblServices", _network_service_post_db_create,
                                           _network_service_pre_db_delete, _post_rest_get_function_rts, "home",
                                           "Router",
                                           rts_keys, _rts,
                                           validate_entity_function=validate_entity.validate_rts,
                                           pre_rest_status_check_function=_check_vdc_status,
                                           pre_db_create_function=_service_pre_db_create,
                                           default_entity_name_prefix="Cls-",
                                           statistics_manager=entity_resync.network_service_statisics_manager),

    "compute_network_service": Entity("tblServices", _network_service_post_db_create,
                                      _network_service_pre_db_delete, _post_rest_get_function_compute, "home",
                                      "ComputeService", compute_keys, _compute,
                                      validate_entity_function=validate_entity.validate_compute,
                                      pre_rest_status_check_function=_check_vdc_status,
                                      pre_db_create_function=_service_pre_db_create,
                                      default_entity_name_prefix="Compute-",
                                      # statistics_manager=entity_resync.compute_statisics_manager
                                      ),

    "storage_network_service": Entity("tblServices", _network_service_post_db_create,
                                      _network_service_pre_db_delete, _post_rest_get_function_storage, "home",
                                      "StorageService", storage_keys, _storage,
                                      validate_entity_function=validate_entity.validate_storage,
                                      pre_rest_status_check_function=_check_vdc_status,
                                      pre_db_create_function=_service_pre_db_create,
                                      default_entity_name_prefix="Storage-",
                                      statistics_manager=entity_resync.network_service_statisics_manager),

    "nms_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_nms, "home",
                                  "NetworkMonitor", nms_keys, _nms,

                                  validate_entity_function=validate_entity.validate_nms,
                                  provision_entity_function=provision_entity.provision_service,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,

                                  default_entity_name_prefix="Monitor-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "ips_network_service": Entity("tblServices", _network_service_post_db_create,
                                  _network_service_pre_db_delete, _post_rest_get_function_ips, "home", "Ips",
                                  ips_keys, _ips,
                                  validate_entity_function=validate_entity.validate_ips,
                                  pre_rest_status_check_function=_check_vdc_status,
                                  pre_db_create_function=_service_pre_db_create,
                                  default_entity_name_prefix="Ips-",
                                  statistics_manager=entity_resync.network_service_statisics_manager),

    "externalnetwork": Entity("tblServices",
                              _externalnetwork_post_db_create,
                              _ext_network_service_pre_db_delete,
                              None,
                              "home",
                              "ExternalNetwork",
                              externalnetwork_keys,
                              _externalnetwork,
                              validate_entity_function=validate_entity.validate_externalnetwork,
                              pre_rest_status_check_function=_check_vdc_status,
                              pre_db_create_function=_service_pre_db_create,
                              default_entity_name_prefix="ExternalNetwork-"),

    "network_interface": Entity("tblServicesInterfaces", _interface_post_db_create, _interface_pre_db_delete,
                                None, None, "Interface",
                                None, None, pre_db_create_function=_interface_pre_db_create,
                                post_db_delete_function=_interface_post_db_delete,
                                default_entity_name_prefix="Interface-"),

    "service_port": Entity("tblServicePorts",
                           _port_post_db_create,
                           None,
                           None,
                           "home",
                           None,
                           None,
                           _service_port,
                           default_entity_name_prefix="Port-",
                           statistics_manager=entity_resync.port_statisics_manager),

    "tap_network_service": Entity("tblServices", _tap_service_post_db_create,
                                  _tap_network_service_pre_db_delete, None, None, None,
                                  None, None,
                                  pre_db_create_function=_tap_service_pre_db_create,
                                  default_entity_name_prefix="Tap-"),
    "storage_class": Entity("tblStorageClasses", None, None, None, "home", "Class",
                            _class_keys, _class, default_entity_name_prefix="StorageClass-",
                            pre_rest_status_check_function=_rest_disabled,
                            post_db_delete_function=_storage_class_post_db_delete, ),
    "compute_class": Entity("tblComputeClasses", None, None, None, "home", "Class",
                            _class_keys, _class, default_entity_name_prefix="ComputeClass-",
                            pre_rest_status_check_function=_rest_disabled,
                            post_db_delete_function=_compute_class_post_db_delete, ),

    "network_class": Entity("tblNetworkClasses", None, None, None, "home", "Class",
                            _class_keys, _class, default_entity_name_prefix="NetworkClass-",
                            pre_rest_status_check_function=_rest_disabled
                            ),
}

'''
def get_next_service(db, dbid):
    try:
        for entitytype in topology_network_services:
            if entitytype in entities:
                for service in cloud_utils.entity_children(db, dbid, entitytype, entities[entitytype].child_table):
                    yield service

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())
'''
'''
def get_next_interface(db, dbid):
    try:
        for entitytype in topology_network_services:
            if entitytype in entities:
                for service in cloud_utils.entity_children(db, dbid, entitytype, entities[entitytype].child_table):
                    yield service

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())
'''
'''
def get_next_group(db, dbid):
    try:
        for profile in profile_groups_provision_order:
            if profile["group"] in entities:
                for group in cloud_utils.entity_members(db, dbid, profile["group"], child_table= entities[profile["group"]].child_table):
                    yield group
                    if profile["child"] and profile["child"] in entities:
                        for child in cloud_utils.entity_members(db, group["id"], profile["child"] , child_table= entities[profile["child"] ].child_table):
                            yield child

    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())
'''
