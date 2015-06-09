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
import string

import ujson

import jsonpickle
import jsonpickle.handlers
# import  jsonpickle.backend

import datetime

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

from utils.underscore import _

import entity_functions

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
# import rest.rest_api as rest_api
import entity_utils
import entity_manager
import provision_entity
import entity_constants
# import cfd_keystone.cfd_keystone as cfd_keystone


class DatetimeHandler(jsonpickle.handlers.BaseHandler):
    def flatten(self, obj, data):
        return obj.strftime('%Y-%m-%d %H:%M:%S')


class TimeHandler(jsonpickle.handlers.BaseHandler):
    def flatten(self, obj, data):
        minutes, seconds = divmod(obj.seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return '{:02d}:{:02d}:{:02d}'.format(hours, minutes, seconds)


jsonpickle.load_backend('ujson', 'dumps', 'loads', ValueError)
jsonpickle.set_preferred_backend('ujson')
jsonpickle.handlers.registry.register(datetime.datetime, DatetimeHandler)
jsonpickle.handlers.registry.register(datetime.timedelta, TimeHandler)
# jpicke = jsonpickle.backend.JSONBackend()
# jpicke.enable_fallthrough(enable=False)





keys_2b_removed = ["id", "child_id", "tblentities", "created_at", "updated_at", "deleted_at",
                   "deleted", "entitystatus", "uniqueid", "uri", "parententityid",
                   "clonedfromentityid", "entitymode",
                   "fault_code", " novnc_url", "fault_message", "vm_state", "server_status", "fault_details",
                   "defaultgateways"
                   ]

keys_2b_converted = {"defaultsliceentityid": "slice", "selectedsliceentityid": "slice",
                     "arcontainerentityid": "container", "bkcontainerentityid": "container",
                     "defaultgatewayentityid": "network_service", "destinationserviceentityid": "network_service",
                     "serviceinterfaceentityid": "network_interface", "beginserviceentityid": "network_service",
                     "endserviceentityid": "network_service", "endserviceportid": "service_port",
                     "beginserviceportid": "service_port", "attachedentityid": "any"}

'''
keys_2b_converted = { "defaultsliceentityid":"slice", "selectedsliceentityid":"slice",
                     "arcontainerentityid":"container", "bkcontainerentityid":"container", "bootserverentityid":"server",
                     "bootimageentityid":"image","bootvolumeentityid":"volume","vpntunnelentityid":"vpnconnection",
                     "defaultgatewayentityid":"network_service", "destinationserviceentityid":"network_service",
                     "serviceinterfaceentityid":"network_interface","beginserviceentityid" :"network_service",
                     "endserviceentityid":"network_service","endserviceportid" :"service_port",
                     "beginserviceportid" :"service_port", "attachedentityid":"any"}
'''


def cleanse_row(db, entity):
    if not entity:
        return
    try:
        for k, v in entity.items():
            if k == "iqn":
                pass
            if isinstance(v, type(None)):
                if not entity[k]:
                    del entity[k]
                continue
            if k in keys_2b_removed:
                del entity[k]
            if k in keys_2b_converted.keys():
                del entity[k]
                if k.endswith("id") and isinstance(v, (int, long)):
                    if v == 0:
                        entity[k] = 0
                        continue
                    nk = k[:-2]  # strip id
                    nk += "name"  # append name
                    ne = cloud_utils.lower_key(db.get_row("tblEntities", "id='%s' AND deleted = 0" % v,
                                                          order="ORDER BY id LIMIT 1"))
                    if ne:
                        np = cloud_utils.lower_key(
                            db.get_row("tblEntities", "id='%s' AND deleted = 0" % ne["parententityid"],
                                       order="ORDER BY id LIMIT 1"))
                        if not np:
                            np = {}
                        if keys_2b_converted[k] == "any" or keys_2b_converted[k] == ne["entitytype"] or \
                                        keys_2b_converted[k] == ne["entitysubtype"]:
                            entity[nk] = {"entityname": ne["name"],
                                          "entitytype": ne["entitytype"],
                                          "parententitytype": np.get("entitytype", "Unknown"),
                                          "parententityname": np.get("name", "Unknown")}
                            if ne["entitysubtype"]:
                                entity[nk]["entitysubtype"] = ne["entitysubtype"]

                            if "uuid" in ne:
                                entity[nk]["uuid"] = ne["uuid"]
                        else:
                            entity[k] = 0
                            LOG.info(_("entity name %s with id %s has invalid entitytype value %s for key %s" % (
                                entity.get("name", "unknown"),
                                entity.get("id", 0), v, k)))
                    else:
                        entity[k] = 0
                        LOG.info(_("entity name %s with id %s with value %s for key %s  is not found in db" % (
                            entity.get("name", "unknown"),
                            entity.get("id", 0), v, k)))
        return entity
    except:
        cloud_utils.log_exception(sys.exc_info())


def cleanse_entity(db, entity):
    if not entity:
        return
    try:
        dbid = entity["id"]
        new_entity = cleanse_row(db, entity)

        attaches = []
        for attach in entity_utils.get_next_entity_attached(db, dbid):
            attaches.append(cleanse_row(db, attach))

        if len(attaches) > 0:
            new_entity["attachments"] = attaches

        user_data = db.get_row_dict("tblUserData", {"tblEntities": dbid}, order="ORDER BY id LIMIT 1")
        if user_data and user_data["User_Data"]:
            new_entity["user_data"] = user_data["User_Data"]

        metadata = entity_utils.json_metadata_keyvalue(db, dbid)
        if metadata:
            new_entity["metadata"] = metadata

        ssh_keys = entity_utils.get_dbid_keys(db, dbid)
        if ssh_keys:
            new_entity["ssh_keys"] = ssh_keys

        return new_entity
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_child_entities_list(db, dbid, child_type):
    try:
        items = []
        for item in cloud_utils.entity_members(db, dbid, child_type,
                                               child_table=entity_manager.entities[child_type].child_table):
            entity = cleanse_entity(db, item)
            if entity:

                items.append(entity)
            else:
                pass
        return items
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_group_entities_list(db, dbid, group_type):
    try:
        groups = []
        child_type = entity_constants.profile_group_child[group_type]
        for group in cloud_utils.entity_members(db, dbid, group_type,
                                                child_table=entity_manager.entities[group_type].child_table):
            group[child_type] = get_child_entities_list(db, group["id"], child_type)
            groups.append(cleanse_entity(db, group))
        return groups
    except:
        cloud_utils.log_exception(sys.exc_info())


def get_named_entity(db, name, type):
    try:
        current_index = db.execute_db("SELECT MAX(id) FROM tblEntities")[0]["MAX(id)"] + 1
        while True:
            entity = cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' "
                                                                     " AND deleted = 0 AND id < '%s' " % (
                                                          name, type, current_index), order="ORDER BY id DESC LIMIT 1"))
            if entity:
                yield entity
                current_index = entity['id']
            else:
                break
    except GeneratorExit:
        LOG.info(_("Ignoring Generator Error for name: %s type:  %s" % (name, type)))
    except:
        cloud_utils.log_exception(sys.exc_info())


