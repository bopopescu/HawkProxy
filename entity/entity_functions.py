#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import eventlet

# import json
import ujson
import yurl

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

import utils.cloud_utils as cloud_utils

import entity_utils
import entity_manager
import entity_constants
from utils.underscore import _
import cfd_keystone.cfd_keystone
import utils.cache_utils as cache_utils
import entity_file
import slice.slice_ops as slice_ops
import organization.organization_ops

import utils.publish_utils

LOG = logging.getLogger()

slice_objects = []
'''
    Organization is a virtual entity. It is defined one in the database - by system admin.
    Data Structure Formats:
    slice_objects:
    [ { 'slice':slice_object, 'name': slice name, 'dbid': id,
            "organizations": [ { 'name': name, "uri": organization uri,  "rest": orgnaization rest response}, 'dbid': id,
                "departments: { dbid, department_object,
                    ]
                }]
            }]
      }
    ]

'''

organization_objects = []
vdcs_dict = {}

storage_types = ["gold", "silver", "platinum", "bronze", "cloud"]


class SystemFunctions(object):
    def __init__(self, db):

        self.parent_row = None
        self.dbid = 0

        self.parent_row = db.get_row_dict("tblEntities", {"entitytype": "system"}, order="ORDER BY id LIMIT 1")
        if not self.parent_row:
            return
        self.dbid = self.parent_row["id"]
        initialize_resource_records(db, self.dbid, "system", 0)

    def do(self, db, function, options=None, **kwargs):
        timeout = eventlet.Timeout(1200)
        status = None
        LOG.info(_("SystemFunctions: Starting function %s with options %s" % (function, options)))
        try:
            status = self.functionMap.get(function.lower(), lambda *args, **kwargs: None)(self, db, options=options)
        except eventlet.Timeout:
            cloud_utils.log_exception(sys.exc_info())
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            timeout.cancel()
        LOG.info(_("Ending function %s" % function))
        return status

    def _initialize(self, db, options=None, **kwargs):
        try:
            self._update_slices(db)
        # self._update_organizations(db)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _update_slices(self, db, options=None, **kwargs):
        try:
            pool = eventlet.GreenPool()
            slices = db.get_multiple_row("tblEntities",
                                         "deleted=0 AND EntityType='slice' AND EntityStatus != 'Duplicate' ")
            if slices:
                for item in slices:
                    count = db.get_rowcount("tblEntities",
                                            "name='%s' AND deleted=0 AND EntityType='slice'" % item['Name'])
                    if count == 1:
                        eve = SliceFunctions(db, item['id'])
                        pool.spawn_n(eve.do, db, "initialize")
                    else:
                        # db.delete_row_id("tblEntities", item['id'])
                        LOG.critical(_("Skipping duplicate slices %s with id %s" % (item['Name'], item['id'])))
            pool.waitall()
            return "Slices initialized"
        except:
            cloud_utils.log_exception(sys.exc_info())
        return "Error in initializing slices"

    functionMap = {
        "initialize": _initialize,
        "slices": _update_slices,
    }


class SliceFunctions(object):
    def __init__(self, db, dbid, LOG=LOG):
        self.dbid = dbid
        self.LOG = LOG
        self.timeout = None
        self.parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                {"entitytype": "system"}, order="ORDER BY id LIMIT 1"))

    def do(self, db, function, options=None, **kwargs):
        # if options is None or "name" not in options.keys():
        #            return json.dumps({"result_code": -1, "result_message": "invalid parameters", "dbid": 0})
        self.timeout = eventlet.Timeout(600)
        status = None
        LOG.info(
            _("SliceFunctions: Starting function %s with dbid %s with options %s" % (function, self.dbid, options)))
        try:
            status = self.functionMap.get(function.lower(), lambda *args, **kwargs: None)(self, db, options=options)
        except eventlet.Timeout:
            cloud_utils.log_exception(sys.exc_info())
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            if self.timeout:
                self.timeout.cancel()
        LOG.info(_("SliceFunctions: Ending function %s with dbid %s" % (function, self.dbid)))
        return status

    def _create(self, db, options=None, **kwargs):
        # Create
        if options is None or "name" not in options.keys() or "url" not in options.keys():
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters", "dbid": 0})

        if options["url"].endswith("/"):
            options["url"] = options["url"][:-1]

        options["entitytype"] = "slice"
        options["parententityid"] = self.parent_row["id"]

        dup_slice = db.get_row_dict("tblEntities", {
            "name": options["name"],
            "entitytype": options["entitytype"],
            "deleted": 0,
            "parententityid": options["parententityid"]
        }, order="ORDER BY id LIMIT 1")
        if dup_slice:
            return ujson.dumps({"result_code": -1, "result_message": "duplicate slice", "dbid": dup_slice["id"]})

        self.dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                                 options,
                                                 {
                                                     "name": options["name"],
                                                     "entitytype": options["entitytype"],
                                                     "deleted": 0,
                                                     "parententityid": options["parententityid"]
                                                 },
                                                 child_table="tblSlices")
        if self.dbid == 0:
            return ujson.dumps({"result_code": -1, "result_message": "database create error", "dbid": 0})

        initialize_resource_records(db, self.dbid, "slice", options["parententityid"])
        slice_obj = slice_ops.Slice(db, self.dbid, user_info=options)
        self._add_slice(slice_obj)

        #        result = slice_obj.update(db, user_info=options)
        result = slice_obj.get_slice(db)

        if result:
            eventlet.spawn_n(self._get_status_update_resources, slice_obj, options)
        # else:
        #            update_entity_resource_records(db, self.parent_row["id"], "total", "slice", "total")
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _get_status_update_resources(self, slice_obj, options):
        try:
            db = cloud_utils.CloudGlobalBase(log=None)
            result = slice_obj.update(db, user_info=options)
            if result:
                update_entity_resource_records(db, self.parent_row["id"], "total", "slice", "total")
                entity_utils.clone_slice_images(db, self.dbid)
            db.close(log=None)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _initialize(self, db, **kwargs):
        if self.timeout:
            self.timeout.cancel()
            self.timeout = None
        slice = self._find_slice()
        if not slice:
            sc = slice_ops.Slice(db, self.dbid, LOG=self.LOG)
            slice = self._add_slice(sc)
        slice["slice"].update(db)
        update_entity_resource_records(db, self.parent_row["id"], "total", "slice", "total")

    def _delete(self, db, options=None, **kwargs):
        current_slice = self._find_slice()
        if current_slice is None:
            db.delete_rows_dict("tblUris", {"tblslices": self.dbid})
            entity_utils.delete_entity_recursively(db, self.dbid)
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - db row id", "dbid": 0})
        eventlet.spawn_n(self._delete_bg, current_slice, options)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _delete_bg(self, current_slice, options):
        try:
            db = cloud_utils.CloudGlobalBase(log=None)
            current_slice["slice"].delete(db)
            slice_objects.remove(current_slice)
            LOG.info(_("SliceObjects Count of %s after deletion: %s" % (len(slice_objects), str(slice_objects))))
            update_entity_resource_records(db, self.parent_row["id"], "total", "slice", "total")
            db.close()
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _update(self, db, options=None, **kwargs):
        current_slice = self._find_slice()
        if current_slice is None:
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - db row id", "dbid": 0})

        options.pop("name", None)
        options.pop("url", None)

        cloud_utils.update_or_insert(db, "tblEntities", options, {"id": self.dbid}, child_table="tblSlices")
        # current_slice["slice"].update(db, user_info=options)
        #        update_entity_resource_records(db, self.parent_row["id"], "total", "slice", "total")
        eventlet.spawn_n(self._get_status_update_resources, current_slice["slice"], options)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _status(self, db, options=None, **kwargs):
        current_slice = self._find_slice()
        if current_slice is None:
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - db row id", "dbid": 0})

        eventlet.spawn_n(self._get_status_update_resources, current_slice["slice"], options)
        # current_slice["slice"].status(db)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _find_slice(self):
        for index, value in enumerate(slice_objects):
            if value["dbid"] == self.dbid:
                return value
        return None

    def _add_slice(self, slice_obj):
        # delete any old slice records
        slice_objects[:] = [slice for slice in slice_objects if slice["name"] != slice_obj.get_name()]
        slice_objects.append({"name": slice_obj.get_name(), "dbid": self.dbid, "slice": slice_obj, "organizations": []})
        LOG.info(_("SliceObjects Count of %s after addition: %s" % (len(slice_objects), str(slice_objects))))
        return slice_objects[-1]

    functionMap = {
        "initialize": _initialize,
        "create": _create,
        "delete": _delete,
        "update": _update,
        "status": _status
    }


