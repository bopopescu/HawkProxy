__author__ = 'vkorolik'
# import ujson as json
import json
import logging
import pprint
from urlparse import parse_qs
from cgi import escape
import sys

import eventlet
from eventlet.green import urllib2
from eventlet import wsgi
import requests

import utils.gflags_collection
import cryptC as crypt
from utils.cloud_utils import CloudGlobalBase

UA = "http://cfd23.does-it.net:8231"
AUTH_URL = "http://cfd23.does-it.net:8002/v3"
# ENDPOINT_URL = "http://192.168.228.23:8002/v3"

log = logging.getLogger("log")
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)

import pytz, datetime

local = pytz.timezone("America/Los_Angeles")
naive = datetime.datetime.strptime("2001-2-3 10:11:12", "%Y-%m-%d %H:%M:%S")
local_dt = local.localize(naive, is_dst=None)
utc_dt = local_dt.astimezone(pytz.utc)

pp = pprint.PrettyPrinter(indent=4)

cloudDB = CloudGlobalBase(pool=False)

RES_CODE = "400 Bad Request"


def fetch(url):
    return urllib2.urlopen(url).read()


def get_token_json_response(un, dname, pa):  # TODO WHY CANT I LOG IN AS DEPARTMENT USER
    sec = "6apC3IcauIeKd5StPTjWzTBXFzQXvooHanb4qxnePzccX4SFBt"
    passw = crypt.crypt(pa, sec)

    payload = {
        "auth": {
            "identity": {
                "methods": [
                    "password"
                ],
                "password": {
                    "user": {
                        "domain": {
                            "name": dname
                        },
                        "name": un,
                        "password": passw
                    }
                }
            }
        }
    }

    # log.info(json.dumps(payload))
    headers = {'Content-Type': 'application/json'}
    r = requests.post(AUTH_URL + "/auth/tokens", data=json.dumps(payload), headers=headers)
    # log.info(r.url)
    log.info("AUTH RESP BODY: %s", json.loads(r.text))
    log.info("AUTH RESP HEADERS: %s", str(r.headers))
    return process_raw_token_data(r.text, r.headers, un)