un_postfixed_entitytypes = ["slice", "image", "imagelibrary", "virtual_network", "slice_attached_network"]


def find_named_entity(db, attach, root_dbid, root_type, name_postfix, entities):
    entityname = attach.get("entityname", "Unknown")
    entitytype = attach.get("entitytype", "Unknown")
    entitysubtype = attach.get("entitysubtype", "Unknown")
    parententityname = attach.get("parententityname", "Unknown")
    parententitytype = attach.get("parententitytype", "Unknown")

    if name_postfix and entitytype not in un_postfixed_entitytypes:
        entityname += name_postfix
        parententityname += name_postfix

    parententity = entity = None

    top_entity_id = root_dbid

    # profile groups, get using parent entity id
    if entitytype in entity_constants.profile_group_child.keys():
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, top_entity_id),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitytype in entity_constants.profile_child_group.keys():
        if not parententityname or not parententitytype:
            return None
        # for images, read the parent department imaage library and images
        if entitytype == "image" and root_type == "vdc":
            vdc_row = entity_utils.read_partial_entity(db, top_entity_id)
            if not vdc_row: return None
            top_entity_id = vdc_row["parententityid"]

        parententity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (parententityname, parententitytype, top_entity_id),
                       order="ORDER BY id DESC LIMIT 1"))
        if not parententity:
            return
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, parententity["id"]),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitysubtype == "network_service" or entitytype == "network_interface":
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, top_entity_id),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitytype == "service_port":
        parententity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid='%s' "
                                      " AND deleted = 0 " % (parententityname, parententitytype, top_entity_id),
                       order="ORDER BY id DESC LIMIT 1"))
        if not parententity:
            return None
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, parententity["id"]),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitytype == "virtual_network":
        vdc_row = entity_utils.read_partial_entity(db, top_entity_id)
        if not vdc_row: return None
        top_entity_id = vdc_row["parententityid"]
        if parententitytype == "organization":
            dept_row = entity_utils.read_partial_entity(db, top_entity_id)
            if not dept_row: return None
            top_entity_id = dept_row["parententityid"]
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, top_entity_id),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitytype == "slice":
        entity = cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' "
                                                                 " AND deleted = 0 " % (entityname, entitytype),
                                                  order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitytype == "slice_attached_network":
        parententity = cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' "
                                                                       " AND deleted = 0 " % (
                                                            parententityname, parententitytype),
                                                        order="ORDER BY id DESC LIMIT 1"))
        if not parententity:
            return
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, parententity["id"]),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    for entity in get_named_entity(db, entityname, entitytype):
        if entity["entitytype"] == "slice":
            return entity
        if root_dbid == entity["parententityid"]:
            return entity
        id = entity["parententityid"]
        while True:
            parent = cloud_utils.lower_key(
                db.get_row("tblEntities", "id = '%s' AND deleted = 0" % id, order="ORDER BY id DESC LIMIT 1"))
            if not parent:
                break
            if root_dbid == parent["parententityid"]:
                return entity
            if parent["entitytype"] == root_type:
                break
            id = parent["parententityid"]
            if id == 0:
                break
    return None


def serach_for_image(db, dbid, entityname, entitytype, parententityname, parententitytype):
    parententity = cloud_utils.lower_key(
        db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                  " AND deleted = 0 " % (parententityname, parententitytype, dbid),
                   order="ORDER BY id DESC LIMIT 1"))
    if not parententity:
        dept_row = entity_utils.read_partial_entity(db, dbid)
        parententity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (
                           parententityname, parententitytype, dept_row['parententityid']),
                       order="ORDER BY id DESC LIMIT 1"))
        if not parententity:
            slice = cloud_utils.lower_key(db.get_row("tblEntities", " entitytype='slice' "
                                                                    " AND deleted = 0 ",
                                                     order="ORDER BY id DESC LIMIT 1"))
            parententity = cloud_utils.lower_key(
                db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                          " AND deleted = 0 " % (parententityname, parententitytype, slice['id']),
                           order="ORDER BY id DESC LIMIT 1"))
            if not parententity:
                return

    return cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                                           " AND deleted = 0 " % (
                                                entityname, entitytype, parententity["id"]),
                                            order="ORDER BY id DESC LIMIT 1"))


def find_named_entity_id(db, attach, root_dbid, root_type, name_postfix, entities):
    entityname = attach.get("entityname", "Unknown")
    entitytype = attach.get("entitytype", "Unknown")
    entitysubtype = attach.get("entitysubtype", "Unknown")
    parententityname = attach.get("parententityname", "Unknown")
    parententitytype = attach.get("parententitytype", "Unknown")

    #    if name_postfix and entitytype not in un_postfixed_entitytypes:
    #        entityname += name_postfix
    #        parententityname += name_postfix

    top_entity_id = root_dbid

    # profile groups, get using parent entity id
    if entitytype in entity_constants.profile_group_child.keys():
        return search_entities(entities, entityname, entitytype, top_entity_id, name_postfix)

    elif entitytype in entity_constants.profile_child_group.keys():
        if not parententityname or not parententitytype:
            return None
        # for images, read the parent department imaage library and images
        if entitytype == "image":
            if root_type == "vdc":
                vdc_row = entity_utils.read_partial_entity(db, top_entity_id)
                if not vdc_row: return None
                top_entity_id = vdc_row["parententityid"]
                return serach_for_image(db, top_entity_id, entityname, entitytype, parententityname, parententitytype)

        parententity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (parententityname, parententitytype, top_entity_id),
                       order="ORDER BY id DESC LIMIT 1"))
        if not parententity:
            return
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                      " AND deleted = 0 " % (entityname, entitytype, parententity["id"]),
                       order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitysubtype == "network_service" or entitytype == "network_interface":
        return search_entities(entities, entityname, entitytype, top_entity_id, name_postfix)

    elif entitytype == "service_port":
        et = search_entities(entities, parententityname, parententitytype, top_entity_id, name_postfix)
        if not et:
            return None
        return search_entities(entities, entityname, entitytype, et["id"], name_postfix)

    elif entitytype == "virtual_network":
        vdc_row = entity_utils.read_partial_entity(db, top_entity_id)
        if not vdc_row: return None
        top_entity_id = vdc_row["parententityid"]
        if parententitytype == "organization":
            dept_row = entity_utils.read_partial_entity(db, top_entity_id)
            if not dept_row: return None
            top_entity_id = dept_row["parententityid"]
        entity = db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                           " AND deleted = 0 " % (entityname, entitytype, top_entity_id),
                            order="ORDER BY id DESC LIMIT 1")
        return entity

    elif entitytype == "slice":
        entity = cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' "
                                                                 " AND deleted = 0 " % (entityname, entitytype),
                                                  order="ORDER BY id DESC LIMIT 1"))
        return entity

    elif entitytype == "slice_attached_network":
        parententity = cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' "
                                                                       " AND deleted = 0 " % (
                                                            parententityname, parententitytype),
                                                        order="ORDER BY id DESC LIMIT 1"))
        if not parententity:
            parententity = cloud_utils.lower_key(db.get_row("tblEntities", " entitytype='slice' "
                                                                           " AND deleted = 0 ",
                                                            order="ORDER BY id DESC LIMIT 1"))
            if not parententity:
                return

        entity = db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
                                           " AND deleted = 0 " % (entityname, entitytype, parententity["id"]),
                            order="ORDER BY id DESC LIMIT 1")
        return entity

    LOG.critical(_("Unable to locate attach:%s current entities:%s" % (attach, entities)))
    return None