class OrganizationFunctions(object):
    def __init__(self, db, dbid):
        self.row = None
        if dbid:
            self.dbid = dbid
            self.row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": self.dbid},
                                                             order="ORDER BY id LIMIT 1"))
            self.parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                    {"entitytype": "system"},
                                                                    order="ORDER BY id LIMIT 1"))
        else:
            self.parent_row = cloud_utils.lower_key(
                db.get_row_dict("tblEntities", {"entitytype": "system"}, order="ORDER BY id LIMIT 1"))
            self.dbid = self.parent_row["id"]

    def do(self, db, function, options=None, **kwargs):
        timeout = eventlet.Timeout(600)
        status = None
        LOG.info(_("OrganizationFunctions: Starting function %s with dbid %s with options %s" % (function,
                                                                                                 self.dbid, options)))
        try:
            status = self.functionMap.get(function.lower(), lambda *args, **kwargs: None)(self, db, options=options)
        except eventlet.Timeout:
            cloud_utils.log_exception(sys.exc_info())
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            timeout.cancel()
        LOG.info(_("OrganizationFunctions: Ending function %s with dbid %s " % (function, self.dbid)))
        return status

    def _create(self, db, options=None, **kwargs):
        # Create
        if options is None:
            options = {}
        if "name" not in options:
            options["name"] = entity_utils.create_entity_name(db, "organization")
        if options is None or "name" not in options.keys():
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters", "dbid": 0})
        options["entitytype"] = "organization"
        options["parententityid"] = self.parent_row["id"]
        self.dbid = cloud_utils.update_or_insert(db, "tblEntities", options, {
            "name": options["name"], "entitytype": options["entitytype"],
            "deleted": 0, "parententityid": options["parententityid"]}, child_table="tblOrganizations")
        if self.dbid == 0:
            return ujson.dumps({"result_code": -1, "result_message": "database create error", "dbid": 0})
        if "user_row" in options:
            cloud_utils.log_message(db, self.parent_row["id"], "Organization %s created by user %s" % (
                options["name"], options["user_row"]["name"]))
        # entity_utils.clone_from_slices(db, self.dbid, "imagelibrary")
        eventlet.spawn_n(self._post_organization, options)
        eventlet.spawn_n(update_resource_records_bg, self.dbid, options["parententityid"], options["entitytype"],
                         options, create_flag=True)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _post_organization(self, options):
        db = cloud_utils.CloudGlobalBase(log=None)
        try:
            for slice in cloud_utils.get_entity(db, "slice", child_table=entity_manager.entities["slice"].child_table):
                if "virtual_infrastructure_url" not in slice or slice["entitystatus"].lower() != "active":
                    continue
                create_entity(self.dbid, options, slice_row=slice)
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            db.close()

    def _get_status_update_resources(self, organization_obj, slice_objects, options):
        try:
            db = cloud_utils.CloudGlobalBase(log=None)
            organization_obj.update(db, slice_objects, user_info=options)
            db.close(log=None)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _update(self, db, options=None, **kwargs):
        if not options:
            options = {}

        options["entitytype"] = "organization"
        options["parententityid"] = self.parent_row["id"]

        if "name" in options.keys() and options["name"] != self.row["name"]:
            row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": options["parententityid"],
                                                                        "entitytype": options["entitytype"],
                                                                        "name": options['name']},
                                                        order="ORDER BY id LIMIT 1"))
            if row:
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - duplicate name",
                                    "dbid": self.dbid})

            options["newname"] = options["name"]
            self.row["name"] = options["name"]

        options["name"] = self.row["name"]
        cloud_utils.update_or_insert(db, "tblEntities", options, {"id": self.dbid}, child_table="tblOrganizations")
        if "user_row" in options:
            cloud_utils.log_message(db, self.parent_row["id"], "Organization %s is updated by user %s" % (
                options["name"], options["user_row"]["name"]))

        eventlet.spawn_n(update_entity_bg, self.dbid, options)
        eventlet.spawn_n(update_resource_records_bg, self.dbid, options["parententityid"], options["entitytype"],
                         options, create_flag=False)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _delete(self, db, options=None, **kwargs):
        if "user_row" in options:
            cloud_utils.log_message(db, self.parent_row["id"], "Organization %s deleted by user %s" % (
                self.row["name"], options["user_row"]["name"]))
        eventlet.spawn_n(delete_entity_bg, self.dbid, options)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    functionMap = {
        "create": _create,
        "delete": _delete,
        "update": _update,
        "status": _update
    }


def verify_integer(number):
    if isinstance(number, (int, long)):
        return True
    if isinstance(number, basestring) and number.isdigit():
        return True
    return False


class DepartmentFunctions(object):
    def __init__(self, db, dbid):

        self.parent_row = None
        self.row = None
        self.dbid = dbid
        if self.dbid != 0:
            self.row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": self.dbid},
                                                             order="ORDER BY id LIMIT 1"))
            if self.row:
                self.parent_row = cloud_utils.lower_key(
                    db.get_row_dict("tblEntities", {"id": self.row["parententityid"]},
                                    order="ORDER BY id LIMIT 1"))

    def do(self, db, function, options=None, **kwargs):
        timeout = eventlet.Timeout(600)
        status = None
        LOG.info(_("DepartmentFunctions: Starting function %s with dbid %s with options %s" %
                   (function, self.dbid, options)))
        try:
            status = self.functionMap.get(function.lower(), lambda *args, **kwargs: None)(self, db, options=options)
        except eventlet.Timeout:
            cloud_utils.log_exception(sys.exc_info())
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            timeout.cancel()
        LOG.info(_("DepartmentFunctions: Ending function %s with dbid %s" % (function, self.dbid)))
        return status

    def _create(self, db, options=None, **kwargs):
        try:
            if options is None:
                options = {}
            if "name" not in options or not options["name"]:
                options["name"] = entity_utils.create_entity_name(db, "department")
            if options is None or "name" not in options.keys():
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - no name", "dbid": 0})
            if "parententityid" in options.keys() and verify_integer(options["parententityid"]):
                self.parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": options["parententityid"],
                                                                                        "EntityType": "organization"},
                                                                        order="ORDER BY id LIMIT 1"))
            elif "parententityname" in options.keys():
                self.parent_row = cloud_utils.lower_key(
                    db.get_row_dict("tblEntities", {"Name": options["parententityname"],
                                                    "EntityType": "organization"},
                                    order="ORDER BY id LIMIT 1"))

            if not self.parent_row:
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters- no parent name or id",
                                    "dbid": 0})
            options["parententityid"] = self.parent_row["id"]
            options["entitytype"] = "department"
            self.dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                                     options,
                                                     {
                                                         "name": options["name"],
                                                         "entitytype": options["entitytype"],
                                                         "deleted": 0,
                                                         "parententityid": options["parententityid"]
                                                     },
                                                     child_table="tblDepartments")
            if self.dbid == 0:
                return ujson.dumps({"result_code": -1, "result_message": "database create error", "dbid": 0})
            if "ssh_keys" in options:
                entity_manager.save_ssh_keys(db, self.dbid, options)
            if "attached_entities" in options:
                entity_manager.remove_and_add_attached_entities(db, self.dbid, options, mode="update")
            if "user_row" in options:
                cloud_utils.log_message(db, self.parent_row["id"], "Department %s created by user %s" % (
                    options["name"], options["user_row"]["name"]))
            eventlet.spawn_n(create_entity, self.dbid, options)
            eventlet.spawn_n(copy_profiles, self.dbid, self.parent_row["id"])
            eventlet.spawn_n(update_resource_records_bg, self.dbid, options["parententityid"], options["entitytype"],
                             options, create_flag=True)
            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _update(self, db, options=None, **kwargs):
        try:
            if not options:
                options = {}

            options["entitytype"] = "department"
            options["parententityid"] = self.row["parententityid"]

            if "name" in options.keys() and options["name"] != self.row["name"]:
                row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": options["parententityid"],
                                                                            "entitytype": options["entitytype"],
                                                                            "name": options['name']},
                                                            order="ORDER BY id LIMIT 1"))
                if row:
                    return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - duplicate name",
                                        "dbid": self.dbid})
                options["newname"] = options["name"]
                self.row["name"] = options["name"]

            options["name"] = self.row["name"]
            cloud_utils.update_or_insert(db, "tblEntities", options, {"id": self.dbid}, child_table="tblDepartments")

            if "ssh_keys" in options:
                entity_manager.save_ssh_keys(db, self.dbid, options)
            if "attached_entities" in options:
                entity_manager.remove_and_add_attached_entities(db, self.dbid, options, mode="update")
            if "user_row" in options:
                cloud_utils.log_message(db, options["parententityid"], "Department %s updated by user %s" %
                                        (options["name"], options["user_row"]["name"]))
            if "newname" in options:
                cloud_utils.update_or_insert(db, "tblEntities", {"name": options["newname"]},
                                             {"id": self.dbid}, child_table="tblDepartments")
            eventlet.spawn_n(update_entity_bg, self.dbid, options)
            eventlet.spawn_n(update_resource_records_bg, self.dbid, options["parententityid"], options["entitytype"],
                             options, create_flag=False)

            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _delete(self, db, options=None, **kwargs):
        try:
            if self.row:
                if not options:
                    options = {}
                options["entitytype"] = "department"
                options["name"] = self.row["name"]
                if "user_row" in options:
                    cloud_utils.log_message(db, self.parent_row["id"], "Department %s deleted by user %s" % (
                        options["name"], options["user_row"]["name"]))

                eventlet.spawn_n(delete_entity_bg, self.dbid, options)
            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())

    functionMap = {
        "create": _create,
        "delete": _delete,
        "update": _update
    }


