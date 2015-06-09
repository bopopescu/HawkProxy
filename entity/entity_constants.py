#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import sys
import logging
import gflags

import eventlet
import eventlet.corolocal

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()
LOG = logging.getLogger('cfd-rpc')
FLAGS = gflags.FLAGS

USER_LOGS_VIA_WEBSOCKET = True

profile_groups_provision_order = [{"group": "vpn_group", "child": "vpn_connection"},
                                  {"group": "security_group", "child": "security_rule"},
                                  {"group": "acl_group", "child": "acl_rule"},
                                  {"group": "lbs_group", "child": "lbs_service"},
                                  {"group": "imagelibrary", "child": "image"},
                                  {"group": "container", "child": "volume"},
                                  {"group": "disk", "child": "partition"},
                                  {"group": "bucket", "child": "object"},
                                  {"group": "serverfarm", "child": "server"}]

profile_groups_deprovision_order = [{"group": "vpn_group", "child": "vpn_connection"},
                                    {"group": "security_group", "child": "security_rule"},
                                    {"group": "acl_group", "child": "acl_rule"},
                                    {"group": "lbs_group", "child": "lbs_service"},
                                    {"group": "serverfarm", "child": "server"}]

profile_group_clone = ["vpn_group", "security_group", "acl_group", "lbs_group",
                       "container", "disk", "bucket", "serverfarm"]

profile_group_child = {"vpn_group": "vpn_connection",
                       "security_group": "security_rule",
                       "acl_group": "acl_rule",
                       "lbs_group": "lbs_service",
                       "imagelibrary": "image",
                       "container": "volume",
                       "disk": "partition",
                       "bucket": "object",
                       "serverfarm": "server"}

profile_child_group = dict([(v, k) for (k, v) in profile_group_child.iteritems()])

skip_dept_org_group_child = {"vpn_group": "vpn_connection",
                             "security_group": "security_rule",
                             "acl_group": "acl_rule",
                             "lbs_group": "lbs_service",
                             #                       "imagelibrary": "image",
                             "container": "volume",
                             "disk": "partition",
                             "bucket": "object",
                             "serverfarm": "server"}

skip_dept_org__child_group = dict([(v, k) for (k, v) in skip_dept_org_group_child.iteritems()])


# network services are validated an provisioned in this order
topology_network_services = ["vdc",
                             "switch_network_service",
                             "externalnetwork",
                             "nat_network_service",
                             "rts_network_service",
                             "fws_network_service",
                             "lbs_network_service",
                             "wan_network_service",
                             "ipsecvpn_network_service",
                             "sslvpn_network_service",
                             "ips_network_service",
                             "compute_network_service",
                             "storage_network_service",
                             "nms_network_service",
                             "tap_network_service",
                             "cloudservice_network_service",
                             "thirdparty_network_service",
                             "wan_network_service",
                             "sslaccelerator_network_service",
                             "rackspace_network_service",
                             "amazon_network_service"
                             ]

vdc_provision_profiles_group_child = \
    {"vpn_group": "vpn_connection",
     "security_group": "security_rule",
     "acl_group": "acl_rule",
     "lbs_group": "lbs_service",
     "serverfarm": "server"}

vdc_provision_only_entitytypes = topology_network_services + ["network_interface"]
#                                                        vdc_provision_profiles_group_child.keys() +
#                                                        vdc_provision_profiles_group_child.values()

vdc_no_update_entitytypes = ["network_interface", "tap_network_service"]

port_groups = [{"name": "acl_group", "type": "access_control", "item": "access_control_group"},
               {"name": "lbs_group", "type": "load_balancer", "item": "Lbs_group"},
               {"name": "vpn_group", "type": "vpn", "item": "vpn_group"},
               {"name": "security_group", "type": "firewall", "item": "security_group"}]

default_entity_pending_states = ["suspending", "processing", "provisioning",
                                 "deprovisioning", "activating", "destroying",
                                 "pending", "deleting", "aborting", "resuming", "rebooting", "queued"]

default_entity_completed_states = ["ready", "provisioned", "aborted", "deleted", "destroyed", "active", "suspended",
                                   "unavailable"]
default_entity_failed_states = ["aborted", "deleted"]

default_periodic_status_check_time = 3
default_periodic_max_status_check_iterations = 100

INACTIVE_VDC_SCAN_INTERVAL = 120
INACTIVE_VDC_CONTAINERS_SCAN_INTERVAL = 60
ACTIVE_VDC_SCAN_INTERVAL = 15