def convert_name_2_id(db, entity, column, root_dbid, root_type, name_postfix, entities):
    try:
        if column not in entity.keys() or entity[column] == 0:
            column_name = column[:-2]  # strip id
            column_name += "name"  # append name
            if column_name in entity.keys() and isinstance(entity[column_name], dict):
                return find_named_entity_id(db, entity[column_name], root_dbid, root_type, name_postfix, entities)

                #                entity_db = find_named_entity(db,entity[column_name],root_dbid, root_type, name_postfix, entities)
                #                if entity_db and "id" in entity_db:
                #                    return entity_db["id"]
        return 0
    except:
        cloud_utils.log_exception(sys.exc_info())


def uncleanse_entity(db, entity, root_dbid, root_type, name_postfix, entities):
    try:
        cln_entity = {}
        for key, value in entity.items():
            #            if name_postfix and key == "name":
            #                cln_entity[key] = value+name_postfix
            #            else:
            #                cln_entity[key] = value
            cln_entity[key] = value
            if len(key) > 4 and key[-4:] == "name" and key[:-4] + "id" in keys_2b_converted.keys():
                ent = convert_name_2_id(db, entity, key[:-4] + "id", root_dbid, root_type, name_postfix, entities)
                if ent and ent["id"] != 0:
                    del entity[key]
                    entity[key[:-4] + "id"] = ent["id"]
                    del cln_entity[key]
                    cln_entity[key[:-4] + "id"] = ent["id"]
                else:
                    if "entitytype" in entity and entity["entitytype"] != 'service_port':
                        LOG.warn(_("Unable to convert key:%s value:%s" % (key, value)))
                        #                    del cln_entity[key]
                        #                    del entity[key]

        return cln_entity
    except:
        cloud_utils.log_exception(sys.exc_info())


def add_entity(db, parent_dbid, entity, root_dbid, root_type, name_postfix, entities):
    try:
        entity = uncleanse_entity(db, entity, root_dbid, root_type, name_postfix, entities)
        entity["parententityid"] = parent_dbid

        dbid = cloud_utils.update_or_insert(db, "tblEntities", entity, {"name": entity["name"],
                                                                        "entitytype": entity["entitytype"],
                                                                        "deleted": 0,
                                                                        "parententityid": entity["parententityid"]},
                                            child_table=entity_manager.entities[entity["entitytype"]].child_table)

        db.execute_db("DELETE FROM tblAttachedEntities WHERE tblEntities = '%s'" % dbid)

        if "user_data" in entity:
            cloud_utils.update_or_insert(db, "tblUserData", {"tblEntities": dbid, "user_data": entity["user_data"]},
                                         {"tblentities": dbid})

        if "metadata" in entity:
            for meta in entity["metadata"]:
                cloud_utils.insert_db(db, "tblKeyValuePairs", {"tblEntities": dbid,
                                                               "thekey": meta["key"], "thevalue": meta["value"]})
        if "ssh_keys" in entity:
            entity_manager.save_ssh_keys(db, dbid, entity)

        if "attachments" in entity:
            for attach in entity["attachments"]:
                attach = uncleanse_entity(db, attach, root_dbid, root_type, name_postfix, entities)
                attach["tblEntities"] = dbid
                cloud_utils.insert_db(db, "tblAttachedEntities", attach)
        return dbid
    except:
        cloud_utils.log_exception(sys.exc_info())


def search_entities(entities, name, entitytype, parent_dbid, name_postfix):
    if name_postfix and entitytype == "service_port":
        name = update_service_name(entities, name, name_postfix)

    for e in entities:
        if entitytype == e["entitytype"] and parent_dbid == e["parententityid"]:
            if name_postfix:
                if e["name"] == name or e["name"] == name + name_postfix:
                    return e
            else:
                if e["name"] == name:
                    return e

    return None


def update_service_name(entities, name, name_postfix):
    for e in entities:
        if e["entitysubtype"] and e["entitysubtype"] == "network_service":
            if e["name"] == name or e["name"] == name + name_postfix:
                return e["name"]

    LOG.error(_("Service should have been in database: %s" % name))
    return None