def create_entity(dbid, options, slice_row=None):
    try:
        db = cloud_utils.CloudGlobalBase(log=None)
        eve = EntityFunctions(db, dbid, slice_row=slice_row, quick_provision=True)
        response = eve.do(db, "provision", options=options)
        LOG.info(_("Entity created with response %s" % response))
        print response
        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def update_resource_records_bg(dbid, parent_dbid, entitytype, options, create_flag=False):
    try:
        db = cloud_utils.CloudGlobalBase(log=False)
        if create_flag:
            initialize_resource_records(db, dbid, entitytype, parent_dbid)
        update_user_assigned_resource_records(db, dbid, options)
        update_entity_resource_records(db, parent_dbid, "allocated",
                                       entity_constants.resource_parent_entitytype[entitytype], "total")
        db.close()
    except:
        cloud_utils.log_exception(sys.exc_info())


def copy_profiles(to_dbid, from_dbid):
    try:
        db = cloud_utils.CloudGlobalBase(log=None)
        for group in entity_constants.profile_group_clone:
            entity_utils.clone_entity(db, to_dbid, from_dbid, group, update_clonedfrom=False)
        for group in entity_constants.profile_group_clone:
            entity_utils.clone_entity_attachments(db, to_dbid, from_dbid, group, to_dbid)

        db.close(log=None)
    except:
        cloud_utils.log_exception(sys.exc_info())


def update_entity_bg(dbid, options=None, slice_row=None):
    db = cloud_utils.CloudGlobalBase(log=None)
    try:
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if not row:
            LOG.critical(_("No url: unable to update id:%s error:%s " % (dbid, error)))
            return
        element, error = entity_manager.get_entity_json(db, dbid, row)
        if not element:
            LOG.critical(
                _("No json encoding: unable to update VDC:%s id:%s with error:%s " % (row["name"], dbid, error)))
            return
        url, error = entity_utils.get_entity_uri(db, dbid, row)
        if not url:
            LOG.critical(_("No url: unable to update VDC:%s id:%s error:%s " % (row["name"], dbid, error)))
            return
        rest_me = entity_utils.put_entity(element, row["entitytype"], url)
    except:
        cloud_utils.log_exception(sys.exc_info())
    finally:
        db.close()


def delete_entity_bg(dbid, options):
    try:
        db = cloud_utils.CloudGlobalBase(log=None)
        row, error = entity_utils.read_full_entity_status_tuple(db, dbid)
        if not row:
            LOG.critical(_("No url: unable to update id:%s error:%s " % (dbid, error)))
            return
        url, error = entity_utils.get_entity_uri(db, dbid, row)
        if not url:
            LOG.critical(_("No url: unable to delete entity:%s id:%s error:%s " % (row["name"], dbid, error)))
        eventlet.spawn_n(entity_utils.delete_entity, url)
        db.delete_rows_dict("tblUris", {"tblentities": dbid})
        entity_utils.delete_entity_recursively(db, dbid)
        db.close()
    except:
        cloud_utils.log_exception(sys.exc_info())


class VDCFunctions(object):
    def __init__(self, db, dbid):
        self.parent_row = None
        self.dbid = dbid
        self.vdc_object = None
        self.dept_object = None
        self.selected_slice = None
        self.grandparent = None
        if self.dbid == 0:
            return
        self.row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": self.dbid},
                                                         order="ORDER BY id LIMIT 1"))
        if not self.row:
            return
        self.row.update(cloud_utils.lower_key(db.get_row_dict("tblVdcs", {"tblEntities": self.dbid},
                                                              order="ORDER BY id LIMIT 1")))
        self.parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": self.row["parententityid"]},
                                                                order="ORDER BY id LIMIT 1"))
        self.grandparent = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                 {"id": self.parent_row["parententityid"]},
                                                                 order="ORDER BY id LIMIT 1"))
        try:
            for slice in slice_objects:
                if slice["dbid"] == self.row["selectedsliceentityid"]:
                    for org in slice["organizations"]:
                        if org["dbid"] == self.grandparent["id"]:
                            self.dept_object = org["departments"].get(self.parent_row["id"], None)
                            if self.dept_object is None:
                                return
                            self.vdc_object = self.dept_object.get_vdc_object(self.dbid)
                            return
        except:
            cloud_utils.log_exception(sys.exc_info())

    def do(self, db, function, options=None, **kwargs):
        timeout = eventlet.Timeout(600)
        status = None
        LOG.info(_("VDCFunctions: Starting function %s with %s with options %s" % (function, self.dbid, options)))
        try:
            status = self.functionMap.get(function.lower(), lambda *args, **kwargs: None)(self, db, options=options)
        except eventlet.Timeout:
            cloud_utils.log_exception(sys.exc_info())
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            timeout.cancel()
        LOG.info(_("VDCFunctions: Ending function %s with dbdid %s" % (function, self.dbid)))
        return status

    def _create(self, db, options=None, **kwargs):
        try:
            if options is None:
                options = {}
            if "name" not in options or not options["name"]:
                options["name"] = entity_utils.create_entity_name(db, "vdc")
            if options is None or "name" not in options.keys():
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - no name", "dbid": 0})
            if "parententityid" in options.keys() and verify_integer(options["parententityid"]):
                self.parent_row = cloud_utils.lower_key(
                    db.get_row_dict("tblEntities", {"id": options["parententityid"]},
                                    order="ORDER BY id LIMIT 1"))
            elif "parententityname".lower() in options.keys():
                self.parent_row = cloud_utils.lower_key(db.get_row_dict("tblEntities",
                                                                        {"Name": options["parententityname"],
                                                                         "EntityType": "department"},
                                                                        order="ORDER BY id LIMIT 1"))
            if not self.parent_row:
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters- no parent name or id",
                                    "dbid": 0})
            self.grandparent = cloud_utils.lower_key(
                db.get_row_dict("tblEntities", {"id": self.parent_row["parententityid"]},
                                order="ORDER BY id LIMIT 1"))
            options["entitytype"] = "vdc"
            options["parententityid"] = self.parent_row["id"]
            # options["entitysubtype"] = "network_service"

            self.selected_slice = self.allocate_slice()
            if self.selected_slice:
                options["selectedsliceentityid"] = self.selected_slice["dbid"]
            self.dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                                     options,
                                                     {
                                                         "name": options["name"],
                                                         "entitytype": options["entitytype"],
                                                         "deleted": 0,
                                                         "parententityid": options["parententityid"]
                                                     },
                                                     child_table="tblVdcs")
            if self.dbid == 0:
                return ujson.dumps({"result_code": -1, "result_message": "database create error", "dbid": 0})

            if "ssh_keys" in options:
                entity_manager.save_ssh_keys(db, self.dbid, options)

            if "metadata" in options and options["metadata"]:
                entity_manager.update_db_metadata_keyvalue(db, self.dbid, options)

            if "user_data" in options:
                entity_manager.save_user_data(db, self.dbid, options)

            if "attached_entities" in options:
                entity_manager.remove_and_add_attached_entities(db, self.dbid, options, mode="create")

            if "user_row" in options:
                cloud_utils.log_message(db, self.parent_row["id"],
                                        "VDC %s created by user %s" % (options["name"], options["user_row"]["name"]))

            eventlet.spawn_n(create_entity, self.dbid, options)
            eventlet.spawn_n(copy_profiles, self.dbid, self.parent_row["id"])
            eventlet.spawn_n(update_resource_records_bg, self.dbid, options["parententityid"], options["entitytype"],
                             options, create_flag=True)
            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _get_status_update_resources(self, organization_obj, options):
        try:
            eventlet.sleep(0.0001)
            db = cloud_utils.CloudGlobalBase(log=None)
            self.vdc_object = vdcs_dict[self.dbid] = organization_obj.create_grandchild(db, self.dbid,
                                                                                        self.parent_row["id"],
                                                                                        self.selected_slice, options)
            db.close(log=None)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def allocate_slice(self):
        if slice_objects:
            return slice_objects[0]

    def _update(self, db, options=None, **kwargs):
        try:
            if not self.row:
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - entity not found",
                                    "dbid": self.dbid})
            if not options:
                options = {}
            options["entitytype"] = "vdc"
            options["parententityid"] = self.parent_row["id"]

            if "templateid" in options:
                return self.vdc_template(db, options)

            if "name" in options.keys() and options["name"] != self.row["name"]:
                row = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"parententityid": options["parententityid"],
                                                                            "entitytype": options["entitytype"],
                                                                            "name": options['name']},
                                                            order="ORDER BY id LIMIT 1"))
                if row:
                    return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - duplicate name",
                                        "dbid": self.dbid})

                    # options["name"] = self.row["name"]

            if "ssh_keys" in options:
                entity_manager.save_ssh_keys(db, self.dbid, options)
            if "metadata" in options and options["metadata"]:
                entity_manager.update_db_metadata_keyvalue(db, self.dbid, options)
            if "attached_entities" in options:
                entity_manager.remove_and_add_attached_entities(db, self.dbid, options, mode="update")
            if "user_data" in options:
                entity_manager.save_user_data(db, self.dbid, options)
            if "user_row" in options:
                cloud_utils.log_message(db, self.parent_row["id"],
                                        "VDC %s updated by user %s" % (options["name"], options["user_row"]["name"]))

            cloud_utils.update_only(db, "tblEntities", options, {"id": self.dbid}, child_table="tblVdcs")
            eventlet.spawn_n(update_resource_records_bg, self.dbid, options["parententityid"], options["entitytype"],
                             options, create_flag=False)
            eventlet.spawn_n(update_entity_bg, self.dbid, options)
            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _delete(self, db, options=None, **kwargs):
        if not self.row:
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - entity not found",
                                "dbid": self.dbid})
        if not options:
            options = {}
        options["entitytype"] = "vdc"
        options["name"] = self.row["name"]

        if "user_row" in options:
            cloud_utils.log_message(db, self.parent_row["id"],
                                    "VDC %s deleted by user %s" % (options["name"], options["user_row"]["name"]))

        eventlet.spawn_n(delete_entity_bg, self.dbid, options)
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    def _command(self, db, options=None, **kwargs):
        if "command" not in options.keys():
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - command missing",
                                "dbid": self.dbid})
        if options["command"] == "paste":
            return self.vdc_paste(db, options)
        if options["command"] == "template":
            return self.vdc_template(db, options)
        LOG.critical(_("Unknown vdc command: unable to process VDC:%s id:%s " % (self.row["name"], self.dbid)))
        return ujson.dumps({"result_code": -1, "result_message": "internal error - invalid command",
                            "dbid": self.dbid})

    def vdc_template(self, db, options):
        if "templateid" in options and "positionx" in options and "positiony" in options:
            return entity_file.add_template(db, self.dbid, options["templateid"], options["positionx"],
                                            options["positiony"])
        else:
            return ujson.dumps({"result_code": -1, "result_message": "invalid parameters", "dbid": self.dbid})

    def vdc_paste(self, db, options):
        return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

    functionMap = {
        "create": _create,
        "delete": _delete,
        "update": _update,
        "command": _command,
    }


