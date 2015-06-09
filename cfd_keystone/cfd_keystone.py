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
from datetime import datetime
from dateutil import tz

currentDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath('%s/..' % currentDir))

eventlet.monkey_patch()

from utils.underscore import _

LOG = logging.getLogger('hawk-rpc')

import utils.cloud_utils as cloud_utils
import rest.rest_api as rest_api
import entity.entity_functions

keystone_url = "http://localhost:35357/v3/"
system_token = "ADMIN"

default_system_group = "SystemGroup"
default_admin_name = "admin"
default_admin_password = "CloudFlow"
import cryptC as crypt
import random
import hashlib
import base64


def system_initialization(db):
    system_row = cloud_utils.lower_key(
        db.get_row_dict("tblEntities", {"entitytype": "system"}, order="ORDER BY id LIMIT 1"))

    header = {"Content-type": "application/json", "X-Auth-token": system_token}

    system_domain = get_create_domain(db, system_token,
                                      {"name": system_row["name"], "description": system_row["description"]})
    if not system_domain:
        return
    it_group = None
    response = rest_api.get_rest(keystone_url + "groups", params={"domain_id": system_domain["id"]}, headers=header)
    for group in response["groups"]:
        if group["name"].lower() == default_system_group.lower():
            it_group = group
            break
    if not it_group:
        group = {"group": {"enabled": True, "name": default_system_group, "domain_id": system_domain["id"]}}
        group = rest_api.post_rest(keystone_url + "groups", group, headers=header)
        it_group = group["group"]

    admin_user = None
    it_group_users = rest_api.get_rest(it_group["links"]["self"] + "/users", headers=header)

    if len(it_group_users["users"]) == 0:
        # no users in system group
        all_users = rest_api.get_rest(keystone_url + "users", headers=header)
        for user in all_users["users"]:
            if user["domain_id"] == system_domain["id"]:
                admin_user = user
        if not admin_user:
            # no users in system domain
            if not os.path.exists("/etc/cloudflow/secret.key"):
                key = base64.b64encode(hashlib.sha256(str(random.getrandbits(256))).digest(),
                                       random.choice(['rA', 'aZ', 'gQ', 'hH', 'hG', 'aR', 'DD'])).rstrip('==')

                cloud_utils.write_file(key, "/etc/cloudflow/secret.key")
            key = cloud_utils.read_file("/etc/cloudflow/secret.key")
            cloud_utils.bash_command_no_exception("chown www-data:root /etc/cloudflow/secret.key")
            password = crypt.crypt(default_admin_password, key)

            u = {"user": {"domain_id": system_domain["id"],
                          "enabled": True,
                          "name": default_admin_name,
                          "password": password}
                 }
            u = rest_api.post_rest(keystone_url + "users", u, headers=header)
            admin_user = u["user"]
        # add admin user to admin group
        rest_api.put_rest(it_group["links"]["self"] + "/users/" + admin_user["id"], None, headers=header)

    system_group_row = db.get_row_dict("tblEntities", {"entitytype": "user_group", "deleted": 0,
                                                       "parententityid": system_row["id"]},
                                       order="ORDER BY id LIMIT 1")

    if system_group_row:
        system_group_dbid = system_group_row["id"]
    else:
        system_group_dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                                         {"name": default_system_group,
                                                          "description": "Root system group",
                                                          "entitytype": "user_group",
                                                          "parententityid": system_row["id"],
                                                          "entitystatus": "Ready"},
                                                         {"entitytype": "user_group",
                                                          "deleted": 0,
                                                          "parententityid": system_row["id"]})


    # ensure there is at least one user in the admin group
    system_admin_row = db.get_row_dict("tblEntities", {"entitytype": "user", "deleted": 0,
                                                       "parententityid": system_group_dbid},
                                       order="ORDER BY id LIMIT 1")
    # create a user if none for admin group
    if not system_admin_row:
        dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                            {"name": default_admin_name,
                                             "loginid": default_admin_name,
                                             "description": "Default System Administrator",
                                             "entitytype": "user",
                                             "parententityid": system_group_dbid,
                                             "reccreatedby": system_row["id"],
                                             "entitystatus": "Ready"},
                                            {"entitytype": "user",
                                             "deleted": 0,
                                             "parententityid": system_group_dbid}, child_table="tblUsers")

        db.delete_rows_dict("tblEntitiesACL", {"tblentities": dbid})
        db.execute_db("INSERT INTO tblEntitiesACL (tblEntities, AclRole, AclEntityId) VALUES ('%s', '%s', '%s')" %
                      (dbid, "IT", system_row["id"]))

    # ensure there is at least one organization
    organization_row = db.get_row_dict("tblEntities", {"entitytype": "organization", "deleted": 0,
                                                       "parententityid": system_row["id"]},
                                       order="ORDER BY id LIMIT 1")

    # create a user if none for admin group
    if not organization_row:
        dbid = cloud_utils.update_or_insert(db, "tblEntities",
                                            {"name": "CloudFlow",
                                             "description": "Default organization",
                                             "entitytype": "organization",
                                             "parententityid": system_row["id"],
                                             "entitystatus": "Ready"},
                                            {"entitytype": "organization",
                                             "deleted": 0,
                                             "parententityid": system_group_dbid}, child_table="tblOrganizations")

        entity.entity_functions.initialize_resource_records(db, dbid, "organization", system_row["id"])

    validate_keystone_users(db)