def attach_entity(db, parent_dbid, entity, root_dbid, root_type, name_postfix, entities):
    try:
        # network interface and port contain cross links which can only be done after all entities are created.
        if entity["entitytype"] == "network_interface" or entity["entitytype"] == "service_port":
            entity = uncleanse_entity(db, entity, root_dbid, root_type, name_postfix, entities)
            entity["parententityid"] = parent_dbid

            et = search_entities(entities, entity["name"], entity["entitytype"], parent_dbid, name_postfix)
            if not et:
                LOG.error(_("Entity should have been in database:%s" % entity))
                return 0

            dbid = cloud_utils.update_only(db, "tblEntities", entity, {"id": et["id"]},
                                           child_table=entity_manager.entities[entity["entitytype"]].child_table)

        # dbid = cloud_utils.update_only(db, "tblEntities", entity,
        #                    {"name": entity["name"],"entitytype": entity["entitytype"],"deleted": 0,
        #                     "parententityid": entity["parententityid"]},
        #                    child_table=entity_manager.entities[entity["entitytype"]].child_table)
        else:
            #            if name_postfix:
            #                name = entity["name"]+name_postfix
            #            else:
            #                name = entity["name"]
            #            entity_db = cloud_utils.lower_key(db.get_row("tblEntities", "name='%s' AND entitytype='%s' AND parententityid = '%s' "
            #                     " AND deleted = 0 " % (name, entity["entitytype"], parent_dbid), order="ORDER BY id DESC LIMIT 1"))
            #            if not entity_db:
            #                LOG.warn(_("Entity should have been in database:%s" % entity))
            #                return 0
            #            dbid = entity_db["id"]
            et = search_entities(entities, entity["name"], entity["entitytype"], parent_dbid, name_postfix)
            if not et:
                LOG.warn(_("Entity should have been in database:%s" % entity))
                return 0
            dbid = et["id"]

        if "attachments" in entity:
            for attach in entity["attachments"]:
                attach = uncleanse_entity(db, attach, root_dbid, root_type, name_postfix, entities)
                skip_attach = False
                for k, v in attach.iteritems():
                    if isinstance(v, dict):
                        LOG.warn(_("dbid: %s - Skipping attachment - attached entity not in db:%s Entity:%s" % (
                            dbid, attach, entity)))
                        skip_attach = True
                        break
                if skip_attach:
                    continue
                attach["tblEntities"] = dbid
                cloud_utils.insert_db(db, "tblAttachedEntities", attach)
        return dbid
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_entity(db, parent_dbid, entity, root_dbid, root_type, name_postfix, entities, offsetx=0, offsety=0,
                  max_min_dict=None):
    try:
        entity = uncleanse_entity(db, entity, root_dbid, root_type, name_postfix, entities)
        entity["parententityid"] = parent_dbid

        if "positionx" in entity:
            entity["positionx"] = float(entity["positionx"]) + offsetx
            if entity["positionx"] > 3969:
                entity["positionx"] = 3969

        if "positiony" in entity:
            entity["positiony"] = offsety + float(entity["positiony"])
            if entity["positiony"] > 3969:
                entity["positiony"] = 3969

        if max_min_dict is not None:
            if "max_x" in max_min_dict:
                if max_min_dict["max_x"] < entity["positionx"]:
                    max_min_dict["max_x"] = entity["positionx"]
            else:
                max_min_dict["max_x"] = entity["positionx"]

            if "min_x" in max_min_dict:
                if max_min_dict["min_x"] > entity["positionx"]:
                    max_min_dict["min_x"] = entity["positionx"]
            else:
                max_min_dict["min_x"] = entity["positionx"]

            if "max_y" in max_min_dict:
                if max_min_dict["max_y"] < entity["positiony"]:
                    max_min_dict["max_y"] = entity["positiony"]
            else:
                max_min_dict["max_y"] = entity["positiony"]

            if "min_y" in max_min_dict:
                if max_min_dict["min_y"] > entity["positiony"]:
                    max_min_dict["min_y"] = entity["positiony"]
            else:
                max_min_dict["min_y"] = entity["positiony"]

        if duplicate_check(db, entity["name"], entity["entitytype"], entity["parententityid"]):
            if not name_postfix:
                name_postfix = entity_utils.create_postfix(db)
            entity["name"] = entity["name"] + name_postfix

        if name_postfix and entity["entitytype"] == "service_port":
            entity["name"] = update_service_name(entities, entity["name"], name_postfix)

        dbid = cloud_utils.update_or_insert(db, "tblEntities", entity, {"name": entity["name"],
                                                                        "entitytype": entity["entitytype"],
                                                                        "deleted": 0,
                                                                        "parententityid": entity["parententityid"]},
                                            child_table=entity_manager.entities[entity["entitytype"]].child_table)

        entities.append({"name": entity["name"],
                         "entitytype": entity["entitytype"],
                         "id": dbid,
                         "parententityid": entity["parententityid"],
                         "entitysubtype": entity.get("entitysubtype", None)})

        if "user_data" in entity:
            cloud_utils.update_or_insert(db, "tblUserData", {"tblEntities": dbid, "user_data": entity["user_data"]},
                                         {"tblentities": dbid})

        if "metadata" in entity:
            for meta in entity["metadata"]:
                cloud_utils.insert_db(db, "tblKeyValuePairs", {"tblEntities": dbid,
                                                               "thekey": meta["key"], "thevalue": meta["value"]})
        if "ssh_keys" in entity and isinstance(entity["ssh_keys"], list):
            for key in entity["ssh_keys"]:
                if "name" in key and "key" in key:
                    cloud_utils.insert_db(db, "tblSSHPublicKeys",
                                          {"tblEntities": dbid, "name": key["name"], "key": key["key"]})

        db.execute_db("DELETE FROM tblAttachedEntities WHERE tblEntities = '%s' " % dbid)
        return dbid
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_group_entities(db, parent_dbid, groups, entitytype, root_dbid, root_type, name_postfix, entities):
    try:
        for group in groups:
            dbid = create_entity(db, parent_dbid, group, root_dbid, root_type, name_postfix, entities)
            if entity_constants.profile_group_child[entitytype] in group.keys():
                for item in group[entity_constants.profile_group_child[entitytype]]:
                    create_entity(db, dbid, item, root_dbid, root_type, name_postfix, entities)
    except:
        cloud_utils.log_exception(sys.exc_info())


def create_group_entity_attachments(db, parent_dbid, groups, entitytype, root_dbid, root_type, name_postfix, entities):
    try:
        for group in groups:
            dbid = attach_entity(db, parent_dbid, group, root_dbid, root_type, name_postfix, entities)
            if entity_constants.profile_group_child[entitytype] in group.keys():
                for item in group[entity_constants.profile_group_child[entitytype]]:
                    attach_entity(db, dbid, item, root_dbid, root_type, name_postfix, entities)
    except:
        cloud_utils.log_exception(sys.exc_info())


def add_group_entities(db, parent_dbid, groups, entitytype, root_dbid, root_type, name_postfix, entities):
    try:
        for group in groups:
            dbid = add_entity(db, parent_dbid, group, root_dbid, root_type, name_postfix, entities)
            if entity_constants.profile_group_child[entitytype] in group.keys():
                for item in group[entity_constants.profile_group_child[entitytype]]:
                    add_entity(db, dbid, item, root_dbid, root_type, name_postfix, entities)
    except:
        cloud_utils.log_exception(sys.exc_info())