class EntityFunctions(object):
    def __init__(self, db, dbid, slice_row=None, callback=None, return_object=None, row=None, quick_provision=False):
        self.parent_row = None
        self.slice_row = slice_row
        self.dbid = dbid
        self.vdc_object = None
        self.dept_object = None
        self.selected_slice = None
        self.error = None
        self.row = row
        self.uri_row = None
        self.parent_uri_row = None
        self.callback = callback
        self.return_object = return_object
        #        self.jobid = jobid
        self.quick_provision = quick_provision

    def do(self, db, function, options=None, do_get=False, **kwargs):
        timeout = eventlet.Timeout(600)
        status = None
        LOG.info(_("Starting function %s with %s with options %s" % (function, self.dbid, options)))
        try:
            status = self.functionMap.get(function.lower(), lambda *args, **kwargs: None)(self, db, options=options,
                                                                                          do_get=do_get)
        except eventlet.Timeout:
            cloud_utils.log_exception(sys.exc_info())
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            timeout.cancel()
        LOG.info(_("Ending function %s with dbdid %s" % (function, self.dbid)))
        return status

    def _create(self, db, options=None, **kwargs):
        try:
            # Create
            self.error = entity_utils.confirm_options_keys(options, ["entitytype", "parententityid"])
            if self.error or not verify_integer(options["parententityid"]):
                return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})

            if options["parententityid"] == 0:
                if options["entitytype"] == "user_group" or \
                                options["entitytype"] == "storage_class" or \
                                options["entitytype"] == "compute_class" or \
                                options["entitytype"] == "network_class":
                    system = cloud_utils.lower_key(
                        db.get_row_dict("tblEntities", {"entitytype": "system", "deleted": 0},
                                        order="ORDER BY id LIMIT 1"))
                    options["parententityid"] = system["id"]
                else:
                    return ujson.dumps({"result_code": -1, "result_message": "invalid parent entity id", "dbid": 0})

            if options["entitytype"] == "user":
                dup_user = db.execute_db("SELECT tblEntities.* FROM tblEntities JOIN tblUsers "
                                         " WHERE ( tblUsers.tblEntities = tblEntities.id AND "
                                         " tblUsers.loginid = '%s' AND tblEntities.deleted=0 ) ORDER BY id DESC LIMIT 1" %
                                         options["loginid"])
                if dup_user:
                    return ujson.dumps({"result_code": -1, "result_message": "user id already in user", "dbid": 0})

            if options["entitytype"] not in entity_manager.entities.keys():
                return ujson.dumps(
                    {"result_code": -1, "result_message": "invalid entity type %s" % options["entitytype"],
                     "dbid": 0})
            if "name" not in options or not options["name"]:
                options["name"] = entity_utils.create_entity_name(db, options["entitytype"])
            if options["entitytype"] in entity_constants.topology_network_services:
                options["entitysubtype"] = "network_service"
                options["Throughputs"] = entity_utils.get_throughputs(db, options)

            self.parent_row, status = entity_utils.read_full_entity_status_tuple(db, options["parententityid"])
            result = entity_manager.entities[options["entitytype"]].pre_db_create_function(db, options,
                                                                                           mode="create",
                                                                                           parent_row=self.parent_row)

            if result:
                return ujson.dumps({"result_code": -1, "result_message": "%s" % result, "dbid": 0})

            self.dbid = cloud_utils.update_or_insert(db, "tblEntities", options,
                                                     {
                                                         "name": options["name"],
                                                         "entitytype": options["entitytype"],
                                                         "deleted": 0,
                                                         "parententityid": options["parententityid"]
                                                     },
                                                     child_table=entity_manager.entities[
                                                         options["entitytype"]].child_table)
            if self.dbid == 0:
                return ujson.dumps({"result_code": -1, "result_message": "database create error", "dbid": 0})

            if "ssh_keys" in options:
                entity_manager.save_ssh_keys(db, self.dbid, options)

            if "user_data" in options:
                entity_manager.save_user_data(db, self.dbid, options)

            if "attached_entities" in options:
                entity_manager.remove_and_add_attached_entities(db, self.dbid, options, mode="create")

            if "attach_to" in options:
                entity_manager.remove_and_add_attach_to_entities(db, self.dbid, options, mode="update")

            entity_manager.entities[options["entitytype"]].post_db_create_function(db, self.dbid, options,
                                                                                   mode="create",
                                                                                   parent_row=self.parent_row)

            if not options or "usertype" not in options or options["usertype"] != "developer":
                eventlet.spawn_n(self._post, options)

            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())
        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})

    def _post(self, options=None, **kwargs):
        db = cloud_utils.CloudGlobalBase(log=False)
        try:
            if not entity_manager.entity_rest_api_enabled(db, self.dbid, options):
                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
            if options["entitytype"] not in entity_constants.vdc_provision_only_entitytypes:
                self._provision(db, options=options)
            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            db.close()
        return ujson.dumps({"result_code": -1, "result_message": "exception", "dbid": self.dbid})

    def _update(self, db, options=None, **kwargs):
        try:
            if self.dbid == 0:
                if options and "networkservicename" in options and "parententityid" in options:
                    trow = cloud_utils.lower_key(
                        db.get_row_dict("tblEntities", {"parententityid": options["parententityid"],
                                                        "name": options["networkservicename"],
                                                        "entitysubtype": "network_service"
                                                        }, order="ORDER BY id LIMIT 1"))
                    if not trow:
                        return ujson.dumps({"result_code": -1, "result_message": "database id not provided", "dbid": 0})
                    self.dbid = trow["id"]
            if options and "log_state" in options:
                db.execute_db("UPDATE tblLogs SET field='Error' WHERE id='%s' AND field = 'Alert' " % self.dbid)
                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

            self.row = cloud_utils.lower_key(
                db.get_row_dict("tblEntities", {"id": self.dbid}, order="ORDER BY id LIMIT 1"))
            if not self.row:
                return ujson.dumps({"result_code": -1, "result_message": "invalid table id", "dbid": self.dbid})
            if options:
                if "name" in options.keys() and options["name"] != self.row["name"]:
                    self.error = self.duplicate_name_check(db, options)
                    if self.error:
                        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})
                    if self.row["entitysubtype"] == "network_service":
                        entity_utils.update_destination_port_name(db, self.dbid, options["name"])

                options["entitytype"] = self.row["entitytype"]
                options["parententityid"] = self.row["parententityid"]
                #                if "persistencetimeout" in options:
                #                    options["persistencetimeout"] = int(options["persistencetimeout"] )
                cloud_utils.update_or_insert(db, "tblEntities", options, {"id": self.dbid},
                                             child_table=entity_manager.entities[options["entitytype"]].child_table)

                if "ssh_keys" in options:
                    entity_manager.save_ssh_keys(db, self.dbid, options)

                if "user_data" in options:
                    entity_manager.save_user_data(db, self.dbid, options)

                if "attached_entities" in options:
                    entity_manager.remove_and_add_attached_entities(db, self.dbid, options, mode="update",
                                                                    entity_row=self.row)

                if "attach_to" in options:
                    entity_manager.remove_and_add_attach_to_entities(db, self.dbid, options, mode="update")

                if "policy" in options:
                    entity_manager.save_entity_policy(db, self.dbid, options)

                if "flavors" in options:
                    entity_manager.save_entity_flavors(db, self.dbid, options)

                if "classes" in options:
                    entity_manager.save_entity_classes(db, self.dbid, self.row, options)

                entity_manager.entities[options["entitytype"]].post_db_create_function(db, self.dbid, options,
                                                                                       mode="update")

            if options and "usertype" in options and options["usertype"] == "developer":
                eventlet.spawn_n(self._developer, options)
                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

            if not entity_manager.entity_rest_api_enabled(db, self.dbid, self.row):
                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

            if self.row["entitytype"] in entity_constants.vdc_no_update_entitytypes:
                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

            self.row, self.error = entity_utils.read_full_entity_status_tuple(db, self.dbid)
            if self.row:
                element, self.error = entity_manager.get_entity_json(db, self.dbid, self.row)
                if element:
                    url, self.error = self.get_entity_uri(db, self.dbid, self.row)
                    if url:
                        rest_me = entity_utils.put_entity(element, self.row["entitytype"], url)
                        if self.check_status(db, rest_me, url):
                            return ujson.dumps({"result_code": rest_me.get("http_status_code", 500),
                                                "result_message": "http rest error", "dbid": self.dbid})
                        entity_manager.entities[self.row["entitytype"]].post_rest_get_function(db, self.dbid, rest_me,
                                                                                               rest='put')
                        rest_me.pop("name", None)
                        cloud_utils.update_or_insert(db, "tblEntities", rest_me, {"id": self.dbid},
                                                     child_table=entity_manager.entities[
                                                         self.row["entitytype"]].child_table)

                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
            return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})
        except:
            cloud_utils.log_exception(sys.exc_info())
        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})

    def _status(self, db, options=None, do_get=False, **kwargs):
        try:
            if self.dbid == 0:
                return ujson.dumps({"result_code": -1, "result_message": "database id not provided", "dbid": 0})
            self.row, self.error = entity_utils.read_full_entity_status_tuple(db, self.dbid)
            if self.row:
                if self.row["entitytype"] == "slice":
                    eve = SliceFunctions(db, self.dbid)
                    return eve.do(db, "status", options=options)

                if self.row["entitytype"] == "organization":
                    eve = OrganizationFunctions(db, self.dbid)
                    return eve.do(db, "status", options=options)

                # if self.row["entitytype"] == "department":
                #                    eve = DepartmentFunctions(db, self.dbid)
                #                    return eve.do(db, "status", options=options)

                #                if self.row["entitytype"] == "vdc":
                #                    eve = VDCFunctions(db, self.dbid)
                #                    return eve.do(db, "status", options=options)

                if not entity_manager.entity_rest_api_enabled(db, self.dbid, self.row):
                    return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

                url, self.error = self.get_entity_uri(db, self.dbid, self.row)
                if url:
                    if do_get:
                        rest_me = entity_utils.get_entity(url)
                        ignore_pending = True
                    else:
                        rest_me = entity_utils.put_entity({"command": "status"}, self.row["entitytype"], url)
                        ignore_pending = False

                    if self.check_status(db, rest_me, url, ignore_pending=ignore_pending):
                        return ujson.dumps(
                            {"result_code": rest_me.get("http_status_code", 500), "result_message": "http rest error",
                             "dbid": self.dbid})
                    entity_manager.entities[self.row["entitytype"]].post_rest_get_function(db, self.dbid, rest_me,
                                                                                           rest='get')
                    rest_me.pop("name", None)
                    cloud_utils.update_or_insert(db, "tblEntities", rest_me, {"id": self.dbid},
                                                 child_table=entity_manager.entities[
                                                     self.row["entitytype"]].child_table)

                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
            return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})
        except:
            cloud_utils.log_exception(sys.exc_info())
        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})

    def _delete(self, db, options=None, **kwargs):
        try:
            if self.dbid == 0:
                return ujson.dumps({"result_code": -1, "result_message": "database id not provided", "dbid": 0})
            self.row, self.error = entity_utils.read_full_entity_status_tuple(db, self.dbid)

            if self.row:
                if self.row["entitytype"] == "slice":
                    eve = SliceFunctions(db, self.dbid)
                    return eve.do(db, "delete", options=options)

                if self.row["entitytype"] == "organization":
                    eve = OrganizationFunctions(db, self.dbid)
                    return eve.do(db, "delete", options=options)

                if self.row["entitytype"] == "department":
                    eve = DepartmentFunctions(db, self.dbid)
                    return eve.do(db, "delete", options=options)

                if self.row["entitytype"] == "vdc":
                    eve = VDCFunctions(db, self.dbid)
                    return eve.do(db, "delete", options=options)

                if entity_manager.entity_rest_api_enabled(db, self.dbid, self.row):
                    # delete from CFD
                    url, self.error = self.get_entity_uri(db, self.dbid, self.row)
                    if url:
                        # rest_me = entity_utils.delete_entity(url)
                        eventlet.spawn_n(entity_utils.delete_entity, url)

                id = entity_manager.entities[self.row["entitytype"]].pre_db_delete_function(db, self.dbid, self.row)
                # we will skip the next few steps in case we are deleting an interfacce, but instead we have deleted the tap service.
                if self.row["entitytype"] != "network_interface" or not id or id == 0:
                    entity_utils.delete_entity_recursively(db, self.dbid)
                    db.execute_db("DELETE FROM tblAttachedEntities WHERE attachedentityid='%s'" % self.dbid)
                    entity_manager.entities[self.row["entitytype"]].post_db_delete_function(db, self.dbid, self.row)

                if id and self.row["entitytype"] == "tap_network_service":
                    self.dbid = id

                return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
            return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})
        except:
            cloud_utils.log_exception(sys.exc_info())
        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})

    def _command(self, db, options=None, **kwargs):
        try:
            if self.dbid == 0:
                self.call_callback(db, "failed", 500)
                return ujson.dumps({"result_code": -1, "result_message": "database id not provided", "dbid": 0})
            if "command" not in options.keys():
                self.call_callback(db, "failed", 500)
                return ujson.dumps({"result_code": -1, "result_message": "invalid parameters - command missing",
                                    "dbid": self.dbid})

            self.row, self.error = entity_utils.read_full_entity_status_tuple(db, self.dbid)
            if self.row:
                if (options["command"] == "provision" or options["command"] == "deprovision") and \
                        (self.row["entitytype"] == "volume" or self.row["entitytype"] == "server"):
                    status = entity_utils.update_resources(db, self.row, options["command"])
                    if status != "success":
                        if options["command"] != "deprovision":
                            LOG.critical(_("%s: Command %s failed - update user status status" % (
                                self.row["name"], options["command"])))
                            utils.publish_utils.publish(self.row["id"], {
                                "update_status": {"dbid": self.row["id"], "status": self.row["entitystatus"]}})
                            if options["command"] == "provision":
                                entity_utils.log_entity_message(db, self.dbid,
                                                                "Provision failed due to insufficient resoucres",
                                                                entity=self.row, type='Warn')
                                return ujson.dumps(
                                    {"result_code": -1, "result_message": "Insufficient resources to provision",
                                     "dbid": self.dbid})
                            else:
                                return ujson.dumps({"result_code": -1, "result_message": "Unable to deprovision",
                                                    "dbid": self.dbid})
                elif options["command"] == "backup" or options["command"] == "archive":
                    if "entity_container" not in options:
                        self.call_callback(db, "failed", 500)
                        return ujson.dumps(
                            {"result_code": -1, "result_message": "invalid parameters - container id missing",
                             "dbid": self.dbid})
                    if "entity_name" in options:
                        options["name"] = options["entity_name"]
                    else:
                        options["name"] = self.row["name"] + "-" + cloud_utils.generate_uuid()

                    if "entity_description" in options:
                        options["description"] = options["entity_description"]
                        options.pop("entity_description", None)

                    con_dbid = options["entity_container"]
                    options["entity_name"], options[
                        "entity_container"], familytree = entity_manager.get_child_parent_name(db, self.dbid)

                    self.dbid = 0
                    options["parententityid"] = con_dbid
                    options["entitytype"] = "volume"
                    options["capacity"] = self.row["capacity"]
                    options["capacity"] = self.row["capacity"]
                    options["volumeclass"] = self.row["volumeclass"]
                    options["voltype"] = self.row["voltype"]
                    options["permissions"] = self.row["permissions"]
                    self.row = None
                    return self._create(db, options=options)

                url, self.error = self.get_entity_uri(db, self.dbid, self.row)
                if not url:
                    LOG.critical(_("%s: Command failed - Unable to find uri for self" % self.row["name"]))
                else:
                    force_periodic = False
                    if options["command"] != "cancel":
                        #                            and self.jobid == 0:
                        if self.return_object:
                            pass
                        # and isinstance(self.return_object, list) and "jobid" in \
                        #                                self.return_object[-1]:
                        #                            self.jobid = self.return_object[-1]["jobid"]
                        else:

                            #                            add = {"entitytype": "job_queue", "parententityid": self.dbid, "deleted": 0,
                            #                                   "command": ujson.dumps(options), "status": "Started"}
                            #                            self.jobid = cloud_utils.update_or_insert(db, "tblEntities", add, None,
                            #                                                                      child_table="tblJobsQueue")
                            self.callback = entity_command_completed
                            if not self.return_object:
                                self.return_object = []
                            self.return_object.append({"entitytype": self.row["entitytype"],
                                                       "options": options, "dbid": self.dbid,
                                                       #                                                       "jobid": self.jobid,
                                                       "caller": "entity.command"})
                    saved_options = {}
                    if self.row["entitytype"] == "volume":
                        if options["command"] == "snapshot":
                            if "entity_name" not in options:
                                options["entity_name"] = self.row["name"] + "-" + cloud_utils.generate_uuid()
                            options.pop("name", None)
                            options.pop("description", None)
                            force_periodic = True
                            # new_dbid = cloud_utils.update_or_insert(db, "tblEntities", item_rest, {"parententityid": dbid,
                            #                                                        "entitytype":options["command"], "name":volume_name},
                            #                                                 child_table=entity_manager.entities[volume_type].child_table)

                    options.pop("user_row", None)
                    rest_me = entity_utils.put_entity(options, self.row["entitytype"], url)

                    if options["command"] != "cancel":
                        if self.check_status(db, rest_me, url, force_periodic=force_periodic, ignore_pending=self.quick_provision):
                            # if an error is detected
                            self._local_command(db, options)
                            return ujson.dumps({"result_code": rest_me.get("http_status_code", 500),
                                                "result_message": "http rest error", "dbid": self.dbid})
                        rest_me.pop("name", None)
                        cloud_utils.update_or_insert(db, "tblEntities", rest_me, {"id": self.dbid},
                                                     child_table=entity_manager.entities[
                                                         self.row["entitytype"]].child_table)
                    return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
                self._local_command(db, options)
            self.call_callback(db, "failed", 500)
            return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())
        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})

    def _local_command(self, db, options=None, **kwargs):
        try:
            if options["command"] == "provision":
                entity_utils.log_entity_message(db, self.dbid, "Provision failed due to a commuication error",
                                                entity=self.row, type='Warn')
                cloud_utils.update_only(db, "tblEntities", {"entitystatus": "Aborted"}, {"id": self.dbid})
            elif options["command"] == "deprovision":
                entity_utils.log_entity_message(db, self.dbid, "Deprovision deferred due to a commuication error",
                                                entity=self.row, type='Warn')
                cloud_utils.update_only(db, "tblEntities", {"entitystatus": "Ready"}, {"id": self.dbid})
            elif options["command"] == "clear":
                entity_utils.log_entity_message(db, self.dbid, "Clear state deferred due to a commuication error",
                                                entity=self.row, type='Warn')
                cloud_utils.update_only(db, "tblEntities", {"entitystatus": "Ready"}, {"id": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())

    def _developer(self, options, **kwargs):
        db = cloud_utils.CloudGlobalBase(log=False)
        try:
            self.row = entity_utils.read_remaining_entity(db, self.dbid, self.row)
            self._provision(db, options=options)
            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})
        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            db.close()
        return ujson.dumps({"result_code": -1, "result_message": "exception", "dbid": self.dbid})

    def _provision(self, db, options=None, **kwargs):
        try:
            if not self.row:
                self.row, self.error = entity_utils.read_full_entity_status_tuple(db, self.dbid)
                if not self.row or self.error:
                    LOG.critical(_("%s: Provision failed - Unable to locate row in dataase" % str(options)))
                    self.call_callback(db, "failed", 500)
                    return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})

            element, self.error = entity_manager.get_entity_json(db, self.dbid, self.row, options=options,
                                                                 quick_provision=self.quick_provision)
            if not element:
                LOG.critical(_("%s: Provision failed - Unable to json encode the entity" % self.row["name"]))
                self.call_callback(db, "failed", 500)
                return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})

            url, self.error = self.get_entity_parent_uri(db, self.dbid, self.row)
            if not url:
                LOG.critical(_("%s: Provision failed - Unable to find parent's uri" % self.row["name"]))
                self.call_callback(db, "failed", 500)
                return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": 0})

            rest_me = entity_utils.post_entity(element, self.row["entitytype"], url)
            y = yurl.URL(url)
            slice_url = str(yurl.URL(scheme=y.scheme, host=y.host, port=y.port))
            if self.check_status(db, rest_me, slice_url + rest_me.get("uri", ""), slice_url=slice_url):
                #            if self.check_status(db, rest_me,
                #                                 self.slice_row["virtual_infrastructure_url"] + rest_me.get("uri", "")):
                return ujson.dumps({"result_code": rest_me.get("http_status_code", 500),
                                    "result_message": "http rest error", "dbid": self.dbid})

            entity_manager.entities[self.row["entitytype"]].post_rest_get_function(db, self.dbid, rest_me,
                                                                                   rest='post')
            if rest_me and "http_status_code" in rest_me.keys() and \
                            rest_me["http_status_code"] == 200 and "uri" in rest_me:
                self.update_all_service_uris(db, rest_me, options=options, slice_url=slice_url)

            rest_me.pop("name", None)
            cloud_utils.update_or_insert(db, "tblEntities", rest_me, {"id": self.dbid},
                                         child_table=entity_manager.entities[self.row["entitytype"]].child_table)

            return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": self.dbid})

        except:
            cloud_utils.log_exception(sys.exc_info())
        return ujson.dumps({"result_code": -1, "result_message": "%s" % self.error, "dbid": self.dbid})

    def update_all_service_uris(self, db, rest_me, options=None, slice_url=None):
        try:
            if not rest_me:
                return
            slice_url = slice_url or self.slice_row["virtual_infrastructure_url"]
            entity_utils.create_or_update_uri(db, self.row, self.dbid, slice_url,
                                              rest_me,
                                              uri_type="home", slice_dbid=self.slice_row["tblentities"])
            uris = {}
            if "compute_uri" in rest_me:
                uris["uri"] = rest_me.get("compute_uri", "")
                entity_utils.create_or_update_uri(db, None, self.dbid, slice_url,
                                                  uris, slice_dbid=self.slice_row["tblentities"], uri_type="compute")
            if "network_uri" in rest_me:
                uris["uri"] = rest_me.get("network_uri", "")
                entity_utils.create_or_update_uri(db, None, self.dbid, slice_url,
                                                  uris, slice_dbid=self.slice_row["tblentities"], uri_type="network")

            if "compute_uri" in rest_me:
                uris["uri"] = rest_me.get("storage_uri", "")
                entity_utils.create_or_update_uri(db, None, self.dbid, slice_url,
                                                  uris, slice_dbid=self.slice_row["tblentities"], uri_type="storage")

            if options and "usertype" in options and options["usertype"] == "developer":
                if "server_boot" in rest_me and "volume_id" in options:
                    cloud_utils.update_or_insert(db, "tblUris",
                                                 {"uri": slice_url + rest_me["server_boot"]["boot_volume"]["uri"],
                                                  "type": "home",
                                                  "tblEntities": options["volume_id"],
                                                  "tblSlices": self.slice_row["tblentities"]},
                                                 {"tblEntities": options["volume_id"]})

            if "interfaces" in rest_me:
                for j in cloud_utils.network_service_ports(db, self.dbid):
                    drow = cloud_utils.lower_key(db.get_row_dict("tblEntities", {"id": j["destinationserviceentityid"]},
                                                                 order="ORDER BY id LIMIT 1"))
                    found = False
                    for i in rest_me["interfaces"]:
                        if drow and "name" in i and "uri" in i and i["name"] == drow["name"]:
                            port = entity_utils.get_entity(slice_url + i["uri"])

                            # if "traffic_stats" in port:
                            #                                stats = self.slice_row["virtual_infrastructure_url"] + port ["traffic_stats"]
                            #                            else:
                            #                                stats = ""

                            #                            cloud_utils.update_only(db, "tblEntities",
                            #                                                        {"uri": self.slice_row["virtual_infrastructure_url"] +i["uri"],
                            #                                                         "statistics": stats},
                            #                                                         {"id": j["id"]}, child_table="tblServicePorts")

                            entity_utils.create_or_update_uri(db, self.row, j["id"],
                                                              slice_url,
                                                              port, uri_type="home",
                                                              slice_dbid=self.slice_row["tblentities"])

                            update_port = entity_manager.provision_network_service_ports(db, j["id"])
                            if update_port:
                                n = entity_utils.put_entity(update_port, "network_interface",
                                                            slice_url + i["uri"])
                                entity_utils.create_or_update_uri(db, self.row, j["id"],
                                                                  slice_url,
                                                                  n, uri_type="home",
                                                                  slice_dbid=self.slice_row["tblentities"])

                            found = True
                            break
                    if not found:
                        cloud_utils.log_message(db, self.dbid, "%s: Unable to find uri for interface %s " %
                                                (self.row["name"], drow["name"]))
                        LOG.critical(_("%s: Unable to find uri for interface %s" % (self.row["name"], drow["name"])))
        except:
            print sys.exc_info()
            cloud_utils.log_exception(sys.exc_info())

    def duplicate_name_check(self, db, options):
        check_row = db.execute_db("SELECT * FROM tblEntities WHERE (Name = '%s' AND EntityType = '%s' AND deleted = 0 AND \
                                   ParentEntityId = '%s' AND id != '%s')  ORDER By id LIMIT 1" %
                                  (options["name"], self.row["entitytype"], self.row["parententityid"], self.dbid))
        if check_row:
            LOG.critical(_("Update entity with duplicate name declined entity %s current name %s requested name %s" %
                           (self.dbid, self.row["name"], options["name"])))
            return "Update declined - Duplicate name error"
        return None

    def check_status(self, db, rest_me, url, ignore_pending=False, force_periodic=False, slice_url=None):
        if rest_me and "EntityStatus" in rest_me:
            if rest_me["EntityStatus"].lower() in entity_utils.http_error_states:
                self.call_callback(db, "failed", rest_me.get("http_status_code", 500), rest_me=rest_me)
                return rest_me.get("http_status_code", 500)

        slice_url = slice_url or self.slice_row["virtual_infrastructure_url"]
        if "uri" in rest_me:
            entity_utils.create_or_update_uri(db, self.row, self.dbid, slice_url,
                                              rest_me,
                                              uri_type="home", slice_dbid=self.slice_row["tblentities"])
            LOG.info(_("Updated - URI for tblEntities id %s" % (self.dbid)))

            if force_periodic or not rest_me or "EntityStatus" not in rest_me or rest_me["EntityStatus"].lower() in \
                    entity_manager.entities[self.row["entitytype"]].entity_pending_states:
                if not ignore_pending:
                    entity_utils.add_periodic_check(db, {"dbid": self.dbid, "url": url, "callback": self.callback,
                                                         "entity": self.row,
                                                         "return_object": self.return_object,
                                                         "slice_dbid": self.slice_row["tblentities"],
                                                         "slice_uri": slice_url})
                return None
            else:
                if entity_manager.entities[self.row["entitytype"]].post_entity_final_status_function:
                    entity_manager.entities[self.row["entitytype"]].post_entity_final_status_function(db, self.dbid
                                                                                                      )

                if rest_me and "EntityStatus" in rest_me and rest_me["EntityStatus"].lower() in entity_manager.entities[
                    self.row["entitytype"]].entity_failed_states:
                    self.call_callback(db, "failed", rest_me.get("http_status_code", 500), rest_me=rest_me)
                else:
                    self.call_callback(db, "success", rest_me.get("http_status_code", 200), rest_me=rest_me)
                return None
        else:
            self.call_callback(db, "failed", rest_me.get("http_status_code", 500), rest_me=rest_me)
            LOG.critical(_("Unable to locate Entity status or URI for tblEntities id %s in %s" % (self.dbid, rest_me)))

        self.call_callback(db, "failed", rest_me.get("http_status_code", 500), rest_me=rest_me)
        return rest_me.get("http_status_code", 500)

    def call_callback(self, db, return_status, http_status_code, rest_me=None):
        try:
            #            if self.jobid:
            #                cloud_utils.update_only(db, "tblEntities", {"progress": 100, "status": return_status,
            #                                                            "response": ujson.dumps(rest_me)},
            #                                        {"id": self.jobid}, child_table="tblJobsQueue")
            if self.callback:
                if self.return_object and isinstance(self.return_object, list):
                    self.return_object[-1]["http_status_code"] = http_status_code
                    self.return_object[-1]["response"] = rest_me
                eventlet.spawn_n(self.callback, self.dbid, return_status=return_status,
                                 return_object=self.return_object)
        except:
            cloud_utils.log_exception(sys.exc_info())

    def get_entity_uri(self, db, dbid, entity):
        uritype = "home"
        self.uri_row = cloud_utils.lower_key(db.get_row_dict("tblUris", {"tblEntities": dbid,
                                                                         "type": uritype,
                                                                         "deleted": 0},
                                                             order="ORDER BY id LIMIT 1"))
        if not self.uri_row:
            LOG.critical(_("Unable to locate URI for tblEntities id %s" % dbid))
            return None, "Unable to locate entity URI in tblUris database"

        self.slice_row = cloud_utils.lower_key(db.get_row_dict("tblSlices", {"tblEntities": self.uri_row["tblslices"]},
                                                               order="ORDER BY id LIMIT 1"))
        if not self.slice_row:
            LOG.critical(
                _("Unable to locate slice for tblEntities  uriid %s entity id  %s" % (self.uri_row["id"], dbid)))
            return None, "Unable to locate entry URI in tblslices in database"
        return self.uri_row["uri"], None

    def get_entity_parent_uri(self, db, dbid, entity):
        uritype = "home"
        if entity["entitytype"] in entity_manager.entities.keys():
            uritype = entity_manager.entities[entity["entitytype"]].parent_uri_type

        self.parent_uri_row = cloud_utils.lower_key(db.get_row_dict("tblUris", {"tblEntities": entity["parententityid"],
                                                                                "type": uritype, "deleted": 0},
                                                                    order="ORDER BY id LIMIT 1"))
        if not self.parent_uri_row:
            if entity["entitytype"] == "storage_class" or \
                            entity["entitytype"] == "compute_class" or \
                            entity["entitytype"] == "network_class":
                if self.slice_row:
                    return self.slice_row["physical_infrastructure_url"], None

            if entity["entitytype"] == "organization" and self.slice_row:
                return self.slice_row["virtual_infrastructure_url"], None

            LOG.critical(_("Unable to locate URI for tblEntities id %s" % entity["parententityid"]))
            return None, "Unable to locate parent entity in database"

        if not self.slice_row:
            self.slice_row = cloud_utils.lower_key(db.get_row_dict("tblSlices",
                                                                   {"tblEntities": self.parent_uri_row["tblslices"]},
                                                                   order="ORDER BY id LIMIT 1"))
            if not self.slice_row:
                LOG.critical(
                    _("Unable to locate slice for tblEntities uriid %s entity id  %s " % (self.parent_uri_row["id"],
                                                                                          entity["parententityid"])))
                return None, "Unable to locate entry in tblslices in database"
        if not self.slice_row["virtual_infrastructure_url"] or not self.parent_uri_row["uri"]:
            return None, "Unable to get slice uri %s or parent uri %s" % (self.slice_row["virtual_infrastructure_url"],
                                                                          self.parent_uri_row["uri"])
        return self.parent_uri_row["uri"], None

    functionMap = {
        "create": _create,
        "delete": _delete,
        "update": _update,
        "status": _status,
        "command": _command,
        "provision": _provision,
        "post": _post
    }