def add_token_to_mysql(token, uname):
    rows = cloudDB.get_multiple_row("tblUsers", "LoginId='%s'" % (uname))
    # print rows[0]
    if len(rows) > 1:
        log.critical("More than one user with same login id in mysql db.")
    elif len(rows) == 0 or rows is None:
        log.warning("User not found in mysql db.")
    else:
        entID = str(rows[0]["tblEntities"])
        t = "NOW()"
        t_ex = "DATE_ADD(NOW(), INTERVAL 1 HOUR)"
        cloudDB.update_db("UPDATE tblUsers SET Token = '%s' WHERE tblEntities = '%s'" % (token, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenIssuedAt = %s WHERE tblEntities = '%s'" % (t, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenExpiresAt = %s WHERE tblEntities = '%s'" % (t_ex, entID))
        cloudDB.update_db("UPDATE tblUsers SET LastActivityDate = %s WHERE tblEntities = '%s'" % (t, entID))
        # print cloudDB.get_row("tblUsers", "tblEntities='%s'" % (entID))


def process_raw_token_data(body, headers, uname):
    # RETURNS JSON THAT SHOULD BE GIVEN AS RESPONSE TO AUTHENTICATE REQUEST
    try:
        tokenID = headers["X-Subject-Token"]
    except KeyError:
        return False
    if tokenID is None:
        return False
    tokenData = json.loads(body)
    tokenData["token"].update({'id': tokenID})
    string = json.dumps(tokenData)
    log.info(string)
    add_token_to_mysql(tokenID, uname)
    return string


def validate_token(token):
    # log.info(token)
    rows = cloudDB.get_multiple_row("tblUsers", "Token='%s'" % (token))
    # TODO In all queries, resulting rows can be None if query fails or db connection fails, causing TypeError on len call
    if rows is None:
        log.critical("Database query failed.")
        return False
    if len(rows) > 1:
        log.critical("More than one user with same login token in mysql db.")
    elif len(rows) == 0 or rows is None:
        log.warning("User with given token not found in mysql db.")
        # FAILED TO AUTH
    else:
        now = "NOW()"
        mysql_now = cloudDB.execute_db("SELECT NOW()")
        entID = str(rows[0]["tblEntities"])
        exp_time = str(rows[0]["TokenExpiresAt"])
        mysql_comp_time = cloudDB.execute_db("SELECT '%s' > '%s' AS 'res'" % (mysql_now[0]["NOW()"], exp_time))
        if mysql_comp_time[0]["res"] == 1:
            return False
        n_t_ex = "DATE_ADD(NOW(), INTERVAL 1 HOUR)"
        cloudDB.update_db("UPDATE tblUsers SET TokenIssuedAt = %s WHERE tblEntities = '%s'" % (now, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenExpiresAt = %s WHERE tblEntities = '%s'" % (n_t_ex, entID))
        cloudDB.update_db("UPDATE tblUsers SET LastActivityDate = %s WHERE tblEntities = '%s'" % (now, entID))
        return rows[0]
    # headers = {'X-Auth-Token':token, 'X-Subject-Token':token}
    # r = requests.get(AUTH_URL + "/auth/tokens", headers=headers)
    # log.info(r.text)
    # log.info(r.headers)
    # log.info(r.status_code)
    return False


def trim_uri(uri):
    counter = 0
    pos = 0
    for i, c in enumerate(uri):
        if "/" == c:
            counter += 1
        if counter == 3:
            pos = i
            break
    return "/" + uri[(pos + 1):]


def load_owned_objects_rec(ent_id, depth):
    # THIS SHOULD RETURN ONE ARRAY OF NESTED ARRAYS OF DICTIONARIES
    # TODO Recursively load all objects that the user has control over
    # Takes a ACLEntityID
    # Looks at all entities with that parent ID
    # For each entity, look at other entities that are children of that entity
    # Don't go deeper than VDC?
    # Maybe load everything and then sort out unnecessary
    if ent_id == 0:
        ent_id = 1

    print(depth)

    ents = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s'" % (ent_id))
    # if len(ents) == 1:
    if len(ents) == 0 or ents is None:
        return dict()

    data = []
    for ent in ents:
        data.append(ent)
        data.append(load_owned_objects_rec(ent["id"], depth + 1))

    return data


def load_owned_objects_rec_nonnest(ent_id, array):
    # THIS SHOULD RETURN ONE ARRAY OF ALL OF THE DICTIONARIES
    # Takes a ACLEntityID
    # Looks at all entities with that parent ID
    # For each entity, look at other entities that are children of that entity
    # Don't go deeper than VDC?
    # Maybe load everything and then sort out unnecessary
    if ent_id == 0 or ent_id == 1:
        log.critical("This method should not be used with IT")
        return
    ents = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s'" % (ent_id))
    # if len(ents) == 1:
    if len(ents) is not 0 and ents is not None:
        for ent in ents:
            # if ent["EntityType"] == "organization" or ent["EntityType"] == "department" or ent["EntityType"] == "imagelibrary" or ent["EntityType"] == "vdc":  # TODO how to use this
            array.append(ent)
            load_owned_objects_rec_nonnest(ent["id"], array)


def load_owned_objects_rec_nonnest_type_limited(ent_id, array, enttype):
    if ent_id == 0 or ent_id == 1:
        log.critical("This method should not be used with IT")
        return
    ents = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s'" % (ent_id))
    # if len(ents) == 1:
    if len(ents) is not 0 and ents is not None:
        for ent in ents:
            if ent["EntityType"] == enttype:
                array.append(ent)
            load_owned_objects_rec_nonnest_type_limited(ent["id"], array, enttype)


def authorization_object_check_rec(ent_id, uuid_to_compare_to):
    """
    Recursively checks if you own object for which you provide the uuid
    :param ent_id:
    :param uuid_to_compare_to:
    :return: boolean about authorization
    """
    if ent_id == 0 or ent_id == 1:
        log.critical("This method should not be used with IT")
        return
    ents = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s'" % ent_id)
    if len(ents) is not 0 and ents is not None:
        for ent in ents:
            if str(ent["UniqueId"]) in str(uuid_to_compare_to):
                return True
            if authorization_object_check_rec(ent["id"], uuid_to_compare_to):
                return True
    return False


def authorization_object_check_bot_up(obj_ent_id, user_acl_id):
    if user_acl_id == 0 or user_acl_id == 1:
        return True
    obj = cloudDB.get_row_dict("tblEntities", {"id": obj_ent_id})
    parent_ent_id = obj["ParentEntityId"]

    if parent_ent_id == user_acl_id:
        return True
    if obj["id"] == 1:
        return False

    return authorization_object_check_bot_up(parent_ent_id, user_acl_id)


# def load_all_orgs():
#     orgs = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("organization"))
#     orgsArr = []
#     for org in orgs:
#         orgsArr.append(org)
#         # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
#         # for dept in depts:
#         #     array.append(dept)
#     return orgsArr
#
#
# def load_all_ilibs():
#     libs = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("imagelibrary"))
#     libraries = []
#     for lib in libs:
#         libraries.append(lib)
#         # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
#         # for dept in depts:
#         #     array.append(dept)
#     return libraries


def load_all(type):
    things = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % (type))
    arr = []
    for thing in things:
        if not (thing["Name"] == "infrastructure" and type == "slice_attached_network"):
            arr.append(thing)
    return arr


# def load_system_ilibs():
#     # load all ilibs that are children of slice
#     slices = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("slice"))
#     libraries = []
#     for slice in slices:
#         libs = cloudDB.get_multiple_row("tblEntities",
#                                         "EntityType='%s' AND ParentEntityId='%s'" % ("imagelibrary", slice["id"]))
#         for lib in libs:
#             libraries.append(lib)
#             # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
#             # for dept in depts:
#             #     array.append(dept)
#     return libraries

def load_system_owned(enttype):
    # load all ilibs that are children of slice
    slices = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("slice"))
    objects = []
    for slice in slices:
        things = cloudDB.get_multiple_row("tblEntities",
                                          "EntityType='%s' AND ParentEntityId='%s'" % (enttype, slice["id"]))
        for thing in things:
            objects.append(thing)
            # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
            # for dept in depts:
            #     array.append(dept)
    return objects


# def load_all_depts(orgs_mysql_result):
#     deptsArr = []
#     for org in orgs_mysql_result:
#         depts = cloudDB.get_multiple_row("tblEntities",
#                                          "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
#         for dept in depts:
#             deptsArr.append(dept)
#     return deptsArr


def load_ent_details(uuid):
    return cloudDB.get_row_dict("tblEntities", {"UniqueId": uuid})


def load_owned(parent_ent_id, type):
    if type == "slice_attached_network":
        return load_all(type)
    arr = []
    things = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (parent_ent_id, type))
    for thing in things:
        arr.append(thing)
    return arr