vdc_children = ["imagelibrary", "container", "disk", "bucket", "serverfarm"]
vdc_grandchildren = ["image", "volume", "partition", "object", "server"]

resource_network_services = ["loadbalancer", "firewall", "vpn", "nat", "networkMonitor", "router", "ssl", "ips", "wan"]

resource_record_types = ["total", "allocated", "deployed"]
resource_parent_entitytype = {"organization": "system", "department": "organization", "vdc": "department"}

network_services = ["loadbalancer", "firewall", "vpn", "nat", "networkMonitor", "router", "ssl", "ips", "wan",
                    "ethernetswitch"]

resource_network_services_2_names = {"vpn": "VPN network service",
                                     "firewall": "Firewall network service",
                                     "ssl": "SSL network service",
                                     "nat": "NAT network service",
                                     "loadbalancer": "Load balancer network service",
                                     "ips": "IPS/IDS network service",
                                     "wan": "WAN acceleration network service",
                                     "router": "Router network service",
                                     "networkMonitor": "Network Monitor network service"}

entity_children = ["imagelibrary", "container", "disk", "bucket", "serverfarm"]
entity_grandchildren = ["image", "volume", "partition", "object", "server"]

virtual_entitytype_2_network_services = {"ipsecvpn_network_service": "vpn",
                                         "fws_network_service": "firewall",
                                         "sslaccelerator_network_service": "ssl",
                                         "nat_network_service": "nat",
                                         "lbs_network_service": "loadbalancer",
                                         "ips_network_service": "ips",
                                         "wan_network_service": "wan",
                                         "rts_network_service": "router",
                                         "nms_network_service": "networkMonitor"}

physical_entitytype_2_network_services = {"slice_ipsecvpn_service": "vpn",
                                          "slice_fws_service": "firewall",
                                          "slice_sslaccelerator_service": "ssl",
                                          "slice_nat_service": "nat",
                                          "slice_lbs_service": "loadbalancer",
                                          "slice_ips_service": "ips",
                                          "slice_wan_service": "wan",
                                          "slice_rts_service": "router",
                                          "slice_nms_service": "networkMonitor"}

virtual_2_physical_entitytypes = {"ipsecvpn_network_service": "slice_ipsecvpn_service",
                                  "fws_network_service": "slice_fws_service",
                                  "sslaccelerator_network_service": "slice_sslaccelerator_service",
                                  "nat_network_service": "slice_nat_service",
                                  "lbs_network_service": "slice_lbs_service",
                                  "ips_network_service": "slice_ips_service",
                                  "wan_network_service": "slice_wan_service",
                                  "rts_network_service": "slice_rts_service",
                                  "nms_network_service": "slice_nms_service"}

entitytype_2_names = {"ipsecvpn_network_service": "VPN network service",
                      "fws_network_service": "Firewall network service",
                      "sslaccelerator_network_service": "SSL network service",
                      "nat_network_service": "NAT network service",
                      "lbs_network_service": "Load balancer network service",
                      "ips_network_service": "IPS/IDS network service",
                      "wan_network_service": "WAN acceleration network service",
                      "rts_network_service": "Router network service",
                      "nms_network_service": "Network Monitor network service"}

storage_types = ["gold", "silver", "platinum"]

class_tables = {"storage_class": "tblStorageClasses", "compute_class": "tblComputeClasses",
                "network_class": "tblNetworkClasses"}
class_device_entitytype = {"storage_class": "slice_storage_entity", "compute_class": "slice_compute_entity",
                           "network_class": "slice_network_entity"}
entitytype_class = {"slice_storage_entity": "storage_class", "slice_compute_entity": "compute_class",
                    "slice_network_entity": "network_class",
                    "slice_ipsecvpn_service": "network_class",
                    "slice_fws_service": "network_class",
                    "slice_sslaccelerator_service": "network_class",
                    "slice_nat_service": "network_class",
                    "slice_lbs_service": "network_class",
                    "slice_ips_service": "network_class",
                    "slice_wan_service": "network_class",
                    "slice_rts_service": "network_class",
                    "slice_nms_service": "network_class"}

physical_entitytypes = ["slice_storage_entity", "slice_compute_entity", "slice_network_entity",
                        "slice_attached_network"]
class_physical_child_tables = {"storage_class": "tblStorageEntities", "compute_class": "tblComputeEntities",
                               "network_class": "tblNetworkEntities"}