def entity_command_completed(dbid, return_status=None, return_object=None):
    try:
        if return_object and isinstance(return_object, list):
            LOG.info(_("job completed for dbid:  %s" % dbid))
        else:
            LOG.critical(_("Unable to locate the eventfunction for dbid:  %s" % dbid))
    except:
        cloud_utils.log_exception(sys.exc_info())


def user_login(db, dbid, function, options=None):
    error = entity_utils.confirm_options_keys(options, ["loginid", "password"])
    if error:
        return ujson.dumps({"result_code": -1, "result_message": "%s" % error, "dbid": 0})

    system_row = cache_utils.get_cache("db|tblEntities|EntityType|System", None, db_in=db)

    dbid = cfd_keystone.cfd_keystone.login(db, options["loginid"], options["password"])
    if dbid == 0:
        cloud_utils.log_message(db, system_row["id"],
                                "User id %s login attempt rejected from IP address: %s" %
                                (options["loginid"], options.get("ipaddress", "0.0.0.0")))

        return ujson.dumps({"result_code": -1, "result_message": "Login rejected", "dbid": 0})

    user = cache_utils.get_cache("db|tblEntities|id|%s" % dbid, None, db_in=db)
    cloud_utils.log_message(db, system_row["id"],
                            "User %s with login id %s login successful from IP address: %s" %
                            (user["name"], options["loginid"], options.get("ipaddress", "0.0.0.0")))
    db.execute_db("UPDATE tblUsers SET LastActivityDate =now()  WHERE tblEntities = '%s' " % user["id"])
    entity_utils.update_developer_resources(db, user["id"])
    return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": dbid})