def get_parent_details(child_id):
    child_p_id = cloudDB.get_row_dict("tblEntities", {"id": child_id})["ParentEntityId"]
    return cloudDB.get_row_dict("tblEntities", {"id": child_p_id})


def get_acl_role(aclID):
    user = cloudDB.get_row("tblEntitiesACL", "AclEntityId='%s'" % (aclID))
    return user["AclRole"]


def load_all_available(vdc_id, enttype):
    # needs to return system libraries and libraries owned by parent department and by organization
    # assumming that ent_id_parent is department id since that is the parent of a vdc
    dept_id = get_parent_details(vdc_id)["id"]
    org_id = get_parent_details(dept_id)["id"]
    return load_owned(vdc_id, enttype) + load_owned(dept_id, enttype) + load_owned(org_id, enttype) + load_system_owned(
        enttype)


def load_auth_dep_vir_nets(vdc_id):
    enttype = "virtual_network"
    first = cloudDB.get_multiple_row("tblAttachedEntities", "AttachedEntityId='%s'" % vdc_id)
    if len(first) == 0:
        return []
    virnets = []
    for att in first:
        print att
        virnets.append(cloudDB.get_row_dict("tblEntities", {"id": att["tblEntities"]}))
    return virnets


def load_all_available_vir_nets(vdc_id):
    # needs to return system libraries and libraries owned by parent department and by organization
    # assumming that ent_id_parent is department id since that is the parent of a vdc
    dept_id = get_parent_details(vdc_id)["id"]
    org_id = get_parent_details(dept_id)["id"]
    enttype = "virtual_network"
    dept_spec = load_auth_dep_vir_nets(vdc_id)
    return load_owned(vdc_id, enttype) + load_owned(org_id, enttype) + dept_spec


# TODO WITH ALL MYSQL SEARCHES, MAKE SURE ROW DELETED == 0; replace get_row with get_row_dict

# def json_list_objects_arr(address, givens, aclRole): #TODO THIS NEEDS TO PROVIDE ERROR IF RESPONSE IS BLANK!!!
#     jStack = {}
#
#     organizations = {}
#     libraryimage = {}
#     departments = {}
#     virtual_networks = {}
#     vdcs_complete = {}
#
#     objects = [organizations, libraryimage, departments, virtual_networks, vdcs_complete]
#
#     jStack.update({"uri": address, "user_type": aclRole})
#     for one in givens:
#         num = len(one)
#         oneSpecs = {"type": None, "total": num}  # TODO Type needs to be established
#         elements = []
#         for thing in one:
#             element = {"name": thing["Name"]}
#
#             # details = load_ent_details(thing["UniqueId"])
#             # for key, value in details.iteritems():
#             #     element.update({str(key): str(value)}) # DUMP ALL DETAILS
#
#             element.update({"uuid": thing["UniqueId"]})
#             selfLinkString = thing["EntityType"] + "/" + thing["UniqueId"]
#             element.update({"links": {"self": selfLinkString}})
#             elements.append(element)
#         oneSpecs.update({"elements": elements})
#         if len(elements) > 0:
#             new = {one[0]["EntityType"]: oneSpecs}
#             jStack.update(new)
#
#     return jStack


def json_list_objects_arr(address, givens, aclRole):  # TODO THIS NEEDS TO PROVIDE ERROR IF RESPONSE IS BLANK!!!
    jStack = {}

    # organizations = {}
    # libraryimage = {}
    # departments = {}
    # virtual_networks = {}
    # vdcs_complete = {}
    #
    # objects = [organizations, libraryimage, departments, virtual_networks, vdcs_complete]

    for one in givens:
        num = len(one)
        jStack.update({"count": num})
        elements = []
        for thing in one:
            element = {"name": thing["Name"]}

            # details = load_ent_details(thing["UniqueId"])
            # for key, value in details.iteritems():
            #     element.update({str(key): str(value)}) # DUMP ALL DETAILS

            element.update({"uuid": thing["UniqueId"]})
            # selfLinkString = thing["EntityType"] + "s/" + thing["UniqueId"]
            # element.update({"links": {"self": selfLinkString}})
            element.update({"type": thing["EntityType"]})
            elements.append(element)
        if len(elements) > 0:
            jStack.update({"elements": elements})

    return jStack