def duplicate_check(db, name, entitytype, parent_dbid):
    return db.get_row("tblEntities", "name = '%s' AND entitytype = '%s' AND parententityid = '%s' "
                                     " AND deleted = 0" % (name, entitytype, parent_dbid), order="ORDER BY id LIMIT 1")


class VDC(object):
    def __init__(self, db, dbid):
        try:
            self.library = []
            self.container = []
            self.bucket = []
            self.disk = []
            self.serverfarm = []
            self.security_group = []
            self.vpn_group = []
            self.acl_group = []
            self.lbs_group = []
            self.vdc = cleanse_entity(db, entity_utils.read_full_entity(db, dbid))
            for profile in entity_constants.profile_group_child.keys():
                statement = "self.%s = get_group_entities_list(db, dbid, '%s')" % (profile, profile)
                exec statement
            self.service = []
            for service in entity_utils.get_next_service(db, dbid):
                ports = []
                for port in entity_utils.get_next_service_port(db, service["id"]):
                    ports.append(cleanse_entity(db, port))

                svc = cleanse_entity(db, service)
                svc["port"] = ports
                self.service.append(svc)

            self.interface = []
            for itc in entity_utils.get_next_vdc_interface(db, dbid):
                vertices = []
                for v in cloud_utils.get_generic(db, "tblInterfaceVertices", "tblEntities", itc["id"]):
                    ver = cleanse_entity(db, v)
                    vertices.append(ver)
                entity = cleanse_entity(db, itc)
                entity["vertices"] = vertices
                self.interface.append(entity)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def update_name(self, db, parent_dbid):
        duplicate = cloud_utils.lower_key(db.get_row("tblEntities", "name = '%s' AND parententityid = '%s'"
                                                                    " AND deleted = 0" % (
                                                         self.vdc["name"], parent_dbid), order="ORDER BY id LIMIT 1"))
        if duplicate:
            self.vdc["name"] += "-" + entity_utils.create_entity_name(db, None)

    def clone(self, db, parent_dbid, name=None, description=None):
        try:
            if name:
                self.vdc["name"] = name
            else:
                self.vdc["name"] += "-clone" + entity_utils.create_entity_name(db, None)
            self.update_name(db, parent_dbid)
            if description:
                self.vdc["description"] = description
            # parent_dbid = convert_name_2_id(db, self.vdc, "parententityid", )
            if parent_dbid != 0:
                return self.restore(db, parent_dbid)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def restore(self, db, parent_dbid, name=None, vdcid=None, options=None, name_postfix=None, offsetx=0, offsety=0,
                max_min_dict=None):
        try:
            if not name_postfix:
                name_postfix = entity_utils.create_postfix(db)

            if not vdcid:
                if name:
                    self.vdc["name"] = name
                    self.update_name(db, parent_dbid)
                parent = entity_utils.read_partial_entity(db, parent_dbid)
                if not parent or parent["entitytype"] != "department":
                    return 0
                self.vdc["parententityid"] = parent["id"]
                eve = entity_functions.VDCFunctions(db, 0)
                response = eve.do(db, "create", options=self.vdc)
                if isinstance(response, basestring):
                    response = ujson.loads(response)
                if isinstance(response, dict) and "dbid" in response and (
                                response["dbid"] != 0 and response["dbid"] != -1):
                    dbid = response["dbid"]
                else:
                    LOG.critical(_("Unable to locate the vdc with:  %s" % self.vdc))
                    return 0
                    #                dbid = add_entity(db, parent_dbid, self.vdc, parent_dbid, "department", name_postfix)
            else:
                dbid = vdcid
                if options and "name" in options and options["name"] != self.vdc["name"]:
                    self.vdc["name"] = options["name"]
                    self.update_name(db, parent_dbid)
                    eve = entity_functions.VDCFunctions(db, dbid)
                    eve.do(db, "update", options={"name": self.vdc["name"]})

            entities = []
            for profile in entity_constants.profile_group_child.keys():
                statement = "create_group_entities(db, dbid, self.%s, '%s', dbid, 'vdc', name_postfix, entities)" % (
                    profile, profile)
                exec statement

            # for profile in entity_constants.profile_group_child.keys():
            #                statement = "create_group_entity_attachments(db, dbid, self.%s, '%s', dbid, 'vdc', name_postfix, entities)" % (profile,profile)
            #                exec statement

            # must be done twice to first create entities and then to establish cross-links with port and interface ids.

            for svc in self.service:
                svcid = create_entity(db, dbid, svc, dbid, "vdc", name_postfix, entities, offsetx=offsetx,
                                      offsety=offsety, max_min_dict=max_min_dict)

            for svc in self.service:
                ent = search_entities(entities, svc["name"], svc["entitytype"], dbid, name_postfix)
                if not ent:
                    LOG.error(_("Service should have been in database: %s" % svc))
                    return 0
                if "port" in svc:
                    for p in svc["port"]:
                        create_entity(db, ent["id"], p, dbid, "vdc", name_postfix, entities)

            for itc in self.interface:
                itcid = create_entity(db, dbid, itc, dbid, "vdc", name_postfix, entities)
                if "vertices" in itc:
                    for v in itc["vertices"]:
                        v["tblEntities"] = itcid
                        if "positionx" in v:
                            v["positionx"] = float(v["positionx"]) + offsetx
                        if "positiony" in v:
                            v["positiony"] = float(v["positiony"]) + offsety
                        cloud_utils.insert_db(db, "tblInterfaceVertices", v)

            for profile in entity_constants.profile_group_child.keys():
                statement = "create_group_entity_attachments(db, dbid, self.%s, '%s', dbid, 'vdc', name_postfix, entities)" % (
                    profile, profile)
                exec statement

            for svc in self.service:
                svcid = attach_entity(db, dbid, svc, dbid, "vdc", name_postfix, entities)
                if "port" in svc:
                    for p in svc["port"]:
                        attach_entity(db, svcid, p, dbid, "vdc", name_postfix, entities)

            for itc in self.interface:
                itcid = attach_entity(db, dbid, itc, dbid, "vdc", name_postfix, entities)
            return dbid
        except:
            cloud_utils.log_exception(sys.exc_info())
        return 0