#    print login(db, default_admin_name,  default_admin_password)
#    print login(db, default_admin_name,  "junk")

# delete all users that are not associated with a group
def validate_keystone_users(db):
    header = {"Content-type": "application/json", "X-Auth-token": system_token}
    all_users = rest_api.get_rest(keystone_url + "users", headers=header)
    for user in all_users["users"]:
        groups = rest_api.get_rest(user["links"]["self"] + "/groups", headers=header)
        if len(groups["groups"]) == 0:
            rest_api.delete_rest(user["links"]["self"], headers=header)


def get_domain(db, token, domain_dict):
    header = {"Content-type": "application/json", "X-Auth-token": token}
    response = rest_api.get_rest(keystone_url + "domains", headers=header)
    if not "domains" in response:   return None
    for domain in response["domains"]:
        if domain["name"].lower() == domain_dict["name"].lower():
            return domain
    return None


def get_create_domain(db, token, domain_dict):
    domain = get_domain(db, token, domain_dict)
    if domain:
        return domain
    header = {"Content-type": "application/json", "X-Auth-token": token}
    domain = {"domain": {"enabled": True, "name": domain_dict["name"], "description": domain_dict["description"]}}
    domain = rest_api.post_rest(keystone_url + "domains", domain, headers=header)
    if not domain or "domain" not in domain: return None
    return domain["domain"]


def del_domain(db, token, domain_dict):
    domain = get_domain(db, token, domain_dict)
    if domain:
        header = {"Content-type": "application/json", "X-Auth-token": token}
        rest_api.patch_rest(domain["links"]["self"], {"domain": {"enabled": False}}, headers=header)
        rest_api.delete_rest(domain["links"]["self"], headers=header)


def get_group(db, token, domain_dict, group_dict):
    domain = get_domain(db, token, domain_dict)
    if not domain:
        return None
    header = {"Content-type": "application/json", "X-Auth-token": token}
    response = rest_api.get_rest(keystone_url + "groups", params={"domain_id": domain["id"]}, headers=header)
    for group in response["groups"]:
        if group["name"].lower() == group_dict["name"].lower():
            return group
    return None


def get_create_group(db, token, domain_dict, group_dict):
    group = get_group(db, token, domain_dict, group_dict)
    if group:
        return group
    domain = get_create_domain(db, token, domain_dict)
    group = {"group": {"enabled": True, "name": group_dict["name"],
                       "description": group_dict["description"],
                       "domain_id": domain["id"]}}
    header = {"Content-type": "application/json", "X-Auth-token": token}
    group = rest_api.post_rest(keystone_url + "groups", group, headers=header)
    return group["group"]


def delete_group(db, token, domain_dict, group_dict):
    group = get_group(db, token, domain_dict, group_dict)
    if group:
        header = {"Content-type": "application/json", "X-Auth-token": token}
        rest_api.delete_rest(group["links"]["self"], headers=header)