def testObjectLoading():
    aclID = 0
    aclRole = get_acl_role(aclID)
    objects = []
    if aclID == 0 or aclID == 1:
        # ITSA LEVEL
        objects.append(load_all("organization"))
        objects.append(load_all_available())
        # depts = load_all_depts(orgs)
    else:
        objects.append(load_owned(parent_ent_id=aclID, type="imagelibrary"))
        objects.append(load_owned(parent_ent_id=aclID, type="department"))
        objects.append(load_owned(parent_ent_id=aclID, type="virtual_network"))
        objects.append(load_owned(parent_ent_id=aclID, type="vdc"))
    jStack = json_list_objects_arr('/', objects, aclRole)
    print json.dumps(jStack, sort_keys=True, indent=4, separators=(',', ': '))


def listAll(acls, addr):
    # testObjectLoading()
    for acl in acls:
        aclID = acl["AclEntityId"]
        aclRole = get_acl_role(aclID)
        objects = []
        if aclID == 0 or aclID == 1:
            # ITSA LEVEL
            objects.append(load_all("organization"))
            objects.append(load_system_owned("imagelibrary"))
        elif aclRole == "vdc":
            # VDC USER LEVEL NEEDS SPECIAL CASE
            return False
        else:
            print aclID
            objects.append(load_owned(parent_ent_id=aclID, type="imagelibrary"))
            objects.append(load_owned(parent_ent_id=aclID, type="department"))
            objects.append(load_owned(parent_ent_id=aclID, type="virtual_network"))
            objects.append(load_owned(parent_ent_id=aclID, type="vdc"))

    jStack = json_list_objects_arr(addr, objects, aclRole)
    stringVal = json.dumps(jStack, sort_keys=True, indent=4, separators=(',', ': '))
    return stringVal


def get_spec_details(obj_uuid, obj_type, acls, canSeeDetails=False):
    details = load_ent_details(obj_uuid)  # THESE ARE DETAILS OF PARENT FOR WHOM WE MAKE A CHILD
    for a in acls:
        if authorization_object_check_bot_up(details["id"], a["AclEntityId"]):
            canSeeDetails = True
            break
    if canSeeDetails is False:
        return None  # TODO UNAUTHORIZED
    details = load_ent_details(obj_uuid)  # THESE ARE DETAILS OF PARENT FOR WHOM WE MAKE A CHILD
    if details is None:
        print "BLANK DETAILS" + obj_uuid
    return details


def get_all_parents(obj_ent_id, array):
    # Array will be array of parents
    obj = cloudDB.get_row_dict("tblEntities", {"id": obj_ent_id})
    parent_ent_id = obj["ParentEntityId"]

    if obj["id"] != 1:
        array.append(obj)
        get_all_parents(parent_ent_id, array)


def load_spec_uri(bottom_child_details):
    if bottom_child_details is None:
        return None
    if len(bottom_child_details) == 0:
        return None
    print bottom_child_details
    print len(bottom_child_details)
    res = []
    # get_all_parents(bottom_child_details["id"], res)
    # for parent in res:
    # print parent["EntityType"] + " " + str(parent["Name"])
    return trim_uri(cloudDB.get_row_dict("tblUris", {"tblEntities": bottom_child_details["id"]})["uri"])


def dict_keys_to_lower(dict):
    new_dict = {}
    for key in dict:
        new_dict.update({str(key).lower(): dict[key]})
    return new_dict