class DEPARTMENT(object):
    def __init__(self, db, dbid):
        try:
            self.vdc = []
            self.department = cleanse_entity(db, entity_utils.read_full_entity(db, dbid))
            for v in cloud_utils.entity_members(db, dbid, "vdc",
                                                child_table=entity_manager.entities["vdc"].child_table):
                vdc = VDC(db, v["id"])
                json_vdc = jsonpickle.encode(vdc, unpicklable=False)
                self.vdc.append(ujson.loads(json_vdc))

            for profile in entity_constants.profile_group_child.keys():
                statement = "self.%s = get_group_entities_list(db, dbid, '%s')" % (profile, profile)
                exec statement
        except:
            cloud_utils.log_exception(sys.exc_info())

    def update_name(self, db, parent_dbid):
        duplicate = cloud_utils.lower_key(db.get_row("tblEntities", "name = '%s' AND parententityid = '%s'"
                                                                    " AND deleted = 0" % (
                                                         self.department["name"], parent_dbid),
                                                     order="ORDER BY id LIMIT 1"))
        if duplicate:
            self.department["name"] += "-" + entity_utils.create_entity_name(db, None)

    def clone(self, db, parent_dbid, name=None, description=None):
        try:
            if name:
                self.department["name"] = name
            else:
                self.department["name"] += "-clone" + entity_utils.create_entity_name(db, None)
            self.update_name(db, parent_dbid)
            if description:
                self.department["description"] = description
            if parent_dbid != 0:
                return self.restore(db, parent_dbid)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def restore(self, db, parent_dbid, name=None, name_postfix=None):
        try:
            if name:
                self.department["name"] = name
                self.update_name(db, parent_dbid)

            parent = entity_utils.read_partial_entity(db, parent_dbid)
            if not parent or parent["entitytype"] != "organization":
                return 0

            entities = []
            dbid = add_entity(db, parent_dbid, self.department, parent_dbid, "organization", name_postfix, entities)

            for profile in entity_constants.profile_group_child.keys():
                statement = "add_group_entities(db, dbid, self.%s, '%s', dbid, 'department', name_postfix)" % (
                    profile, profile)
                exec statement

            for v in self.vdc:
                entity = convert_json_entity(db, "department", v)
                if entity:
                    entity.restore(db, dbid)
            return dbid
        except:
            cloud_utils.log_exception(sys.exc_info())
        return 0


class ORGANIZATION(object):
    def __init__(self, db, dbid):
        try:
            self.department = []
            self.organization = cleanse_entity(db, entity_utils.read_full_entity(db, dbid))
            for v in cloud_utils.entity_members(db, dbid, "department",
                                                child_table=entity_manager.entities["department"].child_table):
                dept = DEPARTMENT(db, v["id"])
                json_dept = jsonpickle.encode(dept, unpicklable=False)
                self.department.append(ujson.loads(json_dept))

            for profile in entity_constants.profile_group_child.keys():
                statement = "self.%s = get_group_entities_list(db, dbid, '%s')" % (profile, profile)
                exec statement

        except:
            cloud_utils.log_exception(sys.exc_info())

    def update_name(self, db, parent_dbid):
        duplicate = cloud_utils.lower_key(db.get_row("tblEntities", "name = '%s' AND parententityid = '%s'"
                                                                    " AND deleted = 0" % (
                                                         self.organization["name"], parent_dbid),
                                                     order="ORDER BY id LIMIT 1"))
        if duplicate:
            self.organization["name"] += "-" + entity_utils.create_entity_name(db, None)

    def clone(self, db, parent_dbid, name=None, description=None):
        try:
            if name:
                self.organization["name"] = name
            else:
                self.organization["name"] += "-clone" + entity_utils.create_entity_name(db, None)
            self.update_name(db, parent_dbid)
            if description:
                self.organization["description"] = description

            if parent_dbid != 0:
                return self.restore(db, parent_dbid)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def restore(self, db, parent_dbid, name=None, name_postfix=None):
        try:
            if name:
                self.organization["name"] = name
                self.update_name(db, parent_dbid)

            parent = entity_utils.read_partial_entity(db, parent_dbid)
            if not parent or parent["entitytype"] != "system":
                return 0
            entities = []
            dbid = add_entity(db, parent_dbid, self.organization, parent_dbid, "system", name_postfix, entities)

            for profile in entity_constants.profile_group_child.keys():
                statement = "add_group_entities(db, dbid, self.%s, '%s', dbid, 'organization', name_postfix)" % (
                    profile, profile)
                exec statement

            for v in self.department:
                entity = convert_json_entity(db, "organization", v)
                if entity:
                    entity.restore(db, dbid)

            return dbid
        except:
            cloud_utils.log_exception(sys.exc_info())
        return 0


class SYSTEM(object):
    def __init__(self, db, dbid):
        try:
            self.organization = []
            self.system = cleanse_entity(db, entity_utils.read_full_entity(db, dbid))
            for v in cloud_utils.entity_members(db, dbid, "organization",
                                                child_table=entity_manager.entities["organization"].child_table):
                org = ORGANIZATION(db, v["id"])
                json_org = jsonpickle.encode(org, unpicklable=False)
                self.organization.append(ujson.loads(json_org))
        except:
            cloud_utils.log_exception(sys.exc_info())

    def restore(self, db, parent_dbid, name_postfix=None):
        try:
            entities = {}
            dbid = add_entity(db, parent_dbid, self.system, parent_dbid, "system", name_postfix, entities)
            for v in self.organization:
                entity = convert_json_entity(db, "system", v)
                if entity:
                    #                    duplicate = cloud_utils.lower_key(db.get_row("tblEntities", "name = '%s' AND parententityid = '%s'"
                    #                         " AND deleted = 0" % (entity["name"], parent_dbid) , order="ORDER BY id LIMIT 1"))
                    #                    if duplicate:
                    #                        id = db.execute_db("SELECT MAX(id) FROM tblEntities")
                    #                        entity["name"] += "-clone" + str(id[0]["MAX(id)"])
                    entity.restore(db, dbid)
            return dbid
        except:
            cloud_utils.log_exception(sys.exc_info())
        return 0


def copy_entity(db, dbid, to_dbid, name=None):
    try:
        parent = cloud_utils.lower_key(
            db.get_row("tblEntities", "id = '%s' AND deleted = 0" % to_dbid, order="ORDER BY id LIMIT 1"))
        if not parent:
            return
        json_entity = convert_entity_json(db, dbid)
        if json_entity:
            entity = convert_json_entity(db, parent["entitytype"], json_entity)
            if entity:
                return entity.clone(db, parent["id"], name)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return