def user_functions(db, dbid, function, options=None):
    if not options or "status" not in options or options["status"] != "logout" or "user_row" not in options:
        return ujson.dumps({"result_code": -1, "result_message": "Invalid user functiona call", "dbid": dbid})

    system_row = cache_utils.get_cache("db|tblEntities|EntityType|System", None, db_in=db)

    user = cloud_utils.lower_key(db.get_row_dict("tblUsers",
                                                 {"tblEntities": options["user_row"]["id"]},
                                                 order="ORDER BY id LIMIT 1"))

    if user:
        cloud_utils.log_message(db, system_row["id"], "User %s login id %s logged out" %
                                (options["user_row"]["name"], user["loginid"]))
        cache_utils.remove_cache("db-tblEntities-id-%s" % options["user_row"]["id"])
        db.execute_db("UPDATE tblUsers SET Token =NULL WHERE tblEntities = '%s' " % user["id"])
    return ujson.dumps({"result_code": 0, "result_message": "success", "dbid": dbid})


def find_organization(dbid):
    for index, value in enumerate(organization_objects):
        if value["dbid"] == dbid:
            return value
    return None


def update_user_assigned_resource_records(db, dbid, options):
    if not options:
        return
    if not "resources" in options:
        return
    resources = options["resources"]
    print resources
    for i in resources:
        if not "catagory" in i:
            continue
        if not isinstance(i, dict):
            continue
        if i["catagory"] == "compute":

            current = db.get_row("tblResourcesCompute", "Catagory='total' AND tblEntities='%s'" % dbid)
            if not "cpu" in i:
                i["cpu"] = current["CPU"]
            if not "ram" in i:
                i["ram"] = current["RAM"]
            if not "network" in i:
                i["network"] = current["Network"]

            db.update_db("UPDATE tblResourcesCompute SET  CPU='%s', RAM='%s', Network='%s' "
                         " WHERE Catagory='total' AND tblEntities='%s'" %
                         (i.get("cpu", 0), i.get('ram', 0), i.get("network", 0), dbid))
            continue
        if i["catagory"] == "storage" and "type" in i:

            current = db.get_row("tblResourcesStorage",
                                 "Catagory='total' AND tblEntities='%s'AND type='%s'" % (dbid, i["type"]))

            if not "capacity" in i:
                i["capacity"] = current["Capacity"]

            if not "iops" in i:
                i["iops"] = current["IOPS"]

            if not "network" in i:
                i["network"] = current["Network"]

            db.update_db("UPDATE tblResourcesStorage SET capacity='%s', iops='%s', Network='%s'"
                         " WHERE Catagory='total' AND tblEntities='%s'AND type='%s' " %
                         (i.get("capacity", 0), i.get("iops", 0), i.get("network", 0), dbid, i["type"]))
            continue

        if i["catagory"] == "network" and "type" in i:
            db.update_db("UPDATE tblResourcesNetwork SET throughput='%s' "
                         "WHERE Catagory = 'total' AND tblEntities='%s'AND type='%s' " %
                         (i.get("throughput", 0), dbid, i["type"]))