def perform_action(reqm, details, obj_uuid, obj_type, user_data, post_data):
    global RES_CODE
    from entity.entity_functions import EntityFunctions
    import rest.rest_api as rest
    import utils.cloud_utils

    print "PERFORMING ACTION: " + reqm + " " + obj_uuid + " " + obj_type
    if reqm == "POST" or reqm == "PUT":
        # details are the details of parents since we are creating a child
        # create entry in local database
        # post request to cfd

        try:
            data = json.loads(post_data)
            data = dict_keys_to_lower(data)
            if len(data) == 0:
                return False
            data["name"]
        except:
            print sys.exc_info()
            return "ERROR: Entity name was not provided"

    if reqm == "POST" or reqm == "PUT" or reqm == "GET" or reqm == "DELETE":
        if obj_type == "switch":
            obj_type = "switch_network_service"
            obj_cont_name = "Subnet"
        elif obj_type == "nats":
            obj_type = "nat_network_service"
            obj_cont_name = "Nat"
        elif obj_type == "external-networks":
            obj_type = "externalnetwork"
            obj_cont_name = "ExternalNetwork"
        elif obj_type == "firewalls":
            obj_type = "fws_network_service"
            obj_cont_name = "Firewall"
        elif obj_type == "load-balancers":
            obj_type = "lbs_network_service"
            obj_cont_name = "LoadBalancer"
        elif obj_type == "routers":
            obj_type = "rts_network_service"
            obj_cont_name = "Router"
        elif obj_type == "vpns":
            obj_type = "sslvpn_network_service"
            obj_cont_name = "VPN"
        elif obj_type == "monitors":
            obj_type = "nms_network_service"
            obj_cont_name = "Monitor"
        elif obj_type == "server-farms":
            obj_type = "serverfarm"
            obj_cont_name = "ServerFarm"
        elif obj_type == "servers":
            obj_type = "server"
            obj_cont_name = "Server"
        elif obj_type == "containers":
            obj_type = "container"
            obj_cont_name = "Container"
        elif obj_type == "volumes":
            obj_type = "volume"
            obj_cont_name = "Volume"
        elif obj_type == "security-groups":
            obj_type = "security_group"
            obj_cont_name = "SecurityGroup"
        elif obj_type == "security-rules":
            obj_type = "security_rule"
            obj_cont_name = "SecurityRule"
        elif obj_type == "acl-groups":
            obj_type = "acl_group"
            obj_cont_name = "AccessGroup"
        elif obj_type == "acl-rules":
            obj_type = "acl_rule"
            obj_cont_name = "AccessRule"
        elif obj_type == "load-balancer-groups":
            obj_type = "lbs-group"
            obj_cont_name = "LbsGroup"
        elif obj_type == "load-balancer-services":
            obj_type = "lbs_service"
            obj_cont_name = "LbsService"
        elif obj_type == "vpn-groups":
            obj_type = "vpn_group"
            obj_cont_name = "VpnGroup"
        elif obj_type == "ipsec-tunnels":
            obj_type = "ipsecvpn_network_service"
            obj_cont_name = "VpnConnection"
        elif obj_type == "interfaces":
            obj_type = "network_interface"
            obj_cont_name = "Interface"
        elif obj_type == "vdcs" or obj_type == "departments":
            obj_type = "vdc"
            obj_cont_name = "Vdc"
        else:
            return "ERROR: Invalid entity type desired"

        slice_row = cloudDB.get_row("tblSlices", "tblEntities='28'")
        slice_row_lower = utils.cloud_utils.lower_key(slice_row)
        headers = {"Content-Type": "clouds.net." + obj_cont_name + "+json"}
        spec_uri = load_spec_uri(bottom_child_details=details)
        entity_res = ""
        print headers
        print spec_uri

        if reqm == "POST":
            r = rest.post_rest(UA + spec_uri, data, headers)
            if r["http_status_code"] == 200 or r["http_status_code"] == 201 or r["http_status_code"] == 202:
                options = data
                if details is not None:
                    options.update({"parententityid": details["id"]})
                options.update({"entitytype": obj_type})
                entity = EntityFunctions(db=cloudDB, dbid=0, slice_row=slice_row_lower)
                entity_res = entity._create(cloudDB, options)

                # print UA + spec_uri
                # print json.dumps(options)
                # print headers
                entity.update_all_service_uris(cloudDB, r, slice_url=UA)
                RES_CODE = "201 Created"
        elif reqm == "PUT":  # TODO How to handle provisioining/deprovisioning?
            r = rest.put_rest(UA + spec_uri, data, headers)
            if r["http_status_code"] == 200 or r["http_status_code"] == 201 or r["http_status_code"] == 202:
                options = data
                print options
                VDCID = get_parent_details(details["id"])["id"]
                entity = EntityFunctions(db=cloudDB, dbid=details["id"], slice_row=slice_row_lower)
                # print options
                # print entity._update(cloudDB, options, do_get=True)
                entity_res = entity._update(cloudDB, options)  # TODO This does not update throughputs
                import entity.entity_commands

                entity.entity_commands.update_multiple(cloudDB, details["id"], options)
                RES_CODE = "202 Accepted"
        elif reqm == "GET":
            r = rest.get_rest(UA + spec_uri, headers)
            entity_res = {"uuid": details["UniqueId"]}
            RES_CODE = "200 OK"
        elif reqm == "DELETE":
            r = rest.delete_rest(UA + spec_uri, headers)
            if r["http_status_code"] == 200 or r["http_status_code"] == 201 or r["http_status_code"] == 202:
                options = {"parententityid": details["id"]}
                options.update({"entitytype": obj_type})
                entity = EntityFunctions(db=cloudDB, dbid=details["id"], slice_row=slice_row_lower)
                entity_res = entity._delete(cloudDB, options)
                RES_CODE = "202 Accepted"
        try:
            created_entity_uri = r["uri"]
        except:
            # print sys.exc_info()
            if reqm != "DELETE":
                return "ERROR: Incorrect/Empty CDF Response: " + str(r)

        comp_res = {"CDF": r, "HAWK-DB": json.loads(entity_res)}
        return comp_res
        # return "CDF RESPONSE:\n" + json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')) + "\nHAWK-DB RESPONSE:\n" + str(entity_res)

    return False


# REM curl -s -S -i -X DELETE http://localhost:8091/v2/switch/d9f5dbf5-9eb5-4b17-a25a-3e0d34ac1fcf --header "X-Auth-Token: 0dee56c9a49a4957bcf3639729aa4598"
# REM curl -s -S -i -X DELETE http://cfd23.does-it.net:8231/Organization-2817-adbf/org10/dept12/vdc73/nets/net329 --header "Content-Type: application/cloudflow.net.cloud.Subnet+json"
#
# REM curl -s -S -i -X DELETE http://cfd23.does-it.net:8231/Vadim-Organization/org8/dept11/vdc22/nets/net7 --header "Content-Type: application/cloudflow.net.cloud.Subnet+json"
#
# REM curl -s -S -i -X POST http://localhost:8091/v2/14ab8813-00a6-48bd-9c8d-65b862331c5e/servers -d "{\"name\":\"New_Switches_A\"}" --header "X-Auth-Token: 0dee56c9a49a4957bcf3639729aa4598"
# REM curl -s -S -i -X PUT http://localhost:8091/v2/switch/770060cb-a082-490f-81b4-dc4454a9aed9 -d "{\"name\":\"New_Switches_B\"}" --header "X-Auth-Token: 0dee56c9a49a4957bcf3639729aa4598"
# curl -s -S -i -X DELETE http://localhost:8091/v2/switch/770060cb-a082-490f-81b4-dc4454a9aed9 --header "X-Auth-Token: 0dee56c9a49a4957bcf3639729aa4598"