def convert_entity_json(db, dbid):
    try:
        entity = cloud_utils.lower_key(
            db.get_row("tblEntities", "id = '%s' AND deleted = 0" % dbid, order="ORDER BY id LIMIT 1"))
        if not entity:
            return None
        if entity["entitytype"] == "vdc":
            entity_object = VDC(db, entity["id"])
        elif entity["entitytype"] == "department":
            entity_object = DEPARTMENT(db, entity["id"])
        elif entity["entitytype"] == "organization":
            entity_object = ORGANIZATION(db, entity["id"])
        elif entity["entitytype"] == "system":
            entity_object = SYSTEM(db, entity["id"])
        else:
            return
        return jsonpickle.encode(entity_object, unpicklable=False)
    except:
        cloud_utils.log_exception(sys.exc_info())
    return


def convert_json_entity(db, parent_entitytype, entity_unjson):
    try:
        if parent_entitytype == 'department' or parent_entitytype == 'vdc':
            entity_unjson["py/object"] = "%s.VDC" % __name__
        elif parent_entitytype == 'organization':
            entity_unjson["py/object"] = "%s.DEPARTMENT" % __name__
        elif parent_entitytype == 'system':
            entity_unjson["py/object"] = "%s.ORGANIZATION" % __name__
        elif parent_entitytype == 'datacenter':
            entity_unjson["py/object"] = "%s.SYSTEM" % __name__
        temp_entity = ujson.dumps(entity_unjson)
        return jsonpickle.decode(temp_entity)

    except:
        cloud_utils.log_exception(sys.exc_info())
    return


def save_entity(entity, filename):
    try:
        f = open(filename, 'w')
        f.write(entity)
        f.close()
        return filename
    except:
        cloud_utils.log_exception(sys.exc_info())
    return


def restore_entity(db, filename, to_dbid, clone=None, name=None):
    try:
        parent = cloud_utils.lower_key(
            db.get_row("tblEntities", "id = '%s' AND deleted = 0" % to_dbid, order="ORDER BY id LIMIT 1"))
        if not parent:
            return
        f = open(filename, 'r')
        json_entity = f.read()
        f.close()
        try:
            entity_unjson = ujson.loads(json_entity)
        except ValueError, e:
            cloud_utils.log_exception(sys.exc_info())
            return
        entity = convert_json_entity(db, parent["entitytype"], entity_unjson)
        if entity:
            if clone:
                return entity.clone(db, parent["id"], name)
            else:
                return entity.restore(db, parent["id"], name)
    except:
        cloud_utils.log_exception(sys.exc_info())


def save_ops(db, dbid, options):
    try:
        filename = None
        if "filename" in options:
            filename = options["filename"]
        if filename and os.path.exists(filename):
            return ujson.dumps({"result_code": -1, "result_message": "file %s already exists" % filename, "dbid": dbid})

        entity = convert_entity_json(db, dbid)
        if not entity:
            return ujson.dumps(
                {"result_code": -1, "result_message": "Unable to get any data for the entity", "dbid": dbid})
        if filename:
            save_entity(entity, filename)
            return ujson.dumps({"result_code": 0, "result_message": filename, "dbid": dbid})
        return ujson.dumps({"result_code": 0, "result_message": entity, "dbid": dbid})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"result_code": -1, "result_message": "unknown system errort", "dbid": dbid})


def restore_ops(db, dbid, options):
    try:
        if dbid == 0:
            parent = {"entitytype": "datacenter"}
        else:
            parent = entity_utils.read_partial_entity(db, dbid)
            if not parent:
                return ujson.dumps({"result_code": -1, "result_message": "parententity doe not exist", "dbid": dbid})
            if parent["entitytype"] == "vdc":
                parent = entity_utils.read_partial_entity(db, parent["parententityid"])
        filename = None
        if "filename" in options:
            filename = options["filename"]
        if filename and not os.path.exists(filename):
            return ujson.dumps({"result_code": -1, "result_message": "file %s doe not exist" % filename, "dbid": dbid})
        if filename:
            f = open(filename, 'r')
            json_entity = f.read()
            f.close()
        elif "entity" in options:
            json_entity = options["entity"]
        else:
            return ujson.dumps({"result_code": -1, "result_message": "json entity not provided", "dbid": dbid})
        try:
            entity_unjson = ujson.loads(json_entity)
        except ValueError, e:
            return ujson.dumps({"result_code": -1, "result_message": "Invalid json entity", "dbid": dbid})
        entity = convert_json_entity(db, parent["entitytype"], entity_unjson)
        if not entity:
            return ujson.dumps(
                {"result_code": -1, "result_message": "Invalid json entity - unable to unpickle", "dbid": dbid})

        if "clone" in options:
            newid = entity.clone(db, dbid, name=options["clone"])
        else:
            newid = entity.restore(db, parent["id"], vdcid=dbid, options=options)

        return ujson.dumps({"result_code": 0, "result_message": "entity restored", "dbid": newid})
    except:
        cloud_utils.log_exception(sys.exc_info())
    return ujson.dumps({"result_code": -1, "result_message": "unknown system errort", "dbid": dbid})


def clone_entity(db, dbid, options):
    try:
        cloned_entityvisibility = cloned_entitytype = cloned_entityname = cloned_entitydescription = None
        if "entity" in options:
            if "type" in options["entity"]:
                cloned_entitytype = options["entity"]["type"]
            if "name" in options["entity"]:
                cloned_entityname = options["entity"]["name"]
            if "description" in options["entity"]:
                cloned_entitydescription = options["entity"]["description"]
            if "availablity" in options["entity"]:
                cloned_entityvisibility = options["entity"]["availablity"]

        if not cloned_entityname or not cloned_entitytype:
            return ujson.dumps({"result_code": -1, "result_message": "clone name or type not provided", "dbid": 0})

        entity = entity_utils.read_partial_entity(db, dbid)
        if not cloned_entitydescription:
            cloned_entitydescription = entity["description"]
        if not entity:
            return None
        if entity["entitytype"] == "vdc":
            entity_object = VDC(db, entity["id"])
        elif entity["entitytype"] == "department":
            entity_object = DEPARTMENT(db, entity["id"])
        elif entity["entitytype"] == "organization":
            entity_object = ORGANIZATION(db, entity["id"])
        elif entity["entitytype"] == "system":
            entity_object = SYSTEM(db, entity["id"])
        else:
            return ujson.dumps({"result_code": -1, "result_message": "invalid entity id provided", "dbid": 0})

        if cloned_entitytype == "vdc":
            newid = entity_object.clone(db, entity["parententityid"], name=cloned_entityname,
                                        description=cloned_entitydescription)
        else:
            entity_json = convert_entity_json(db, dbid)
            if cloned_entityvisibility and (
                            cloned_entityvisibility == "department" or cloned_entityvisibility == "organization"):
                entity = entity_utils.read_partial_entity(db, entity["parententityid"])
                if cloned_entityvisibility == "organization":
                    entity = entity_utils.read_partial_entity(db, entity["parententityid"])

            newid = cloud_utils.update_or_insert(db, "tblEntities", {"name": cloned_entityname,
                                                                     "description": cloned_entitydescription,
                                                                     "entitytype": "template",
                                                                     "parententityid": entity["id"],
                                                                     "JSONString": entity_json},
                                                 {"name": cloned_entityname,
                                                  "entitytype": "template",
                                                  "parententityid": entity["id"]},
                                                 child_table=entity_manager.entities["template"].child_table)
        return ujson.dumps({"result_code": 0, "result_message": "entity restored", "dbid": newid})
    except:
        cloud_utils.log_exception(sys.exc_info())