def initialize_resource_records(db, dbid, entittype, parententityid):
    row = db.get_row_dict("tblResourcesCompute", {"tblEntities": dbid, "type": "default"},
                          order="ORDER BY id LIMIT 1")
    if not row:
        db.update_db(
            "INSERT INTO tblResourcesCompute (tblEntities, Catagory, TypeTitle, Type,CPU, RAM, Network, Entitytype, ParentEntityId) "
            "VALUES ('%s','total','Compute','Default','0','0','0', '%s','%s')" % (dbid, entittype, parententityid))
        db.update_db(
            "INSERT INTO tblResourcesCompute (tblEntities, Catagory, TypeTitle, Type,CPU, RAM, Network, Entitytype, ParentEntityId) "
            "VALUES ('%s','allocated','Compute','Default','0','0','0', '%s','%s')" % (dbid, entittype, parententityid))
        db.update_db(
            "INSERT INTO tblResourcesCompute (tblEntities, Catagory, TypeTitle, Type,CPU, RAM, Network, Entitytype, ParentEntityId) "
            "VALUES ('%s','deployed','Compute','Default','0','0','0', '%s','%s')" % (dbid, entittype, parententityid))

    for item in storage_types:
        row = db.get_row_dict("tblResourcesStorage", {"tblEntities": dbid, "type": item},
                              order="ORDER BY id LIMIT 1")
        if not row:
            db.update_db("INSERT INTO tblResourcesStorage "
                         "(tblEntities, Catagory, TypeTitle, Type, capacity, iops, Network, Entitytype, ParentEntityId) "
                         "VALUES ('%s','total', 'Latency','%s','0','0','0', '%s','%s') " % (
                             dbid, item, entittype, parententityid))
            db.update_db("INSERT INTO tblResourcesStorage "
                         "(tblEntities, Catagory, TypeTitle, Type, capacity, iops, Network, Entitytype, ParentEntityId) "
                         "VALUES ('%s','allocated', 'Latency','%s','0','0','0', '%s','%s') " % (
                             dbid, item, entittype, parententityid))
            db.update_db("INSERT INTO tblResourcesStorage "
                         "(tblEntities, Catagory, TypeTitle, Type, capacity, iops, Network, Entitytype, ParentEntityId) "
                         "VALUES ('%s','deployed', 'Latency','%s','0','0','0', '%s','%s') " % (
                             dbid, item, entittype, parententityid))

    for item in entity_constants.network_services:
        row = db.get_row_dict("tblResourcesNetwork", {"tblEntities": dbid, "type": item},
                              order="ORDER BY id LIMIT 1")
        if not row:
            db.update_db(
                "INSERT INTO tblResourcesNetwork (tblEntities, Catagory, TypeTitle, Type, throughput, Entitytype, ParentEntityId) "
                "VALUES ('%s','total', 'Network Service','%s','0', '%s','%s') " % (
                    dbid, item, entittype, parententityid))
            db.update_db(
                "INSERT INTO tblResourcesNetwork (tblEntities, Catagory, TypeTitle, Type, throughput, Entitytype, ParentEntityId) "
                "VALUES ('%s','allocated', 'Network Service','%s','0', '%s','%s') " % (
                    dbid, item, entittype, parententityid))
            db.update_db(
                "INSERT INTO tblResourcesNetwork (tblEntities, Catagory, TypeTitle, Type, throughput, Entitytype, ParentEntityId) "
                "VALUES ('%s','deployed', 'Network Service','%s','0', '%s','%s') " % (
                    dbid, item, entittype, parententityid))