def special_process(action_type, split, reqm, acls, user_data, post_data):
    print "SPECIAL THINGS: " + action_type + " " + str(split) + " " + reqm
    # TODO Group by create, update, get, delete actions?
    if reqm == "POST":  # CREATING AN OBJECT UNDER ANOTHER OBJECT
        if action_type == "vdcs":
            obj_type = "vdcs"
            if len(split) == 3:
                obj_uuid = split[1]
                obj_type = split[0]
        elif len(split) > 0:  # ASSUME UUID IS PRESENT UNDER split[0]
            obj_uuid = split[0]
            obj_type = split[1]
    else:
        if len(split) > 1:  # ASSUME UUID IS PRESENT UNDER split[1]
            obj_uuid = split[1]
            obj_type = split[0]

    if obj_type is None or obj_uuid is None:
        return "ERROR: Entity type or uuid not specified"
    details = get_spec_details(obj_uuid, obj_type, acls, True)
    if not details:
        return "ERROR: Parent details not found"
    # print details
    return perform_action(reqm, details, obj_uuid, obj_type, user_data, post_data)  # assume authenticated


def request_api(addr, userData, reqm, post_data):
    # address is relative url
    # data comes in json format
    # TODO Permission checking in: load_all; load_ent_details; load_owned
    if addr[len(addr) - 1:] == '/':
        addr = addr[:-1]

    user_ent_id = userData["tblEntities"]
    acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (user_ent_id))
    aclID = acls[0]["AclEntityId"]
    aclRole = get_acl_role(aclID)

    print "API REQUEST: " + addr + " " + post_data + " " + str(reqm) + " " + aclRole

    split = addr[1:].split('/')
    specific_action_addresses = ["switch", "nats", "firewalls", "load-balancers", "routers",
                                 "vpns", "monitors", "computer-services", "server-farms", "servers",
                                 "containers", "volumes", "security-groups", "security-rules",
                                 "acl-groups", "acl-rules", "load-balancer-groups", "load-balancer-services",
                                 "vpn-groups", "ipsec-tunnels", "interfaces"]
    duplicate_specific_action_addresses = ["external-networks", "virtual-networks", "image-libraries"]

    for part in split:
        if part in duplicate_specific_action_addresses and len(split) > 1:
            if split[0] in duplicate_specific_action_addresses or split[1] in duplicate_specific_action_addresses:
                return special_process(part, split, reqm, acls, userData, post_data)
        if part in specific_action_addresses:
            return special_process(part, split, reqm, acls, userData, post_data)
        if "vdcs" in part and (reqm == "PUT" or reqm == "DELETE"):
            return special_process(part, split, reqm, acls, userData, post_data)

    if addr == '/listAll' and reqm == "GET":
        stringVal = listAll(acls, addr)
        print stringVal
        return stringVal
    elif reqm == "POST" or reqm == "PUT" or reqm == "DELETE":
        if len(split) == 3:
            if split[2] == "vdcs":
                if len(split[1]) == 36:
                    return special_process("vdcs", split, reqm, acls, userData, post_data)

    elif reqm == "GET":
        data = []

        if aclRole == "IT":
            if len(split) < 2:
                if split[0] == "organizations":
                    object_type = "organization"
                elif split[0] == "external-networks":
                    object_type = "slice_attached_network"
                elif split[0] == "image-libraries":
                    object_type = "imagelibrary"
                else:
                    return False

                data.append(load_all(object_type))
                if len(data) > 0:
                    return json_list_objects_arr(addr, data, aclRole)
            else:
                if len(split[1]) == 36:
                    details = load_ent_details(split[1])
                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in split[0]:
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        element = {}
                        for key, value in details.iteritems():
                            element.update({str(key): str(value)})  # DUMP ALL DETAILS
                        return element

                    elif len(split) == 3:  # details about nested thing like departments/uuid/vdcs
                        ent_id_parent = details["id"]
                        object_type = split[2][:-1]
                        if object_type == "external-network":
                            object_type = "slice_attached_network"
                        elif object_type == "image-librarie":
                            object_type = "imagelibrary"
                        elif object_type == "virtual-network":
                            object_type = "virtual_network"

                        if object_type == "imagelibrary" and split[0] == "vdcs":
                            data.append(load_all_available(vdc_id=ent_id_parent, enttype=object_type))
                        elif object_type == "virtual_network" and split[0] == "vdcs":
                            data.append(load_all_available_vir_nets(ent_id_parent))  # this is wrong, too simple
                        else:
                            data.append(load_owned(ent_id_parent, object_type))
                        return json_list_objects_arr(addr, data, aclRole)



        elif aclRole == "organization":
            if len(split) < 2:  # listing
                if split[0] == "departments":
                    object_type = "department"
                elif split[0] == "external-networks":
                    object_type = "slice_attached_network"
                elif split[0] == "image-libraries":
                    object_type = "imagelibrary"
                elif split[0] == "virtual-networks":
                    object_type = "virtual_network"
                else:
                    return False
                data.append(load_owned(aclID, object_type))
                if len(data) > 0:
                    return json_list_objects_arr(addr, data, aclRole)
            else:  # maybe redundant with IT just add this to it as well and remove aclRole if separation
                if len(split[1]) == 36:
                    details = load_ent_details(uuid=split[1])
                    if not authorization_object_check_bot_up(details["id"], aclID):
                        # make sure you actually own this
                        log.critical("ATTEMPT TO ACCESS ILLEGAL OBJECT")
                        print "ATTEMPT TO ACCESS ILLEGAL OBJECT"
                        return "Forbidden"

                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in split[0]:
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        element = {}
                        for key, value in details.iteritems():
                            element.update({str(key): str(value)})  # DUMP ALL DETAILS
                        return get_dict_details(details)

                    elif len(split) == 3:  # details about nested thing like departments/uuid/vdcs
                        ent_id_parent = details["id"]
                        object_type = split[2][:-1]
                        if object_type == "external-network":
                            object_type = "slice_attached_network"
                        elif object_type == "image-librarie":
                            object_type = "imagelibrary"
                        elif object_type == "virtual-network":
                            object_type = "virtual_network"

                        if object_type == "imagelibrary" and split[0] == "vdcs":
                            data.append(load_all_available(vdc_id=ent_id_parent, enttype=object_type))
                        elif object_type == "virtual_network" and split[0] == "vdcs":
                            data.append(load_all_available_vir_nets(ent_id_parent))  # this is wrong, too simple
                        else:
                            data.append(load_owned(ent_id_parent, object_type))
                        return json_list_objects_arr(addr, data, aclRole)



        elif aclRole == "department":
            acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (user_ent_id))
            resultantData = []
            canSeeDetails = False
            if len(split) >= 2:
                if len(split[1]) == 36:
                    details = load_ent_details(uuid=split[1])
                    for a in acls:
                        if authorization_object_check_bot_up(details["id"], a["AclEntityId"]):
                            canSeeDetails = True
                            break
            if len(split) < 2:  # listing
                for a in acls:
                    data = []
                    aclID = a["AclEntityId"]
                    aclRole = get_acl_role(aclID)
                    if len(split) < 2:  # listing
                        if split[0] == "vdcs":
                            object_type = "vdc"
                        elif split[0] == "external-networks":
                            object_type = "slice_attached_network"
                        elif split[0] == "image-libraries":
                            object_type = "imagelibrary"
                        elif split[0] == "virtual-networks":
                            object_type = "virtual_network"
                        else:
                            return False
                        data += (load_owned(aclID, object_type))
                        if len(data) > 0:
                            resultantData += data
            else:
                if len(split[1]) == 36:
                    if not canSeeDetails:
                        # make sure you actually own this
                        log.critical("ATTEMPT TO ACCESS ILLEGAL OBJECT")
                        print "ATTEMPT TO ACCESS ILLEGAL OBJECT"
                        return "Forbidden"

                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in split[0]:
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        element = {}
                        for key, value in details.iteritems():
                            element.update({str(key): str(value)})  # DUMP ALL DETAILS
                        return element

                    elif len(split) == 3:  # details about nested thing like departments/uuid/vdcs
                        ent_id_parent = details["id"]
                        object_type = split[2][:-1]
                        if object_type == "image-librarie":
                            object_type = "imagelibrary"
                        elif object_type == "virtual-network":
                            object_type = "virtual_network"

                        if object_type == "imagelibrary" and split[0] == "vdcs":
                            data += (load_all_available(vdc_id=ent_id_parent, enttype=object_type))
                        elif object_type == "virtual_network" and split[0] == "vdcs":
                            data += (load_all_available_vir_nets(ent_id_parent))  # this is wrong, too simple
                        else:
                            data += (load_owned(ent_id_parent, object_type))
                        resultantData += data
            if len(resultantData) > 0:
                resultantData = json_list_objects_arr(addr, [resultantData], aclRole)
                return resultantData



        elif aclRole == "vdc":
            acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (user_ent_id))
            resultantData = []
            canSeeDetails = False
            if len(split) >= 2:
                if len(split[1]) == 36:
                    details = load_ent_details(uuid=split[1])
                    for a in acls:
                        oneVDC = cloudDB.get_row_dict("tblEntities", {"id": a["AclEntityId"]})
                        if details["id"] == oneVDC["id"]:
                            canSeeDetails = True
                            break

            if len(split) < 2:  # listing
                for a in acls:
                    data = []
                    oneVDC = cloudDB.get_row_dict("tblEntities", {"id": a["AclEntityId"]})
                    vdcID = oneVDC["id"]
                    dept_id = get_parent_details(vdcID)["id"]
                    if split[0] == "vdcs":
                        object_type = "vdc"
                        data += [oneVDC]
                    elif split[0] == "external-networks":
                        object_type = "slice_attached_network"
                        data += load_owned(dept_id, object_type)
                    elif split[0] == "image-libraries":
                        object_type = "imagelibrary"
                        data += load_all_available(vdc_id=vdcID, enttype=object_type)
                    elif split[0] == "virtual-networks":
                        object_type = "virtual_network"
                        data += load_all_available_vir_nets(vdcID)
                    else:
                        return False
                    if len(data) > 0:
                        resultantData += data
                if len(resultantData) > 0:
                    resultantData = json_list_objects_arr(addr, [resultantData], aclRole)
                    return resultantData
            else:
                if len(split[1]) == 36:
                    if not canSeeDetails:
                        # make sure you actually own this
                        log.critical("ATTEMPT TO ACCESS ILLEGAL OBJECT")
                        print "ATTEMPT TO ACCESS ILLEGAL OBJECT"
                        return "Forbidden"

                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in split[0]:
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        element = {}
                        for key, value in details.iteritems():
                            element.update({str(key): str(value)})  # DUMP ALL DETAILS
                        return element

    return False