def template_entity(db, dbid, options):
    try:

        if "name" not in options or not options["name"]:
            options["name"] = entity_utils.create_entity_name(db, "template")
        if "name" not in options:
            return ujson.dumps({"result_code": -1, "result_message": "name must be provided", "dbid": dbid})
        cloned_entityname = options["name"]
        cloned_entitydescription = ''
        if "description" in options:
            cloned_entitydescription = options["description"]
        newid = cloud_utils.update_or_insert(db, "tblEntities", {"name": cloned_entityname,
                                                                 "description": cloned_entitydescription,
                                                                 "entitytype": "template",
                                                                 "parententityid": dbid,
                                                                 "JSONString": options["entity"]},
                                             {"name": cloned_entityname,
                                              "entitytype": "template",
                                              "parententityid": dbid},
                                             child_table=entity_manager.entities["template"].child_table)
        return ujson.dumps({"result_code": 0, "result_message": "entity restored", "dbid": newid})
    except:
        cloud_utils.log_exception(sys.exc_info())


def add_template(db, vdc_dbid, template_dbid, offsetx, offsety):
    try:
        entity = entity_utils.read_full_entity(db, template_dbid)
        if not entity:
            return ujson.dumps({"result_code": -1, "result_message": "invalid entity id provided", "dbid": vdc_dbid})
        str = entity["jsonstring"]
        try:
            entity_unjson = ujson.loads(entity["jsonstring"])
        except ValueError, e:
            return ujson.dumps({"result_code": -1, "result_message": "Invalid json entity", "dbid": vdc_dbid})

        entity = convert_json_entity(db, "vdc", entity_unjson)
        if not entity:
            return ujson.dumps(
                {"result_code": -1, "result_message": "Invalid json entity - unable to unpickle", "dbid": vdc_dbid})

        id = entity_utils.create_entity_name(db, None)
        max_min_dict = {}
        entity.restore(db, 0, vdcid=vdc_dbid, name_postfix="-%s" % id, offsetx=long(round(float(offsetx))),
                       offsety=long(round(float(offsety))),
                       max_min_dict=max_min_dict)

        return ujson.dumps(dict(
            {"result_code": 0, "result_message": "entity restored", "dbid": vdc_dbid}.items() + max_min_dict.items()))
    except:
        cloud_utils.log_exception(sys.exc_info())


def file_ops(db, dbid, options=None):
    if not options:
        return ujson.dumps({"result_code": -1, "result_message": "no options provided", "dbid": 0})

    if not dbid or dbid == 0:
        if "dbid" in options:
            dbid = options["dbid"]

    if dbid is None:
        return ujson.dumps({"result_code": -1, "result_message": "no entity id provided", "dbid": 0})

    if "function" not in options:
        return ujson.dumps({"result_code": -1, "result_message": "no function provided", "dbid": dbid})

    if options["function"] == "save":
        return save_ops(db, dbid, options)

    elif options["function"] == "restore":
        return restore_ops(db, dbid, options)

    elif options["function"] == "clone":
        return clone_entity(db, dbid, options)

    elif options["function"] == "clear":
        return provision_entity.clear_entity(db, dbid, options)

    elif options["function"] == "template":
        return template_entity(db, dbid, options)
    else:
        return ujson.dumps(
            {"result_code": -1, "result_message": "invalid function %s provided" % options["function"], "dbid": dbid})


def conversions():
    try:
        db = cloud_utils.CloudGlobalBase(log=False)

        vdc = cloud_utils.lower_key(
            db.get_row("tblEntities", "entitytype='vdc' AND deleted = 0", order="ORDER BY id LIMIT 1"))
        filename = "/home/cloud/vdc"
        if os.path.exists(filename):
            os.remove(filename)
        save_entity(db, vdc["id"], filename)
        vdc_dbid = restore_entity(db, filename, vdc["parententityid"], clone=True, name=None)
        print vdc_dbid

        dept = cloud_utils.lower_key(
            db.get_row("tblEntities", "id='%s' AND deleted = 0" % vdc["parententityid"], order="ORDER BY id LIMIT 1"))
        filename = "/home/cloud/dept"
        if os.path.exists(filename):
            os.remove(filename)
        save_entity(db, dept["id"], filename)
        dept_dbid = restore_entity(db, filename, dept["parententityid"], clone=True, name=None)
        print dept_dbid

        org = cloud_utils.lower_key(
            db.get_row("tblEntities", "id='%s' AND deleted = 0" % dept["parententityid"], order="ORDER BY id LIMIT 1"))
        filename = "/home/cloud/org"
        if os.path.exists(filename):
            os.remove(filename)
        save_entity(db, org["id"], filename)
        org_dbid = restore_entity(db, filename, org["parententityid"], clone=True, name=None)
        print org_dbid

        system = cloud_utils.lower_key(
            db.get_row("tblEntities", "id='%s' AND deleted = 0" % dept["parententityid"], order="ORDER BY id LIMIT 1"))
        filename = "/home/cloud/org"
        if os.path.exists(filename):
            os.remove(filename)
        save_entity(db, org["id"], filename)
        org_dbid = restore_entity(db, filename, org["parententityid"], clone=True, name=None)
        print org_dbid

        entity = VDC(db, old["id"])



        #        coded = jsonpickle.encode(entity)

        coded1 = jsonpickle.encode(entity, unpicklable=False)

        uncoded1 = ujson.loads(coded1)
        uncoded1["py/object"] = "__main__.VDC"
        coded2 = json.dumps(uncoded1)

        #        uncoded = jsonpickle.decode(coded)
        uncoded2 = jsonpickle.decode(coded2)
        uncoded2.clone(db, old["parententityid"])


    except:
        cloud_utils.log_exception(sys.exc_info())
    return