def update_entity_resource_records(db, dbid, to_catagory, from_entity_type, from_catagory):
    try:
        cores = 0
        mhz = 0
        ram = 0
        cnetwork = 0
        capacity = {}
        iops = {}
        snetwork = {}
        for i in storage_types:
            capacity[i] = 0
            iops[i] = 0
            snetwork[i] = 0
        thru = {}
        for i in entity_constants.network_services:
            thru[i] = 0
        for item in cloud_utils.entity_children(db, dbid, entitytype=from_entity_type):
            # update compute resources
            row = cloud_utils.lower_key(db.get_row_dict("tblResourcesCompute", {'tblEntities': item['id'],
                                                                                'Catagory': from_catagory},
                                                        order="ORDER BY id LIMIT 1"))
            if row:
                cores += row['cpu']
                ram += row['ram']
                cnetwork += row['network']

            for i in storage_types:
                row = cloud_utils.lower_key(db.get_row_dict("tblResourcesStorage", {'tblEntities': item['id'],
                                                                                    'type': i,
                                                                                    'Catagory': from_catagory},
                                                            order="ORDER BY id LIMIT 1"))
                if row:
                    capacity[i] += row['capacity']
                    iops[i] += row['iops']
                    snetwork[i] += row['network']

            for i in entity_constants.network_services:
                row = cloud_utils.lower_key(db.get_row_dict("tblResourcesNetwork", {'tblEntities': item['id'],
                                                                                    'type': i,
                                                                                    'Catagory': from_catagory},
                                                            order="ORDER BY id LIMIT 1"))
                if row:
                    thru[i] += row['throughput']

        db.update_db("UPDATE tblResourcesCompute SET CPU='%s', RAM='%s', Network='%s' "
                     "WHERE Catagory = '%s' AND tblEntities='%s'" %
                     (cores, ram, cnetwork, to_catagory, dbid))

        for i in storage_types:
            db.update_db("UPDATE tblResourcesStorage SET Type='%s', capacity='%s', iops='%s', Network='%s'"
                         "  WHERE Catagory ='%s' AND tblEntities='%s'AND type='%s' " %
                         (i, capacity[i], iops[i], snetwork[i], to_catagory, dbid, i))

        for i in entity_constants.network_services:
            db.update_db("UPDATE tblResourcesNetwork SET Type='%s', throughput='%s' "
                         " WHERE Catagory ='%s' AND tblEntities='%s'AND type='%s' " %
                         (i, thru[i], to_catagory, dbid, i))
    except:
        cloud_utils.log_exception(sys.exc_info())