class OutputManager(object):  # TODO Format json
    def api_info(self):
        return [json.dumps({"API": {"Version": "2"}}, sort_keys=True, indent=4, separators=(',', ': '))]

    def no_post_data(self):
        return ['{"Error": "Missing/incorrect post data submitted"}']

    def auth_failed(self):
        return ['{"Unauthorized": "Authentication failed"}']

    def auth_success(self, tokenResp):
        return [tokenResp]

    def no_auth_token(self):
        return ['{"Error": "No auth-token present"}']

    def api_response(self, token, api_response):
        # return ["TOKEN VALID: " + token + "\nAPI RESPONSE:\n" + api_response]
        global RES_CODE
        if str(api_response) == "False":
            RES_CODE = "400 Bad Request"
            api_response = "BAD API REQUEST"
        elif str(api_response) == "Forbidden":
            RES_CODE = "403 Forbidden"
            api_response = "API: Forbidden"
        elif "ERROR" in str(api_response):
            RES_CODE = "400 Bad Request"

        dic = {"Token": {"ID": token, "Status": "Valid"}, "API Response": api_response}
        return json.dumps(dic, sort_keys=True, indent=4, separators=(',', ': '))

    def token_invalid(self, token):
        return [
            json.dumps({"Token": {"ID": token, "Status": "Invalid"}}, sort_keys=True, indent=4, separators=(',', ': '))]

    def wrong_api_version(self):
        return ['{"Error": "Malformed/Unsupported API Version"}']