def get_user(db, token, domain_dict, group_dict, user_dict):
    header = {"Content-type": "application/json", "X-Auth-token": token}
    group = get_group(db, token, domain_dict, group_dict)
    if not group:
        return None
    response = rest_api.get_rest(group["links"]["self"] + "/users", headers=header)
    for user in response["users"]:
        if user["name"].lower() == user_dict["name"].lower():
            return user
    return None


def get_create_user(db, token, domain_dict, group_dict, user_dict):
    user = get_user(db, token, domain_dict, group_dict, user_dict)
    if user:
        return user
    group = get_create_group(db, token, domain_dict, group_dict)
    header = {"Content-type": "application/json", "X-Auth-token": token}
    user = {"user": {"domain_id": group["domain_id"], "enabled": user_dict["enabled"],
                     "name": user_dict["name"], "password": user_dict["password"],
                     "email": user_dict["email"], "description": user_dict["description"]}}
    user = rest_api.post_rest(keystone_url + "users", user, headers=header)
    user = user["user"]
    # add user to group
    rest_api.put_rest(group["links"]["self"] + "/users/" + user["id"], None, headers=header)
    return user


def update_user(db, token, domain_dict, group_dict, user_dict):
    user = get_user(db, token, domain_dict, group_dict, user_dict)
    if user:
        header = {"Content-type": "application/json", "X-Auth-token": token}
        rest_api.patch_rest(user["links"]["self"], {"user": {"enabled": user_dict["enabled"],
                                                             "password": user_dict["password"]
                                                             }}, headers=header)
    else:
        get_create_user(db, token, domain_dict, group_dict, user_dict)


def delete_user(db, token, domain_dict, group_dict, user_dict):
    user = get_user(db, token, domain_dict, group_dict, user_dict)
    if user:
        header = {"Content-type": "application/json", "X-Auth-token": token}
        rest_api.delete_rest(user["links"]["self"], headers=header)


def login(db, loginid, password, domain=None):
    user = {"name": loginid, "password": password}
    header = {"Content-type": "application/json"}
    all_users = None
    if domain:
        user.update({"domain": {"id": domain}})
    else:
        system_header = {"Content-type": "application/json", "X-Auth-token": system_token}
        all_users = rest_api.get_rest(keystone_url + "users", headers=system_header)
        for u in all_users["users"]:
            if u["name"].lower() == user["name"].lower():
                user.update({"domain": {"id": u["domain_id"]}})
                break
    if not "domain" in user:
        if all_users:
            LOG.critical(_("Curent users are %s " % str(all_users)))
        LOG.critical(_("no domain for user %s found" % user["name"]))
        return 0

    token_reuqest = {"auth": {"identity": {"methods": ["password"], "password": {"user": user}}}}
    user_token = rest_api.post_rest(keystone_url + "auth/tokens", token_reuqest, headers=header)
    if not user_token or "http_status_code" not in user_token or user_token["http_status_code"] != 201:
        if all_users:
            LOG.critical(_("Curent users are %s " % str(all_users)))
        LOG.critical(_("No keystone token found for user %s " % user["name"]))
        return 0

    # Convert ISO and UTC time local python
    issued_at = cloud_utils.jscript_time_to_python(user_token["token"]["issued_at"])
    #    issued_at = cloud_utils.utc_to_local(issued_at)
    issued_at = cloud_utils.python_time_to_mysql(issued_at)

    expires_at = cloud_utils.jscript_time_to_python(user_token["token"]["expires_at"])
    #    expires_at = cloud_utils.utc_to_local(expires_at)

    #    expires_at = cloud_utils.current_plus_minutes(10)
    expires_at = cloud_utils.python_time_to_mysql(expires_at)

    response = db.execute_db("SELECT tblEntities.id FROM tblEntities, tblUsers "
                             "WHERE (tblEntities.id = tblUsers.tblEntities AND tblUsers.LoginId = '%s' "
                             "AND tblEntities.deleted = 0) "
                             "ORDER BY tblEntities.id LIMIT 1" % loginid)

    if not response:
        LOG.critical(_("no db id found for user %s " % user["name"]))
        return 0

    db.execute_db("UPDATE tblUsers SET Token='%s', TokenIssuedAt='%s', TokenExpiresAt='%s' WHERE (tblEntities ='%s')" %
                  (user_token["response_headers"]["x-subject-token"], issued_at, expires_at, response[0]['id']))
    return response[0]['id']
