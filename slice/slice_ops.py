#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import eventlet
import json
import yurl
import threading

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

import rest.rest_api as rest_api
from utils.underscore import _
import entity.entity_functions
import entity.entity_utils
import entity.entity_manager
import entity.entity_constants
import utils.cloud_utils as cloud_utils
import organization.organization_ops as organization

LOG = logging.getLogger('hawk-rpc')


class Slice(object):
    def __init__(self, db, dbid, user_info=None, LOG=LOG):

        self.instance_lock = threading.RLock()
        self.LOG = LOG
        self.dbid = dbid
        self.user_info = user_info
        self.db_entity = None
        self.db_slice = None
        self.rest_system = None

        self.slice_virtual_home = None

        self.rest_slice = None
        self.rest_slice_uri = None

        self.rest_hosts_uri = None
        self.rest_hosts = None
        self.compute_objects = {}

        self.rest_storages_uri = None
        self.rest_storages = None
        self.storage_objects = {}

        self.rest_networkentities_uri = None
        self.rest_networkentities = None
        self.network_objects = {}

        self.rest_external_clouds_uri = None
        self.rest_external_clouds = None
        self.external_cloud_objects = {}

        self.rest_attached_networks_uri = None
        self.rest_attached_networks = None
        self.attached_network_objects = {}

        self.rest_image_libraries_uri = None
        self.rest_image_libraries = None
        self.image_library_objects = {}
        self.cfd_created_at = None

        self.get_database(db)

    def get_database(self, db):

        self.db_entity = db.get_row("tblEntities", "id='%s' AND deleted = 0" % self.dbid)
        if self.db_entity is None:
            LOG.critical(_("Invalid database ID:%s Unable to locate row in database" % self.dbid))
            return
        self.db_entity = cloud_utils.lower_key(self.db_entity)
        self.db_slice = db.get_row("tblSlices", "tblEntities='%s'" % (self.db_entity["id"]),
                                   order="ORDER BY id LIMIT 1")
        self.db_slice = cloud_utils.lower_key(self.db_slice)

    def update(self, db, user_info=None):
        with self.instance_lock:
            try:
                # ensure that slice is still in DB
                check = db.get_row("tblEntities", "id='%s' AND deleted = 0" % self.dbid)
                if check is None:
                    LOG.warn(_("Skipping update - Invalid database ID:%s Unable to locate row in database" % self.dbid))
                    return
                if user_info is not None:
                    # Don't allow changes in name and URL
                    self.user_info = user_info
                    self.user_info["entitytype"] = "slice"
                    self.user_info["name"] = self.db_entity["name"]
                    self.user_info['url'] = self.db_slice["url"]
                    cloud_utils.update_only(db, "tblEntities", self.user_info, {"id": self.dbid},
                                            child_table="tblSlices")
                self.status(db)
                if self.rest_slice_uri is None:
                    return None
                time_clause = {"field": "updated_at", "check": "<", "time": "%s" % (db.get_time_stamp("NOW()")['time'])}
                pool = eventlet.GreenPool()
                pool.spawn_n(organization.sync_organizations, self.db_slice, self.slice_virtual_home,
                             self.rest_slice['virtual_infrastructure_url'], self.dbid, LOG=self.LOG)
                pool.spawn_n(self.compute_entities_update, time_clause, LOG=self.LOG)
                pool.spawn_n(self.storage_entities_update, time_clause, LOG=self.LOG)
                pool.spawn_n(self.slice_network_entities_update, time_clause, LOG=self.LOG)
                pool.spawn_n(self.slice_attached_networks_update, time_clause, LOG=self.LOG)
                pool.spawn_n(self.cloud_entities_update, time_clause, LOG=self.LOG)
                pool.spawn_n(self.slice_libraries_update, time_clause, LOG=self.LOG)

                pool.waitall()
            except:
                cloud_utils.log_exception(sys.exc_info(), LOG=self.LOG)
            db.update_db(
                "UPDATE tblSlices SET  lastresynctime=NOW(), resyncinprogress=0 WHERE id= %s" % self.db_slice["id"])
            return self.rest_slice

    def status(self, db):
        with self.instance_lock:
            try:
                self.get_slice(db)

                # ensure that slice is still in DB
                check = db.get_row("tblEntities", "id='%s' AND deleted = 0" % self.dbid)
                if check is None:
                    LOG.warn(_("Skipping status - Invalid database ID:%s Unable to locate row in database" % self.dbid))
                    return

                    # Override any fields received fro CFD with fields from GUI user
                if self.user_info is not None:
                    for field in self.user_info:
                        self.rest_slice[field] = self.user_info[field]

                if "virtual_mgmt_port" in self.rest_slice and "physical_mgmt_port" in self.rest_slice:
                    self.rest_slice['virtual_infrastructure_url'] = \
                        str(yurl.URL(self.db_slice["url"]).replace(port="%s" % self.rest_slice['virtual_mgmt_port']))
                    self.rest_slice['physical_infrastructure_url'] = \
                        str(yurl.URL(self.db_slice["url"]).replace(port="%s" % self.rest_slice['physical_mgmt_port']))

                    try:
                        self.slice_virtual_home = rest_api.get_rest(self.rest_slice['virtual_infrastructure_url'] + "/")
                    # self.sync_organizations(db)
                    except:
                        cloud_utils.log_exception(sys.exc_info())

                    if not self.slice_virtual_home:
                        LOG.critical(_("Unable to contact slice virtual at url=%s" %
                                       self.rest_slice["virtual_infrastructure_url"]))
                        # do not allow CFD to update slice name or description
                self.rest_slice.pop("name", None)
                self.rest_slice.pop("description", None)

                cloud_utils.update_only(db, "tblEntities", self.rest_slice, {"id": self.dbid},
                                        child_table="tblSlices")
                self.get_database(db)
                return self.rest_slice["resource_state"]

            except:
                cloud_utils.log_exception(sys.exc_info(), LOG=self.LOG)

    def inactive_state(self):
        self.rest_system = {}
        self.rest_slice = {"resource_state": {"state": "Inactive"}, "uuid": cloud_utils.generate_uuid()}
        self.rest_slice_uri = None

    def get_slice(self, db):
        with self.instance_lock:
            try:
                self.rest_system = rest_api.get_rest(self.db_slice["url"])

                if "created" in self.rest_system:
                    self.cfd_created_at = self.rest_system["created"]
                if "class_list" in self.rest_system:
                    eventlet.spawn_n(self.classes_update, LOG=self.LOG)

                if "slices" in self.rest_system and "elements" in self.rest_system["slices"]:
                    self.rest_slice_uri = self.db_slice["url"] + self.rest_system["slices"]["elements"][0]["uri"]
                    self.rest_slice = rest_api.get_rest(self.rest_slice_uri)
                    if "resource_state" not in self.rest_slice.keys():
                        self.inactive_state()
                else:
                    self.inactive_state()
            except:
                cloud_utils.log_exception(sys.exc_info())

            if self.rest_slice_uri is None:
                LOG.critical(_("Unable to locate slice url=%s response=%s" % (self.db_slice["url"], self.rest_system)))
            if "resource_state" in self.rest_slice.keys() and "state" in self.rest_slice["resource_state"].keys():
                self.rest_slice["EntityStatus"] = self.rest_slice["resource_state"]["state"]
                self.rest_slice.pop("name", None)
                self.rest_slice.pop("description", None)
                if "uuid" in self.rest_slice:
                    self.rest_slice["uniqueid"] = self.rest_slice["uuid"]
                else:
                    self.rest_slice["uniqueid"] = cloud_utils.generate_uuid()

                if "implementation_version" in self.rest_slice:
                    self.rest_slice["firmware_version"] = self.rest_slice["implementation_version"]

                if "created_at" in self.rest_system:
                    self.rest_slice["slice_created_at"] = self.rest_system["created_at"]

                if "updated_at" in self.rest_system:
                    self.rest_slice["slice_updated_at"] = self.rest_system["updated_at"]

                cloud_utils.update_only(db, "tblEntities", self.rest_slice, {"id": self.dbid},
                                        child_table="tblSlices")

                dup_check = db.get_row("tblEntities",
                                       "id != '%s' AND entitytype='slice' AND uniqueid='%s' AND deleted = 0" % (
                                           self.dbid, self.rest_slice["uniqueid"]))
                if dup_check:
                    self.rest_system = {}
                    self.rest_slice["resource_state"] = {"state": "Duplicate"}
                    cloud_utils.update_only(db, "tblEntities", {"EntityStatus": "Duplicate"}, {"id": self.dbid})
                    self.rest_slice_uri = None

                entity.entity_utils.create_or_update_uri(db, None, self.dbid, self.db_slice["url"],
                                                         self.rest_slice, slice_dbid=self.dbid, uri_type="home")

            return self.rest_slice_uri

    def get_slice_virtual_home_url(self):
        if self.rest_slice and "virtual_infrastructure_url" in self.rest_slice:
            return self.rest_slice['virtual_infrastructure_url']
        return None

    def get_slice_virtual_home(self):
        if self.rest_slice and "virtual_infrastructure_url" in self.rest_slice:
            return self.slice_virtual_home
        return None

    def get_name(self):
        if self.db_entity and "name" in self.db_entity:
            return self.db_entity["name"]
        return None

    def delete(self, db):
        with self.instance_lock:
            # ensure that slice is still in DB
            #            check = db.get_row("tblEntities", "id='%s' AND deleted = 0" % self.dbid)
            #            if check is None:
            #                LOG.warn(_("Skipping delete - Invalid database ID:%s Unable to locate row in database" % self.dbid))
            #                return
            self.compute_entities_delete(db)
            self.storage_entities_delete(db)
            #            self.network_entities_delete(db)
            #            self.attached_networks_delete(db)
            self.cloud_entities_delete(db)
            #            self.image_libraries_delete(db)
            db.delete_rows_dict("tblUris", {"tblslices": self.dbid})
            entity.entity_utils.delete_entity_recursively(db, self.dbid)
            #           db.delete_rows_dict("tblEntities", {"id": self.dbid})

    def inactivate(self, db):
        pass

    def sync_organizations(self, db):
        pool = eventlet.GreenPool()
        pool.spawn_n(organization.sync_organizations, self.slice_virtual_home,
                     self.rest_slice['virtual_infrastructure_url'], self.dbid)
        pool.waitall()
        return
        rest_elements = entity.entity_utils.get_entity_dict(db, self.slice_virtual_home, "organizations")
        if rest_elements is None:
            LOG.critical(_("No organizations in parent response %s" % self.slice_virtual_home))
            return
        for item in cloud_utils.entity_children(db, self.db_entity["parententityid"], entitytype="organization"):
            if item["name"] in rest_elements.keys():
                # found in db and cfd - we will keep it
                del rest_elements[item["name"]]
            else:
                # found in db but not in cfd
                pass

        update = False
        # delete element found in CFD but not in user database
        for name, uri in rest_elements.iteritems():
            entity.entity_utils.delete_entity(self.rest_slice['virtual_infrastructure_url'] + uri)
            LOG.warn(_("Deleting excess organization %s from %s  with uri %s" % (name, self.slice_virtual_home, uri)))
            update = True

        if update:
            self.slice_virtual_home = rest_api.get_rest(self.rest_slice['virtual_infrastructure_url'] + "/")

    def compute_entities_update(self, time_clause, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            self.rest_hosts_uri = self.db_slice["url"] + self.rest_slice["hosts"]
            self.rest_hosts = rest_api.get_rest(self.rest_hosts_uri)
            if self.rest_hosts["http_status_code"] != 200:
                return
            new_objects = {}
            pool = eventlet.GreenPool()
            if "hosts" in self.rest_hosts and "total" in self.rest_hosts["hosts"] and \
                            self.rest_hosts["hosts"]["total"] > 0:
                if "elements" in self.rest_hosts["hosts"]:
                    LOG.info(_("found %s current object as %s " % (len(self.compute_objects), self.compute_objects)))
                    for item in self.rest_hosts["hosts"]["elements"]:
                        if item["name"] in self.compute_objects.keys():
                            new_objects[item["name"]] = self.compute_objects[item["name"]]
                            del self.compute_objects[item["name"]]
                        else:
                            new_objects[item["name"]] = ComputeEntities(self.dbid, item["name"],
                                                                        self.db_slice["url"], item["uri"])
                        pool.spawn_n(new_objects[item["name"]].update, uri=item["uri"])
                else:
                    LOG.critical(_("Unable to locate elements in: %s with count > 0" % self.rest_hosts))
            else:
                LOG.info(_("Unable to locate hosts or total in: %s" % self.rest_hosts))
            LOG.info(_("deleting %s current object as %s " % (len(self.compute_objects), self.compute_objects)))
            # delete any compute entries for which an object is present but it was not received from CFD
            for item in self.compute_objects:
                self.compute_objects[item].delete(db)
            self.compute_objects = new_objects
            pool.waitall()
            # delete any stale entries from the database (if an entry is not updated, it must be stale)
            while True:
                row = db.get_row_dict("tblEntities",
                                      {"ParentEntityId": self.dbid, "Entitytype": "slice_compute_entity"},
                                      time_clause=time_clause)
                if row is None:
                    break
                # row = cloud_utils.lower_key(row)
                LOG.warn(_("deleting stale entity  time clause %s " % time_clause))
                LOG.warn(_("deleting stale entity - row is %s " % row))
                #                db.delete_rows_dict("tblEntities", {"id": row['id']})
                db.update_db(
                    "UPDATE tblEntities SET updated_at=now(), entitystatus='Unavailable' WHERE id = %s" % row['id'])


            # update compute resources for this slice
            sums = db.execute_db("SELECT SUM(tblComputeEntities.mhz), "

                                 "SUM(tblComputeEntities.vcpu), "

                                 "SUM(tblComputeEntities.memory), "
                                 "SUM(tblComputeEntities.totalbandwidth) "
                                 "FROM tblEntities JOIN tblComputeEntities "
                                 "WHERE tblEntities.deleted=0 AND tblEntities.id = tblComputeEntities.tblEntities AND "
                                 "tblEntities.EntityType = 'slice_compute_entity' AND  tblEntities.entitystatus='Active' and "
                                 "tblEntities.ParentEntityId = %s" % self.dbid)
            sums = cloud_utils.lower_key(sums[0])
            cores = 0
            mhz = 0
            ram = 0
            net = 0
            if sums:
                if "sum(tblcomputeentities.mhz)" in sums and sums["sum(tblcomputeentities.mhz)"]:
                    mhz = sums["sum(tblcomputeentities.mhz)"]
                if "sum(tblcomputeentities.vcpu)" in sums and sums["sum(tblcomputeentities.vcpu)"]:
                    cores = sums["sum(tblcomputeentities.vcpu)"]
                if "sum(tblcomputeentities.memory)" in sums and sums["sum(tblcomputeentities.memory)"]:
                    ram = sums["sum(tblcomputeentities.memory)"]
                if "sum(tblcomputeentities.totalbandwidth)" in sums and sums["sum(tblcomputeentities.totalbandwidth)"]:
                    net = sums["sum(tblcomputeentities.totalbandwidth)"]

            db.update_db("UPDATE tblResourcesCompute SET  CPU='%s', RAM='%s', Network='%s' WHERE "
                         "Catagory='total' AND tblEntities='%s'" %
                         (cores, ram, net, self.dbid))
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()

    def compute_entities_delete(self, db, LOG=LOG):
        for item in self.compute_objects:
            self.compute_objects[item].delete(db)
        self.compute_objects = {}

    def storage_entities_update(self, time_clause, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            self.rest_storages_uri = self.db_slice["url"] + self.rest_slice["storage_devices"]
            self.rest_storages = rest_api.get_rest(self.rest_storages_uri)
            if self.rest_storages["http_status_code"] != 200:
                return
            new_objects = {}
            pool = eventlet.GreenPool()
            if "storage" in self.rest_storages and "total" in self.rest_storages["storage"] and \
                            self.rest_storages["storage"]["total"] > 0:
                if "elements" in self.rest_storages["storage"]:
                    for item in self.rest_storages["storage"]["elements"]:
                        if item["name"] in self.storage_objects.keys():
                            new_objects[item["name"]] = self.storage_objects[item["name"]]
                            del self.storage_objects[item["name"]]
                        else:
                            new_objects[item["name"]] = StorageEntities(self.dbid, item["name"], self.db_slice["url"],
                                                                        item["uri"])
                        pool.spawn_n(new_objects[item["name"]].update, uri=item["uri"])
                else:
                    LOG.critical(_("Unable to locate elements in: %s with count > 0" % self.rest_storages))
            else:
                LOG.info(_("Unable to locate stors, total in: %s" % self.rest_storages))
            for item in self.storage_objects:
                self.storage_objects[item].delete(db)
            self.storage_objects = new_objects
            pool.waitall()
            # delete any stale entries from the database (if an entry is not updated, it must be stale)
            while True:
                row = db.get_row_dict("tblEntities",
                                      {"ParentEntityId": self.dbid, "Entitytype": "slice_storage_entity"},
                                      time_clause=time_clause)
                if row is None:
                    break
                LOG.info(_("Deleting stale stor id: %s" % row['id']))
                db.update_db(
                    "UPDATE tblEntities SET updated_at=now(), entitystatus='Unavailable' WHERE id = %s" % row['id'])
            # db.delete_rows_dict("tblEntities", {"id": row['id']})


            # update storage resources for this slice
            sums = db.execute_db("SELECT SUM(tblStorageEntities.totalstorage), "
                                 "SUM(tblStorageEntities.totaliops), "
                                 "SUM(tblStorageEntities.totalbandwidth) "
                                 "FROM tblEntities JOIN tblStorageEntities "
                                 "WHERE tblEntities.deleted=0 "
                                 "AND tblEntities.id = tblStorageEntities.tblEntities  "
                                 "AND tblEntities.EntityType = 'slice_storage_entity' "
                                 "AND tblEntities.ParentEntityId= %s" % self.dbid)

            sums = cloud_utils.lower_key(sums[0])
            capacity = 0
            iops = 0
            network = 0
            if sums:
                if "sum(tblstorageentities.totalstorage)" in sums and sums["sum(tblstorageentities.totalstorage)"]:
                    capacity = sums["sum(tblstorageentities.totalstorage)"]
                if "sum(tblstorageentities.totaliops)" in sums and sums["sum(tblstorageentities.totaliops)"]:
                    iops = sums["sum(tblstorageentities.totaliops)"]
                if "sum(tblstorageentities.totalbandwidth)" in sums and sums["sum(tblstorageentities.totalbandwidth)"]:
                    network = sums["sum(tblstorageentities.totalbandwidth)"]

            storage_type = "gold"
            storage_type_title = "Latency"

            db.update_db(
                "UPDATE tblResourcesStorage SET TypeTitle='%s', Type='%s', capacity='%s', iops='%s', Network='%s'"
                " WHERE Catagory='total' AND  tblEntities='%s'AND type='%s' " %
                (storage_type_title, storage_type, capacity, iops, network, self.dbid, storage_type))
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()

    def storage_entities_delete(self, db):
        for item in self.storage_objects:
            self.storage_objects[item].delete(db)
        self.storage_objects = {}

    cfd_2_hawk_keys = {"cloudflow_appliances": "cloudflow_director",
                       "firewalls": "slice_fws_service",
                       "ipss": "slice_ips_service",
                       "loadbalancers": "slice_lbs_service",
                       "nats": "slice_nat_service",
                       "routers": "slice_rts_service",
                       "switches": "slice_switch_service",
                       "ssl_accelerator": "slice_sslaccelerator_service",
                       "vpn": "slice_ipsecvpn_service",
                       "nms": "slice_nms_service",
                       "wan_accelerator": "slice_wan_service"}

    def slice_network_entities_update(self, time_clause, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            self.rest_networkentities_uri = self.db_slice["url"] + self.rest_slice["network_devices"]
            self.rest_networkentities = rest_api.get_rest(self.rest_networkentities_uri)
            if self.rest_networkentities["http_status_code"] != 200:
                return
            pool = eventlet.GreenPool()
            for devicetype, devicespecs in self.rest_networkentities.items():
                if devicetype not in self.cfd_2_hawk_keys:
                    continue

                if isinstance(devicespecs, dict) and "elements" in devicespecs:
                    for item in devicespecs["elements"]:
                        pool.spawn(update_net_entity, self.cfd_2_hawk_keys[devicetype], self.dbid, self.db_slice["url"],
                                   item["uri"], self.dbid)

            pool.waitall()

            # delete any stale entries from the database (if an entry is not updated, it must be stale)
            while True:
                row = db.get_row_dict("tblEntities",
                                      {"ParentEntityId": self.dbid, "EntitySubtype": "slice_network_entity"},
                                      time_clause=time_clause)
                if row is None:
                    break
                LOG.info(_("Deleting stale network id: %s" % row['id']))
                db.update_db(
                    "UPDATE tblEntities SET updated_at=now(), entitystatus='Unavailable' WHERE id = %s" % row['id'])
            # db.delete_rows_dict("tblEntities", {"id": row['id']})


            # update network resources for this slice
            #            network_services = ["vpn", "firewall", "ssl", "nat", "loadbalancer", "ips", "wan", "ethernetswitch",
            #                                "router"]
            for svc in entity.entity_constants.network_services:

                sums = db.execute_db("SELECT SUM(tblNetworkEntities.totalthroughput), "
                                     "SUM(tblNetworkEntities.totalbandwidth) "
                                     "FROM tblEntities JOIN tblNetworkEntities "
                                     "WHERE tblEntities.deleted=0 "
                                     "AND tblEntities.id = tblNetworkEntities.tblEntities  "
                                     "AND tblEntities.EntitySubType = 'slice_network_entity' "
                                     "AND tblEntities.ParentEntityId = '%s' AND  "
                                     "LOWER(tblNetworkEntities.DeviceFunction) = LOWER('%s')" % (self.dbid, svc))

                sums = cloud_utils.lower_key(sums[0])
                thru = 0
                network = 0
                if sums:
                    if "sum(tblnetworkentities.totalthroughput)" in sums and sums[
                        "sum(tblnetworkentities.totalthroughput)"]:
                        thru = sums["sum(tblnetworkentities.totalthroughput)"]
                    if "sum(tblnetworkentities.totalbandwidth)" in sums and sums[
                        "sum(tblnetworkentities.totalbandwidth)"]:
                        network = sums["sum(tblnetworkentities.totalbandwidth)"]
                network_type = svc
                network_type_title = "Network Service"

                db.update_db("UPDATE tblResourcesNetwork SET TypeTitle='%s', Type='%s', throughput='%s' "
                             "WHERE Catagory='total' AND tblEntities='%s'AND type='%s' " % (
                                 network_type_title, network_type,
                                 thru, self.dbid, network_type))
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()

    def slice_attached_networks_update(self, time_clause, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            self.rest_attached_networks_uri = self.db_slice["url"] + self.rest_slice["external_networks"]
            self.rest_attached_networks = rest_api.get_rest(self.rest_attached_networks_uri)
            if self.rest_attached_networks["http_status_code"] != 200:
                return
            new_objects = {}
            pool = eventlet.GreenPool()
            if "networks" in self.rest_attached_networks.keys() and \
                            "elements" in self.rest_attached_networks["networks"].keys() and \
                            "uri" in self.rest_attached_networks["networks"]:

                rest_attached = rest_api.get_rest(self.db_slice["url"] + self.rest_attached_networks["networks"]["uri"])
                if "networks" in rest_attached:
                    for item in rest_attached["networks"]:
                        pool.spawn(update_attached_network_entity, db, self.dbid, self.db_slice["url"], item["uri"],
                                   self.dbid)
                else:
                    LOG.critical(_("Unable to locate networks in: %s" % rest_attached))
            pool.waitall()
            # delete any stale entries from the database (if an entry is not updated, it must be stale)
            while True:
                row = db.get_row_dict("tblEntities",
                                      {"ParentEntityId": self.dbid, "Entitytype": "slice_attached_network"},
                                      time_clause=time_clause)
                if row is None:
                    break
                LOG.info(_("Deleting stale attached network id: %s" % row['id']))
                entity.entity_utils.delete_entity_recursively(db, row['id'])
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()

    def cloud_entities_update(self, time_clause, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            self.rest_external_clouds_uri = self.db_slice["url"] + self.rest_slice["public_clouds"]
            self.rest_external_clouds = rest_api.get_rest(self.rest_external_clouds_uri)
            if self.rest_external_clouds["http_status_code"] != 200:
                return
            new_objects = {}
            pool = eventlet.GreenPool()
            if "total" in self.rest_external_clouds and self.rest_external_clouds["total"] > 0 and \
                            "elements" in self.rest_external_clouds:
                for devicetype, devicespecs in self.rest_external_clouds.items():
                    if isinstance(devicespecs, dict) and "elements" in devicespecs:
                        for item in devicespecs["elements"]:
                            if item["name"] in self.network_objects.keys():
                                # self.external_cloud_objects[item["name"]].update(db)
                                new_objects[item["name"]] = self.external_cloud_objects[item["name"]]
                                del self.external_cloud_objects[item["name"]]
                            else:
                                new_objects[item["name"]] = ExternalCloudEntities(db, self.dbid, self.db_slice["url"],
                                                                                  devicetype, item["uri"])
                            pool.spawn_n(new_objects[item["name"]].update, db)
                            # else:
                            #                    LOG.critical(_("Unable to locate elements in: %s" % devicespecs))
            for item in self.external_cloud_objects:
                self.external_cloud_objects[item].delete(db)
            self.external_cloud_objects = new_objects
            pool.waitall()
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()

    def cloud_entities_delete(self, db):
        for item in self.external_cloud_objects:
            self.external_cloud_objects[item].delete(db)
        self.external_cloud_objects = {}

    def classes_update(self, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            rest_uri = self.db_slice["url"] + self.rest_system["classes"]
            rest_classes = rest_api.get_rest(rest_uri)
            if rest_classes["http_status_code"] != 200:
                return
            slice_row = {}
            slice_row.update(self.db_slice)
            slice_row.update(self.db_entity)

            if "classes" in rest_classes.keys() and \
                            "total" in rest_classes["classes"].keys() and \
                            rest_classes["classes"]["total"] > 0:
                for item in rest_classes["classes"]["elements"]:
                    db_class = db.get_row("tblEntities", "deleted = 0 AND  name = '%s' AND "
                                                         "entitytype =  '%s' AND "
                                                         "parententityid = '%s' " % (
                                              item["name"], item["type"], self.db_entity["parententityid"]))
                    if not db_class:
                        entity.entity_utils.delete_entity(self.db_slice["url"] + item["uri"])

            classes = []
            current_index = 0
            while True:
                db_class = cloud_utils.to_lower(db.get_row("tblEntities", "deleted = 0 AND "
                                                                          " (entitytype = 'compute_class' OR entitytype = 'storage_class' OR entitytype = 'network_class') AND "
                                                                          " parententityid = '%s' AND id > %s  " % (
                                                               self.db_entity["parententityid"], current_index)))
                if not db_class:
                    break
                current_index = db_class["id"]
                db_class_row = cloud_utils.to_lower(
                    db.get_row(entity.entity_constants.class_tables[db_class["entitytype"]],
                               " tblEntities = %s  " % current_index))
                if not db_class_row:
                    continue
                db_class_row.update(db_class)
                classes.append(entity.entity_manager.create_class_json(db, current_index, db_class_row))
            # eve = entity.entity_functions.EntityFunctions(db, db_class["id"], slice_row=slice_row, quick_provision=True)
            #                eve.do(db,"provision")
            entity.entity_utils.post_entity({"classes": classes}, "storage_class", self.db_slice["url"])
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()

    def slice_libraries_update(self, time_clause, LOG=LOG):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            self.rest_image_libraries_uri = self.db_slice["url"] + self.rest_slice["libraryimage"]
            self.rest_image_libraries = rest_api.get_rest(self.rest_image_libraries_uri)
            if self.rest_image_libraries["http_status_code"] != 200:
                return
            pool = eventlet.GreenPool()
            if "libraryimage" in self.rest_image_libraries.keys() and \
                            "elements" in self.rest_image_libraries["libraryimage"].keys() and \
                            "uri" in self.rest_image_libraries["libraryimage"]:

                #                rest_list = rest_api.get_rest(self.db_slice["url"] + self.rest_image_libraries["libraryimage"]["uri"])
                #                if rest_list["http_status_code"] != 200:
                #                    return

                update_time = cloud_utils.mysql_now()
                slice_libs = []
                for item in self.rest_image_libraries["libraryimage"]["elements"]:
                    #                if "list" in rest_list:
                    #                    for item in rest_list["list"]:
                    group = db.get_row("tblEntities", "deleted = 0 AND  name = '%s' AND "
                                                      "entitytype =  'imagelibrary' AND "
                                                      "parententityid = '%s' " % (item["name"], self.dbid))
                    if group:
                        group_child = db.get_row("tblImageLibrary", "tblEntities = '%s' " % group["id"])
                        if group_child and group_child["created_by"] != "slice":
                            continue
                    slice_libs.append(item)
                    pool.spawn_n(resync_group, self.dbid, "imagelibrary", item["uri"], self.db_slice["url"], self.dbid,
                                 "libraryimages")

                for item in slice_libs:
                    self.rest_image_libraries["libraryimage"]["elements"].remove(item)
                    self.rest_image_libraries["libraryimage"]["total"] -= 1

                pool.waitall()
                current_index = 0
                while True:
                    lib = db.get_row("tblEntities", "deleted = 0 AND "
                                                    "entitytype = 'imagelibrary' AND "
                                                    "parententityid = '%s' AND id > %s AND "
                                                    "updated_at < '%s' " % (self.dbid, current_index, update_time))
                    if not lib:
                        break

                    current_index = lib["id"]
                    lib_child = db.get_row("tblImageLibrary", "tblEntities = '%s' " % lib["id"])
                    created_by = "user"
                    if lib_child:
                        created_by = lib_child["created_by"]
                    if created_by == "user":
                        continue

                    LOG.critical(_("Library being deleted update_time:%s  lib: %s" % (update_time, str(lib))))

                    while True:
                        img = db.get_row("tblEntities", "deleted = 0 AND "
                                                        "entitytype = 'image' AND "
                                                        "parententityid = '%s' " % lib["id"])
                        if img:
                            db.delete_rows_dict("tblEntities", {"clonedfromentityid": img["id"]})
                            entity.entity_utils.delete_entity_recursively(db, img["id"])
                        # db.delete_rows_dict("tblEntities", {"id": img["id"]})
                        else:
                            break

                    db.delete_rows_dict("tblEntities", {"clonedfromentityid": lib["id"]})
                    entity.entity_utils.delete_entity_recursively(db, lib["id"])
                # db.delete_rows_dict("tblEntities", {"id": lib["id"]})

                organization.sync_imagelibraries(self.dbid, self.rest_image_libraries, self.db_slice["url"], LOG=LOG)
        except:
            cloud_utils.log_exception(sys.exc_info(), LOG=LOG)
        finally:
            db.close()


def resync_group(parententityid, entitytype, uri, home_url, slice_dbid, child_rest_name, LOG=LOG):
    db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
    try:
        if not uri:
            LOG.critical(_("uri not provided for parententityid: %s  entitytype: %s" %
                           (parententityid, entitytype)))
            return
        group_rest = rest_api.get_rest(home_url + uri)
        if group_rest["http_status_code"] != 200:
            return

        if "name" not in group_rest:
            LOG.critical(_("name not in rest response %s for parententityid: %s  entitytype: %s" %
                           (group_rest, parententityid, entitytype)))
            return
        group_rest["entitytype"] = entitytype
        group_rest["parententityid"] = parententityid
        group_rest["entitystatus"] = group_rest["resource_state"]["state"]
        if "uuid" in group_rest:
            group_rest["uniqueid"] = group_rest["uuid"]
        group_rest["created_by"] = "slice"

        group_dbid = cloud_utils.update_or_insert(db, "tblEntities", group_rest, {"entitytype": "imagelibrary",
                                                                                  "parententityid": parententityid,
                                                                                  "name": group_rest["name"],
                                                                                  "deleted": 0
                                                                                  },
                                                  child_table=entity.entity_manager.entities[entitytype].child_table)
        if not group_dbid:
            LOG.critical(_("unable add or locate dbod for parententityid: %s  entitytype: %s" %
                           (parententityid, entitytype)))
            return

        entity.entity_utils.create_or_update_uri(db, None, group_dbid, home_url,
                                                 group_rest, slice_dbid=slice_dbid, uri_type="home")

        if child_rest_name not in group_rest:
            LOG.critical(_("childrestname %s not in rest %s for parententityid: %s  entitytype: %s" %
                           (child_rest_name, group_rest, parententityid, entitytype)))
            return

        if entitytype not in entity.entity_constants.profile_group_child:
            LOG.critical(_("no child profile for parententityid: %s  entitytype: %s" %
                           (parententityid, entitytype)))
            return

        update_time = cloud_utils.mysql_now()
        child_entitytype = entity.entity_constants.profile_group_child[entitytype]
        if "uri" in group_rest[child_rest_name]:
            child_rest_list = rest_api.get_rest(home_url + group_rest[child_rest_name]["uri"])
            if child_rest_list["http_status_code"] != 200:
                LOG.critical(_("unable to GET %s for parententityid: %s  entitytype: %s" %
                               (child_rest_list, parententityid, entitytype)))
                return

            if "list" in child_rest_list:
                for item in child_rest_list["list"]:
                    if "name" not in item or "uri" not in item:
                        continue
                    unique = {"name": item["name"], "entitytype": child_entitytype, "parententityid": group_dbid,
                              "deleted": 0}
                    if "uuid" in item:
                        unique["uniqueid"] = item["uuid"]

                    item.update(unique)
                    item["entitystatus"] = item["resource_state"]["state"]
                    child_dbid = cloud_utils.update_or_insert(db, "tblEntities", item, unique,
                                                              child_table=entity.entity_manager.entities[
                                                                  child_entitytype].child_table)

                    entity.entity_utils.create_or_update_uri(db, None, child_dbid, home_url,
                                                             item, slice_dbid=slice_dbid, uri_type="home")

        while True:
            orphan = db.get_row("tblEntities", "deleted = 0 AND "
                                               "entitytype = '%s' AND "
                                               "parententityid = '%s' AND "
                                               "updated_at < '%s'" % (child_entitytype, group_dbid, update_time))
            if not orphan:
                break
            db.delete_rows_dict("tblEntities", {"clonedfromentityid": orphan["id"]})
            #            db.delete_rows_dict("tblEntities", {"id": orphan["id"]})
            entity.entity_utils.delete_entity_recursively(db, orphan["id"])

        previous_id = 0
        while True:
            lib = db.get_row("tblEntities",
                             "deleted = 0 AND ClonedFromEntityId = '%s' AND id > %s" % (group_dbid, previous_id))
            if not lib:
                break
            previous_id = lib["id"]
            db.delete_rows_dict("tblEntities", {"parententityid": lib["id"], "clonedfromentityid": 0})
    except:
        cloud_utils.log_exception(sys.exc_info(), LOG=LOG)

    finally:
        db.close()


class ComputeEntities(object):
    def __init__(self, slice_id, name, rest_slice_uri, rest_my_uri):
        self.name = name
        self.my_ports = {}
        self.my_addresses = {}
        self.rest_slice_uri = rest_slice_uri
        self.rest_my_uri = rest_my_uri
        self.rest_me = None
        self.rest_ports = None
        self.dbid = 0
        self.slice_id = slice_id

    def update(self, uri=None):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            if uri:
                self.rest_my_uri = uri
            row = cloud_utils.to_lower(db.get_row_dict("tblEntities", self.get_unique()))
            if row:
                entity.entity_utils.read_remaining_entity(db, row["id"], row)

            self.rest_me = rest_api.get_rest(self.rest_slice_uri + self.rest_my_uri)
            if "data" in self.rest_me.keys() and len(self.rest_me["data"]) == 2:
                self.rest_me["TotalBandwidth"] = self.rest_me["data"][0]
                self.rest_me["CurrentBandwidth"] = self.rest_me["data"][1]

            self.rest_me.pop("extra_specs", None)
            self.rest_me.pop("metadata", None)

            self.rest_me["CPU_OverAllocation"] = 0
            self.rest_me["EntityPool"] = ""
            if "cpu" in self.rest_me.keys():
                if len(self.rest_me["cpu"]) == 2:
                    self.rest_me["Cores"] = self.rest_me["cpu"][0]
                    self.rest_me["Mhz"] = self.rest_me["cpu"][1]
                    self.rest_me["vCPU"] = self.rest_me["Cores"]
                elif len(self.rest_me["cpu"]) == 5:
                    self.rest_me["Sockets"] = self.rest_me["cpu"][0]
                    self.rest_me["Cores"] = self.rest_me["cpu"][1]
                    self.rest_me["Threads"] = self.rest_me["cpu"][2]
                    self.rest_me["CPU_OverAllocation"] = self.rest_me["cpu"][3]
                    self.rest_me["vCPU"] = self.rest_me["Sockets"] * self.rest_me["Cores"] * self.rest_me["Threads"] * \
                                           self.rest_me["CPU_OverAllocation"]
                    self.rest_me["Mhz"] = self.rest_me["cpu"][4]

            if "das" in self.rest_me.keys() and len(self.rest_me["das"]) == 2:
                self.rest_me["TotalStorage"] = self.rest_me["das"][0]
                self.rest_me["CurrentStorage"] = self.rest_me["das"][1]

            if "hypervisor_type" in self.rest_me.keys():
                self.rest_me["Hypervisor"] = self.rest_me["hypervisor_type"]

            if "resource_status" in self.rest_me.keys():
                if "pool" in self.rest_me["resource_status"].keys():
                    self.rest_me["EntityPool"] = self.rest_me["resource_status"]["pool"]
                if "power" in self.rest_me["resource_status"].keys():
                    self.rest_me["EntityPower"] = self.rest_me["resource_status"]["power"]

            if row and row["cpu_overallocation"] != 0:
                if row["cpu_overallocation"] != 0:
                    del self.rest_me["CPU_OverAllocation"]

            if row and row["entitypool"] != self.rest_me["EntityPool"]:
                del self.rest_me["EntityPool"]
            # update_cfa = True

            if row and "description" in self.rest_me:
                del self.rest_me["description"]

            if "resource_state" in self.rest_me.keys() and "state" in self.rest_me["resource_state"].keys():
                self.rest_me["EntityStatus"] = self.rest_me["resource_state"]["state"]

            self.rest_me["EntityType"] = "slice_compute_entity"
            self.rest_me["ParentEntityId"] = self.slice_id

            #        self.db.delete_rows_dict("tblComputeEntities", {"uuid": self.rest_me["uuid"]})
            #        self.dbid = cloud_utils.insert_db(self.db, "tblComputeEntities",self.rest_me)
            if "uuid" in self.rest_me:
                self.rest_me["uniqueid"] = self.rest_me["uuid"]
            self.dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                                     self.rest_me, self.get_unique(), child_table="tblComputeEntities")

            cloud_utils.update_or_insert(db, "tblUris",
                                         {"tblEntities": self.dbid, "rest_response": json.dumps(self.rest_me),
                                          "tblSlices": self.slice_id, "type": "home",
                                          "uri": self.rest_slice_uri + self.rest_my_uri},
                                         {"tblEntities": self.dbid, "deleted": 0})

            new_addresses = {}
            if "addresses" in self.rest_me.keys() and len(self.rest_me["addresses"]) > 0:
                address = {"tblEntities": self.dbid}
                for item in self.rest_me["addresses"]:
                    if "ip_address" in item:
                        address["IPAddress"] = item["ip_address"]
                        if "ip_mask" in item:
                            address["IPMask"] = item["ip_mask"]
                        if "network" in item:
                            address["Network"] = item["network"]
                        if "mac_address" in item:
                            address["MacAddress"] = item["mac_address"]

                        # id = cloud_utils.insert_db(self.db,"tblIP4Addresses", address)
                        id = cloud_utils.update_or_insert(db, "tblIP4Addresses", address, {"tblEntities": self.dbid,
                                                                                           "IPAddress": address[
                                                                                               "IPAddress"]})
                        if address["IPAddress"] in self.my_addresses:
                            del self.my_addresses[address["IPAddress"]]
                        new_addresses[address["IPAddress"]] = id

            for item in self.my_addresses:
                db.delete_rows_dict("tblIP4Addresses", {"id": self.my_addresses[item]})
            self.my_addresses = new_addresses
            #        self.my_ports = add_ports(db, "tblEntities", self.dbid, self.rest_slice_uri, self.rest_me, self.my_ports)

            update_ports(db, self.dbid, self.rest_slice_uri, self.rest_me)
            if row:
                eve = entity.entity_functions.EntityFunctions(db, row["id"], row=row)
                eve.do(db, "update", options=row)

        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            db.close()

    def delete(self, db):
        db.delete_rows_dict("tblEntities", {"id": self.dbid})

    def get_unique(self):
        try:
            return {"entitytype": "slice_compute_entity", "parententityid": self.slice_id, "name": self.name}
        except:
            cloud_utils.log_exception(sys.exc_info())


class StorageEntities(object):
    def __init__(self, slice_id, name, rest_slice_uri, rest_my_uri):
        self.name = name
        self.slice_id = slice_id
        self.my_ports = {}
        self.rest_slice_uri = rest_slice_uri
        self.rest_my_uri = rest_my_uri
        self.rest_me = None
        self.rest_ports = None
        self.dbid = 0

    # self.update(db)

    def update(self, uri=None):
        db = cloud_utils.CloudGlobalBase(log=False, LOG=LOG)
        try:
            if uri:
                self.rest_my_uri = uri

            row = cloud_utils.to_lower(db.get_row_dict("tblEntities", self.get_unique()))
            if row:
                entity.entity_utils.read_remaining_entity(db, row["id"], row)

            self.rest_me = rest_api.get_rest(self.rest_slice_uri + self.rest_my_uri)
            #        self.rest_me["tblEntities"] = self.pid

            self.rest_me.pop("extra_specs", None)
            self.rest_me.pop("metadata", None)

            if "network" in self.rest_me.keys() and len(self.rest_me["network"]) == 3:
                self.rest_me["TotalBandwidth"] = self.rest_me["network"][0]
                self.rest_me["AvailableBandwidth"] = self.rest_me["network"][1]
                self.rest_me["AllocationUnitBandwidth"] = self.rest_me["network"][2]

            if "iops" in self.rest_me.keys() and len(self.rest_me["iops"]) == 3:
                self.rest_me["TotalIOPS"] = self.rest_me["iops"][0]
                self.rest_me["AvailableIOPS"] = self.rest_me["iops"][1]
                self.rest_me["AllocationUnitIOPS"] = self.rest_me["iops"][2]

            if "storage" in self.rest_me.keys() and len(self.rest_me["storage"]) == 3:
                self.rest_me["TotalStorage"] = self.rest_me["storage"][0]
                self.rest_me["AvailableStorage"] = self.rest_me["storage"][1]
                self.rest_me["AllocationUnitStorage"] = self.rest_me["storage"][2]

            if "resource_status" in self.rest_me.keys():
                if "pool" in self.rest_me["resource_status"].keys():
                    self.rest_me["EntityPool"] = self.rest_me["resource_status"]["pool"]
                if "power" in self.rest_me["resource_status"].keys():
                    self.rest_me["EntityPower"] = self.rest_me["resource_status"]["power"]

            if row and row["entitypool"] != self.rest_me["EntityPool"]:
                del self.rest_me["EntityPool"]

            if row and "description" in self.rest_me:
                del self.rest_me["description"]

            if "resource_state" in self.rest_me.keys() and "state" in self.rest_me["resource_state"].keys():
                self.rest_me["EntityStatus"] = self.rest_me["resource_state"]["state"]

            self.rest_me["EntityType"] = "slice_storage_entity"
            self.rest_me["ParentEntityId"] = self.slice_id
            if "uuid" in self.rest_me:
                self.rest_me["uniqueid"] = self.rest_me["uuid"]
            self.dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                                     self.rest_me, self.get_unique(), child_table="tblStorageEntities")

            cloud_utils.update_or_insert(db, "tblUris",
                                         {"tblEntities": self.dbid, "rest_response": json.dumps(self.rest_me),
                                          "tblSlices": self.slice_id, "type": "home",
                                          "uri": self.rest_slice_uri + self.rest_my_uri},
                                         {"tblEntities": self.dbid, "deleted": 0})

            update_ports(db, self.dbid, self.rest_slice_uri, self.rest_me)
            #       self.my_ports = add_ports(db, "tblEntities", self.dbid, self.rest_slice_uri, self.rest_me, self.my_ports)
            if row:
                eve = entity.entity_functions.EntityFunctions(db, row["id"], row=row)
                eve.do(db, "update", options=row)

        except:
            cloud_utils.log_exception(sys.exc_info())
        finally:
            db.close()

    def delete(self, db):
        db.delete_rows_dict("tblEntities", {"id": self.dbid})

    def get_unique(self):
        return {"entitytype": "slice_storage_entity", "parententityid": self.slice_id, "name": self.name}


def update_net_entity(entitytype, parententityid, slice_url, device_uri, slice_id):
    db = cloud_utils.CloudGlobalBase(log=False)
    try:
        LOG.info(_("Updateing for id: %s, entitytype:%s slice_url:%s device uri:%s" % (
            parententityid, entitytype, slice_url, device_uri)))

        rest_me = rest_api.get_rest(slice_url + device_uri)
        if rest_me["http_status_code"] != 200:
            return

        rest_me.pop("extra_specs", None)
        rest_me.pop("metadata", None)

        if "device_type" in rest_me.keys():
            rest_me["DeviceType"] = rest_me["device_type"]

        if "type" in rest_me.keys():
            rest_me["DeviceFunction"] = rest_me["type"]

        # if "capacity" in rest_me.keys() and len(rest_me["capacity"]) == 2:
        #            rest_me["TotalThroughput"] = rest_me["capacity"][0]
        #            rest_me["CurrentThroughput"] = rest_me["capacity"][1]

        if "throughputs_offered" in rest_me.keys() and isinstance(rest_me["throughputs_offered"], list):
            rest_me["Throughputs"] = str(rest_me["throughputs_offered"]).strip('[]')

        rest_me["TotalThroughput"] = rest_me.get("throughput_allocated", 0)
        rest_me["LicensedThroughput"] = rest_me.get("throughput_license", 0)
        if rest_me["TotalThroughput"] == 0:
            rest_me["TotalThroughput"] = rest_me["LicensedThroughput"]

        if "resource_status" in rest_me.keys():
            if "pool" in rest_me["resource_status"].keys():
                rest_me["EntityPool"] = rest_me["resource_status"]["pool"]
            if "power" in rest_me["resource_status"].keys():
                rest_me["EntityPower"] = rest_me["resource_status"]["power"]

        if "resource_state" in rest_me.keys() and "state" in rest_me["resource_state"].keys():
            rest_me["EntityStatus"] = rest_me["resource_state"]["state"]

        rest_me["EntitySubType"] = "slice_network_entity"
        rest_me["EntityType"] = entitytype
        rest_me["ParentEntityId"] = parententityid
        if "uuid" in rest_me:
            rest_me["uniqueid"] = rest_me["uuid"]
        dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                            rest_me, {"parententityid": parententityid, "entitytype": entitytype,
                                                      "name": rest_me["name"]}, child_table="tblNetworkEntities")

        cloud_utils.update_or_insert(db, "tblUris", {"tblEntities": dbid, "rest_response": json.dumps(rest_me),
                                                     "tblSlices": slice_id, "type": "home",
                                                     "uri": slice_url + device_uri},
                                     {"tblEntities": dbid, "deleted": 0})
        update_addresses(db, dbid, rest_me)
        update_ports(db, dbid, slice_url, rest_me)

    except:
        cloud_utils.log_exception(sys.exc_info())
    finally:
        db.close()


def update_addresses(db, dbid, rest_me):
    time_clause = {"field": "updated_at", "check": "<", "time": "%s" % (db.get_time_stamp("NOW()")['time'])}
    if "addresses" in rest_me.keys() and len(rest_me["addresses"]) > 0:
        address = {"tblEntities": dbid}
        for item in rest_me["addresses"]:
            if "ip_address" in item:
                address["IPAddress"] = item["ip_address"]
                if "ip_mask" in item:
                    address["IPMask"] = item["ip_mask"]
                if "network" in item:
                    address["Network"] = item["network"]
                if "mac_address" in item:
                    address["MacAddress"] = item["mac_address"]
                if "name" in item:
                    address["name"] = item["name"]
                if "uuid" in item:
                    address["uuid"] = item["uuid"]

                id = cloud_utils.update_or_insert(db, "tblIP4Addresses", address, {"tblEntities": dbid,
                                                                                   "IPAddress": address[
                                                                                       "IPAddress"]})

    # delete any stale entries from the database (if an entry is not updated, it must be stale)
    while True:
        row = db.get_row_dict("tblIP4Addresses", {"tblEntities": dbid}, time_clause=time_clause)
        if row is None:
            break
        LOG.info(_("Deleting stale port id: %s" % row['id']))
        db.delete_rows_dict("tblIP4Addresses", {"id": row['id']})


def update_ports(db, dbid, rest_slice_uri, rest_me):
    try:
        rest_response = None
        if "ports" in rest_me.keys() and "total" in rest_me["ports"] and rest_me["ports"]["total"] > 0:
            rest_response = rest_api.get_rest(rest_slice_uri + rest_me["ports"]["uri"])
            if rest_response["http_status_code"] != 200:
                return
        else:
            return
        if "ports" not in rest_response:
            return
        pool = eventlet.GreenPool()
        time_clause = {"field": "updated_at", "check": "<", "time": "%s" % (db.get_time_stamp("NOW()")['time'])}
        for item in rest_response["ports"]:
            if "name" not in item or "uri" not in item:
                LOG.critical(_("Unable to locate port name in item: %s " % item))
                continue
            pool.spawn(update_port_entity, db, dbid, rest_slice_uri, item["uri"])
        pool.waitall()
        # delete any stale entries from the database (if an entry is not updated, it must be stale)
        while True:
            row = db.get_row_dict("tblPortEntities", {"tblEntities": dbid}, time_clause=time_clause)
            if row is None:
                break
            LOG.info(_("Deleting stale port id: %s" % row['id']))
            db.delete_rows_dict("tblPortEntities", {"id": row['id']})

    except:
        cloud_utils.log_exception(sys.exc_info())


def update_port_entity(db, dbid, rest_slice_uri, uri):
    rest_me = rest_api.get_rest(rest_slice_uri + uri)
    if rest_me["http_status_code"] != 200:
        return
    rest_me["tblEntities"] = dbid

    if "data" in rest_me.keys() and len(rest_me["data"]) == 2:
        rest_me["TotalBandwidth"] = rest_me["data"][0]
        rest_me["CurrentBandwidth"] = rest_me["data"][1]

    if "mac_address" in rest_me.keys():
        rest_me["MacAddress"] = rest_me["mac_address"]

    if "resource_state" in rest_me.keys() and "state" in rest_me["resource_state"].keys():
        rest_me["EntityStatus"] = rest_me["resource_state"]["state"]

    if "connected_with" in rest_me.keys() and \
                    "device" in rest_me["connected_with"] and \
                    "type" in rest_me["connected_with"] and \
                    "port" in rest_me["connected_with"]:
        rest_me["ConnectedWithDevice"] = rest_me["connected_with"]["device"]
        rest_me["ConnectedWithDeviceType"] = rest_me["connected_with"]["type"]
        rest_me["ConnectedWithDevicePort"] = rest_me["connected_with"]["port"]
    if "uuid" in rest_me:
        rest_me["uniqueid"] = rest_me["uuid"]
    dbid = cloud_utils.update_or_insert(db, "tblPortEntities", rest_me, {"name": rest_me["name"], "tblentities": dbid})


#    LOG.info(_("Port id: %s added/updated with:%s" % (dbid, rest_me)))


class ExternalCloudEntities(object):
    def __init__(self, db, pid, ptable, rest_slice_uri, rest_my_uri):
        self.db = db
        self.pid = pid
        self.ptable = ptable
        self.rest_slice_uri = rest_slice_uri
        self.rest_my_uri = rest_my_uri


def update_attached_network_entity(db, parententityid, slice_url, device_uri, slice_id):
    try:
        LOG.info(_("Updateing for id: %s, slice_url:%s device uri:%s" % (parententityid, slice_url, device_uri)))
        rest_me = rest_api.get_rest(slice_url + device_uri)
        if rest_me["http_status_code"] != 200:
            return

        if "capacity" in rest_me.keys():
            rest_me["TotalBandwidth"] = rest_me["capacity"]
        if "available" in rest_me.keys():
            rest_me["CurrentBandwidth"] = rest_me["available"]

        if "network_type" in rest_me.keys():
            rest_me["NetworkType"] = rest_me["network_type"]

        if "ip_address" in rest_me.keys():
            rest_me["IPAddress"] = rest_me["ip_address"]

        if "ip_mask" in rest_me.keys():
            rest_me["IPMask"] = rest_me["ip_mask"]
            rest_me["network_mask"] = rest_me["ip_mask"]

        if "resource_state" in rest_me.keys() and "state" in rest_me["resource_state"].keys():
            rest_me["EntityStatus"] = rest_me["resource_state"]["state"]

        rest_me["EntityType"] = "slice_attached_network"
        rest_me["ParentEntityId"] = parententityid

        #        db.delete_rows_dict("tblAttachedNetworkEntities", {"name": rest_me["name"]})
        #        dbid = cloud_utils.insert_db(db,"tblAttachedNetworkEntities", rest_me)
        if "uuid" in rest_me:
            rest_me["uniqueid"] = rest_me["uuid"]

        dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                            rest_me, {"parententityid": rest_me["ParentEntityId"],
                                                      "entitytype": rest_me["EntityType"], "name": rest_me["name"]},
                                            child_table="tblAttachedNetworkEntities")

        cloud_utils.update_or_insert(db, "tblUris",
                                     {"tblEntities": dbid, "rest_response": json.dumps(rest_me), "tblSlices": slice_id,
                                      "type": "home",
                                      "uri": slice_url + device_uri},
                                     {"tblEntities": dbid, "deleted": 0})

        user_info = db.execute_db(
            "SELECT user_foreign_addresses FROM tblAttachedNetworkEntities WHERE tblEntities='%s'" % dbid)
        if isinstance(user_info, tuple):
            user_info = user_info[0]
        if user_info["user_foreign_addresses"] and unicode(user_info["user_foreign_addresses"]) != unicode(
                rest_me["foreign_addresses"]):
            eve = entity.entity_functions.EntityFunctions(db, dbid)
            status = eve.do(db, "update", options={"foreign_addresses": user_info["user_foreign_addresses"]})

        time_clause = {"field": "updated_at", "check": "<", "time": "%s" % (db.get_time_stamp("NOW()")['time'])}
        if "address_pool" in rest_me.keys() and "address_pool_count" in rest_me.keys() and \
                        rest_me["address_pool_count"] > 0:

            address = {"tblEntities": dbid}

            for item in rest_me["address_pool"]:
                if isinstance(item, dict):
                    address["IPAddress"] = item["foreign_address"]
                    address["network"] = rest_me["name"]
                    address["subnet"] = item.get("network", "")
                    address["server"] = item.get("server", "")
                    address["serverfarm"] = item.get("serverfarm", "")
                    address["service"] = item.get("service", "")
                    address["vdc"] = item.get("vdc", "")
                    address["department"] = item.get("department", "")
                    address["organization"] = item.get("organization", "")
                    address["local_ip_address"] = item.get("local_address", "")

                    id = cloud_utils.update_or_insert(db, "tblIP4Addresses", address,
                                                      {"IPAddress": item["foreign_address"]})

        # delete any stale entries from the database (if an entry is not updated, it must be stale)
        while True:
            row = db.get_row_dict("tblIP4Addresses", {"tblEntities": dbid}, time_clause=time_clause)
            if row is None:
                break
            LOG.info(_("Deleting stale port id: %s" % row['id']))
            db.delete_rows_dict("tblIP4Addresses", {"id": row['id']})

    except:
        cloud_utils.log_exception(sys.exc_info())