def serve(env, start_response):
    oman = OutputManager()
    global RES_CODE
    path = env['PATH_INFO']
    defresponse_header = [('Content-Type', 'cloudflows.net+json')]

    apiVer = path[:3]  # contains starting / no trailing /
    if apiVer == '/':
        start_response('200 OK', defresponse_header)
        return oman.api_info()
    elif apiVer == "/v2":
        path = path[3:]  # contains starting / no trailing /
        if path == '/authenticate' and env['REQUEST_METHOD'] == "POST":
            response_header = [('Content-Type', 'cloudflows.net.Authenticate+json')]
            start_response('200 OK', response_header)

            try:
                request_body_size = int(env.get('CONTENT_LENGTH', 0))
            except (ValueError):
                request_body_size = 0
            request_body = env['wsgi.input'].read(request_body_size)
            data = parse_qs(request_body)
            if len(data) == 0:
                start_response('400 Bad Request', defresponse_header)
                return oman.no_post_data()
            try:
                user = escape(data.get("user")[0])
                passw = escape(data.get("pass")[0])
                dname = escape(data.get("domain")[0])
            except (TypeError):
                start_response('400 Bad Request', defresponse_header)
                return oman.no_post_data()
            tokenResp = get_token_json_response(user, dname, passw)
            if tokenResp is False:
                start_response('401 Unauthorized', response_header)
                return oman.auth_failed()
            return oman.auth_success(tokenResp)
        elif path == '/':
            return oman.api_info()
        else:
            try:
                token = env['HTTP_X_AUTH_TOKEN']
            except KeyError:
                start_response('400 Bad Request', defresponse_header)
                return oman.no_auth_token()

            try:
                request_body_size = int(env.get('CONTENT_LENGTH', 0))
            except (ValueError):
                request_body_size = 0
            data = env['wsgi.input'].read(request_body_size)
            userData = validate_token(token)
            if userData is not False:
                apiResponse = request_api(path, userData, env['REQUEST_METHOD'], data)
                str_res = oman.api_response(token, apiResponse)
                start_response(RES_CODE, defresponse_header)
                return str_res

            # else cannot auth
            RES_CODE = "401 Unauthorized"
            start_response(RES_CODE, defresponse_header)
            return oman.token_invalid(token)
    else:
        start_response(RES_CODE, defresponse_header)
        return oman.wrong_api_version()


import utils.cloud_utils

utils.cloud_utils.setup_flags_logs('hawk-rpc.log', flagfile='cloudflow_flags.conf', logdir=None, init_logger=True)
wsgi.server(eventlet.listen(('', 8091)), serve)
