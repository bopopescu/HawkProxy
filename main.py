__author__ = 'vkorolik'
# import ujson as json
import json
import logging
import pprint
from urlparse import parse_qs
from cgi import escape
import sys
import datetime

import eventlet
from eventlet.green import urllib2
from eventlet import wsgi
import requests
import pytz

import utils.gflags_collection
import cryptC as crypt
import utils.cloud_utils
from utils.cloud_utils import CloudGlobalBase
from entity.entity_functions import EntityFunctions
import entity.entity_commands
import entity.validate_entity
import entity.entity_manager as ent_man
import rest.rest_api as rest
import utils.cloud_utils
import api_actions

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

local = pytz.timezone("America/Los_Angeles")
naive = datetime.datetime.strptime("2001-2-3 10:11:12", "%Y-%m-%d %H:%M:%S")
local_dt = local.localize(naive, is_dst=None)
utc_dt = local_dt.astimezone(pytz.utc)

pp = pprint.PrettyPrinter(indent=4)

cloudDB = CloudGlobalBase(pool=False)

RES_CODE = "400 Bad Request"

# TODO In all queries, resulting rows can be None if query fails or db connection fails, causing TypeError on len call
# TODO Why does gui treat api-made vdcs as network service?
# WITH ALL MYSQL SEARCHES, MAKE SURE ROW DELETED == 0; replace get_row with get_row_dict

def fetch(url):
    return urllib2.urlopen(url).read()


def get_token_json_response(un, pa):
    sec = "6apC3IcauIeKd5StPTjWzTBXFzQXvooHanb4qxnePzccX4SFBt"
    passw = crypt.crypt(pa, sec)
    headers = {'Content-Type': 'application/json'}
    responses = []
    for domain in ["System", "CloudFlow"]:
        payload = {
            "auth": {
                "identity": {
                    "methods": [
                        "password"
                    ],
                    "password": {
                        "user": {
                            "domain": {
                                "name": domain
                            },
                            "name": un,
                            "password": passw
                        }
                    }
                }
            }
        }
        r = requests.post(AUTH_URL + "/auth/tokens", data=json.dumps(payload), headers=headers)
        log.info("AUTH RESP BODY: %s", json.loads(r.text))
        log.info("AUTH RESP HEADERS: %s", str(r.headers))
        responses.append(r)
    proc1 = process_raw_token_data(responses[0].text, responses[0].headers, un)
    proc2 = process_raw_token_data(responses[1].text, responses[1].headers, un)
    if proc1 is not False:
        return proc1
    elif proc2 is not False:
        return proc2
    else:
        return False


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


def process_raw_token_data(body, headers, uname):
    # RETURNS JSON THAT SHOULD BE GIVEN AS RESPONSE TO AUTHENTICATE REQUEST
    """

    :param body:
    :param headers:
    :param uname:
    :return: A token in string format if auth successful, otherwise False
    """
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
    # Recursively load all objects that the user has control over
    # Takes a ACLEntityID
    # Looks at all entities with that parent ID
    # For each entity, look at other entities that are children of that entity
    # Don't go deeper than VDC?
    # Maybe load everything and then sort out unnecessary
    if ent_id == 0:
        ent_id = 1

    print(depth)

    ents = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s'" % (ent_id))
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
    ents = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s'" % (ent_id))
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
    ents = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s'" % (ent_id))
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
    ents = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s'" % ent_id)
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
    if obj_ent_id == user_acl_id:
        return True
    print "obj: " + str(obj_ent_id)
    print "user: " + str(user_acl_id)
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
    things = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND EntityType='%s'" % (type))
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
    slices = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND EntityType='%s'" % ("slice"))
    objects = []
    for slice in slices:
        things = cloudDB.get_multiple_row("tblEntities",
                                          "deleted=0 AND EntityType='%s' AND ParentEntityId='%s'" % (enttype, slice["id"]))
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
    print parent_ent_id
    print type
    arr = []
    things = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s' AND EntityType='%s'" % (parent_ent_id, type))
    for thing in things:
        arr.append(thing)
    return arr

def load_all_owned(parent_ent_id):
    print parent_ent_id
    arr = []
    things = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s'" % (parent_ent_id))
    for thing in things:
        arr.append(thing)
    return arr

def get_parent_details(child_id):
    child_p_id = cloudDB.get_row_dict("tblEntities", {"id": child_id})["ParentEntityId"]
    return cloudDB.get_row_dict("tblEntities", {"id": child_p_id})


def get_acl_role(aclID):
    user = cloudDB.get_row_dict("tblEntitiesACL", {"AclEntityId": aclID})
    if user is not None:
        return user["AclRole"]
    else:
        return None


def load_all_available(vdc_id, enttype):
    # needs to return system libraries and libraries owned by parent department and by organization
    # assumming that ent_id_parent is department id since that is the parent of a vdc
    dept_id = get_parent_details(vdc_id)["id"]
    org_id = get_parent_details(dept_id)["id"]
    return load_owned(vdc_id, enttype) + load_owned(dept_id, enttype) + load_owned(org_id, enttype) + load_system_owned(
        enttype)


def load_auth_spec_vir_nets(child_id):
    enttype = "virtual_network"
    first = cloudDB.get_multiple_row("tblAttachedEntities", "AttachedEntityId='%s'" % child_id)
    if len(first) == 0:
        return []
    virnets = []
    for att in first:
        virnets.append(cloudDB.get_row_dict("tblEntities", {"id": att["tblEntities"]}))
    return virnets


def load_all_available_vir_nets(vdc_id):
    # needs to return system libraries and libraries owned by parent department and by organization
    # assumming that ent_id_parent is department id since that is the parent of a vdc
    dept_id = get_parent_details(vdc_id)["id"]
    #org_id = get_parent_details(dept_id)["id"]
    enttype = "virtual_network"
    dept_spec = load_auth_spec_vir_nets(vdc_id)
    org_spec = load_auth_spec_vir_nets(dept_id)
    return load_owned(vdc_id, enttype) + org_spec + dept_spec


# def json_list_objects_arr(address, givens, aclRole): # THIS NEEDS TO PROVIDE ERROR IF RESPONSE IS BLANK!!!
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
#         oneSpecs = {"type": None, "total": num}  # Type needs to be established
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

            if thing["EntityType"] == "vdc":
                parent_dept = get_parent_details(thing["id"])
                element.update({"ParentDepartmentName": parent_dept["Name"]})

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


def get_spec_details(obj_uuid, acls, canSeeDetails=False):
    details = load_ent_details(obj_uuid)  # THESE ARE DETAILS OF PARENT FOR WHOM WE MAKE A CHILD
    # print details
    if details is None:
        log.critical("CANNOT FIND DETAILS FOR OBJECT: " + obj_uuid)
        return None
    for a in acls:
        if authorization_object_check_bot_up(details["id"], a["AclEntityId"]):
            canSeeDetails = True
            break
    if canSeeDetails is False:
        return None  # TODO UNAUTHORIZED
    # details = load_ent_details(obj_uuid)  # THESE ARE DETAILS OF PARENT FOR WHOM WE MAKE A CHILD
    if details is None:
        log.critical("BLANK DETAILS" + str(obj_uuid))
    return details


def get_spec_details_with_parent_id(ent_type, name, parent_id):
    return cloudDB.get_row_dict("tblEntities", {"Name": name, "ParentEntityId": parent_id})

def get_spec_details_with_parent_id_notype(name, parent_id):
    return cloudDB.get_row_dict("tblEntities", {"Name": name, "ParentEntityId": parent_id})


def get_spec_details_with_entid(ent_id):
    return cloudDB.get_row_dict("tblEntities", {"id": ent_id})


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
    uri = cloudDB.get_row_dict("tblUris", {"tblEntities": bottom_child_details["id"]})
    if uri is None:
        return "URI NOT FOUND IN DATABASE"
    return trim_uri(uri["uri"])


def dict_keys_to_lower(dict):
    new_dict = {}
    for key in dict:
        new_dict.update({str(key).lower(): dict[key]})
    return new_dict


def create_interface(beg_serv_name, end_serv_name, interface_specs, vdc_id):
    # TODO check either beggining or end must be a switch?
    # TODO?!?!?!?!

    options = {}
    beggining_row = cloudDB.get_row_dict("tblEntities", {"Name": beg_serv_name, "ParentEntityId": vdc_id})
    ending_row = cloudDB.get_row_dict("tblEntities", {"Name": end_serv_name, "ParentEntityId": vdc_id})
    if beggining_row["EntityType"] == "externalnetwork":  # TODO is this right
        log.error("Attempt to create interface starting at extnet")
        return
    # if beggining_row["EntityType"] != "switch_network_service" and ending_row["EntityType"] != "switch_network_service":
    #     log.error("Attempt to create interface without at least one switch")
    #     return
    print beg_serv_name
    print end_serv_name
    print beggining_row
    print ending_row
    print vdc_id
    options.update({
        "beginserviceentityid": beggining_row["id"],
        "endserviceentityid": ending_row["id"],
        "ports": [
            {
                "serviceentityid": beggining_row["id"]
            },
            {
                "serviceentityid": ending_row["id"]
            }
        ],
        "beginserviceentityname": beg_serv_name,
        "endserviceentityname": end_serv_name,
        "interfaceindex": 0,
        "entitytype": "network_interface",
        "parententityid": vdc_id
    })
    entitya = EntityFunctions(db=cloudDB, dbid=0)
    entity_res = entitya._create(cloudDB, options)
    print entity_res


def create_interfaces(ent_name, interfaces_array, vdc_id):
    # TODO Handle interface params
    for interface in interfaces_array:
        beg_serv_name = ent_name
        end_serv_name = interface["subnet"]
        create_interface(beg_serv_name, end_serv_name, interface, vdc_id)


def convert_post_data_to_cfd(data):
    if data is None:
        log.critical("Passed null data")
        return None
    if "ssh_keys" in data.viewkeys():
        if isinstance(data["ssh_keys"], list):
            new_ssh_keys = []
            for ssh_key in data["ssh_keys"]:
                if "type" not in ssh_key.viewkeys():
                    continue
                key_type = ssh_key["type"]
                ssh_ent = {}
                if key_type == "user":
                    if "login_id" in ssh_key.viewkeys():
                        log_id = ssh_key["login_id"]
                        row = cloudDB.get_row_dict("tblUsers", {"LoginId": log_id})
                        if row is None:
                            continue
                        user_id = row["tblEntities"]
                        rowssh = cloudDB.get_row_dict("tblSSHPublicKeys", {"tblEntities": user_id})
                        if rowssh is None:
                            continue
                        keyname = rowssh["name"]
                        key = rowssh["public_key"]
                        ssh_ent = {
                            "name": keyname,
                            "key": key
                        }
                elif key_type == "new":
                    if "key_name" in ssh_key.viewkeys() and "key" in ssh_key.viewkeys():
                        keyname = ssh_key["key_name"]
                        key = ssh_key["key"]
                        ssh_ent = {
                            "name": keyname,
                            "key": key
                        }
                new_ssh_keys.append(ssh_ent)
            data.update({"ssh_keys": new_ssh_keys})
    return data


def do_ssh_keys_conversion_to_db(options, data):
    if "ssh_keys" in data.viewkeys():
        if isinstance(data["ssh_keys"], list):
            for ssh_key in data["ssh_keys"]:
                if "type" not in ssh_key.viewkeys():
                    continue
                key_type = ssh_key["type"]
                if key_type == "user":
                    if "login_id" in ssh_key.viewkeys():
                        log_id = ssh_key["login_id"]
                        row = cloudDB.get_row_dict("tblUsers", {"LoginId": log_id})
                        if row is None:
                            continue
                        user_id = row["tblEntities"]
                        ssh_ent = {
                            "entities": [
                                {
                                    "attachedentityid": user_id
                                }
                            ],
                            "entitytype": "ssh_user"
                        }
                        if "attached_entities" in options.viewkeys():
                            if isinstance(options["attached_entities"], list):
                                options["attached_entities"].append(ssh_ent)
                        else:
                            options.update({"attached_entities": [ssh_ent]})
                elif key_type == "new":
                    if "key_name" in ssh_key.viewkeys() and "key" in ssh_key.viewkeys():
                        ssh_ent = {
                            "name": ssh_key["key_name"],
                            "public_key": ssh_key["key"]
                        }
                        if "ssh_keys" in options.viewkeys():
                            if isinstance(options["ssh_keys"], list):
                                options["ssh_keys"].append(ssh_ent)
                        else:
                            options.update({"ssh_keys": [ssh_ent]})


def generate_options(obj_type, obj_uuid, data, vdc_details, action="create", child_details=None):  # parent details
    options = {}

    print action
    print obj_type

    try:
        name = data["name"]
    except KeyError:
        print "NO NAME PROVIDED"
        log.critical("ERROR NO NAME PROVIDED")
        return False

    try:
        descr = data["description"]
    except KeyError:
        descr = ""

    service_type = ""
    if obj_type == "switch_network_service":
        service_type = "networkSwitch"
    elif obj_type == "nat_network_service":
        service_type = "nat"
    elif obj_type == "fws_network_service":
        service_type = "firewall"
    elif obj_type == "lbs_network_service":
        service_type = "loadbalancer"
    elif obj_type == "rts_network_service":
        service_type = "router"
    elif obj_type == "ipsecvpn_network_service":
        service_type = "vpn"
    elif obj_type == "nms_network_service":
        service_type = "networkMonitor"
    # elif obj_type == "volumes":
    # elif obj_type == "security-groups":
    # elif obj_type == "security-rules":
    # elif obj_type == "acl-groups":
    # elif obj_type == "acl-rules":
    # elif obj_type == "load-balancer-groups":
    # elif obj_type == "load-balancer-services":
    # elif obj_type == "vpn-groups":
    # elif obj_type == "ipsec-tunnels":
    elif obj_type == "externalnetwork":
        service_type = "externalNetwork"
    elif obj_type == "compute_network_service":
        service_type = "compute"

    if action == "create":
        if len(service_type) > 0:
            options.update({"entitytype": obj_type, "name": name, "description": descr, "servicetype": service_type,
                            "parententityid": vdc_details["id"]})
        else:
            options.update(
                {"name": name, "description": descr, "entitytype": obj_type, "parententityid": vdc_details["id"]})

    # -----------------------------------------------------UPDATE--------------------------------------
    elif action == "update" and child_details is not None:
        for key in data:
            try:
                val = data[key]
                if val is None:
                    continue
                if len(str(val)) > 0:
                    print {key: val}
                    options.update({key: val})
            except KeyError:
                continue

        print "UPDATE OPTIONS FOR OBJ: " + obj_type
        print options

        options.update({
            "entitytype": obj_type,
            "parententityid": vdc_details["id"]
        })

        if len(service_type) > 0:  # network service TODO Maybe some of these take extra information?
            options.update({"servicetype": service_type})
            options.update({
                "id": child_details["id"],
                "name": name,
                "uniqueid": child_details["uniqueid"],
                "throughputsArray": [
                    {
                        "name": "100",
                        "id": "100"
                    },
                    {
                        "name": "200",
                        "id": "200"
                    },
                    {
                        "name": "500",
                        "id": "500"
                    },
                    {
                        "name": "1000",
                        "id": "1000"
                    },
                    {
                        "name": "2000",
                        "id": "2000"
                    }
                ]
            })

        elif obj_type == "serverfarm":

            if "metadata" in data.viewkeys():
                options.update({"metadata": data["metadata"]})
            do_ssh_keys_conversion_to_db(options, data)
            if "compute_service" in data.viewkeys():
                attached_compute_name = data["compute_service"]
                compute_row = get_spec_details_with_parent_id("compute_network_service", attached_compute_name,
                                                              vdc_details["id"])
                if compute_row is not None:
                    options.update({
                        "attach_to": [
                            compute_row["id"]
                        ]
                    })
            if "dynamic_option" in data.viewkeys():
                options.update({
                    "scale_option": data["dynamic_option"],
                    "min": data["min"],
                    "max": data["max"],
                    "initial": data["initial"]
                })
                policies = ["bandwidth", "ram", "cpu"]
                for one in policies:
                    if one in data["dynamic_option"].viewkeys():
                        options.update({
                            str(one) + "_red": data["dynamic_option"][one][0],
                            str(one) + "_green": data["dynamic_option"][one][1]
                        })
        elif obj_type == "server":
            try:
                libname = data["server_boot"]["boot_image"]["library_name"]
            except KeyError:
                libname = ""
            try:
                imgname = data["server_boot"]["boot_image"]["image_name"]
            except KeyError:
                imgname = ""
            libraryrow = cloudDB.get_row_dict("tblEntities", {"EntityType": "imagelibrary", "Name": libname})
            imagerow = get_spec_details_with_parent_id("image", imgname, libraryrow["id"])

            try:
                options.update({"cpuvcpu": data["cpu"][0]})
            except KeyError:
                pass
            try:
                options.update({"cpumhz": data["cpu"][1]})
            except KeyError:
                pass

            attached_entities = []
            if "server_boot" in data.viewkeys():
                if "boot_image" in data["server_boot"].viewkeys():
                    attached_entities.append({
                        "entitytype": "image",
                        "entities": [
                            {
                                "attachedentityid": imagerow["id"]
                            }
                        ]
                    })
                if "boot_volume" in data["server_boot"].viewkeys():
                    if "volume_name" in data["server_boot"]["boot_volume"].viewkeys():
                        boot_volume_row = get_spec_details_with_parent_id("volume", data["server_boot"]["boot_volume"][
                            "volume_name"], vdc_details["id"])
                        attached_entities.append({
                            "entitytype": "volume",  # TODO was volume_boot before
                            "entities": [
                                {
                                    "attachedentityid": boot_volume_row["id"]
                                }
                            ]
                        })
            if "volumes" in data.viewkeys() and isinstance(data["volumes"], list):
                for vol in data["volumes"]:
                    volume_row = get_spec_details_with_parent_id("volume", vol["volume_name"], vdc_details["id"])
                    attached_entities.append({
                        "entitytype": "volume",
                        "entities": [
                            {
                                "attachedentityid": volume_row["id"]
                            }
                        ]
                    })
            if "metadata" in data.viewkeys():
                options.update({"metadata": data["metadata"]})
            if "nat" in data.viewkeys() and isinstance(data["nat"], list):
                for nat in data["nat"]:
                    nat_row = get_spec_details_with_parent_id("nat_network_service", nat["volume_name"],
                                                              vdc_details["id"])
                    attached_entities.append({
                        "entitytype": "nat_network_service",
                        "entities": [
                            {
                                "attachedentityid": nat_row["id"]
                            }
                        ]
                    })
            options.update({"attached_entities": attached_entities})

        elif obj_type == "container":
            if "storage_class" in data.viewkeys():
                storage_class_name = data["storage_class"]
                db_row = get_spec_details_with_parent_id(ent_type=obj_type, name=storage_class_name,
                                                         parent_id=vdc_details["id"])
                if data["datareduction"] == "None":
                    contype = "Regular"
                else:
                    contype = data["datareduction"]
                options.update({
                    "tblstorageclassesid": db_row["id"],
                    "minimumiops": data["iops"],
                    "containerType": contype
                })

        elif obj_type == "volume":
            if "volume_type" in data.viewkeys():
                options.update({"voltype": data["volume_type"]})
            if "snapshot_params" in data.viewkeys():
                options.update({
                    "SnPolicyLimit": data["snapshot_params"]["policy_limit"],
                    "SnapshotsPolicy": data["snapshot_params"]["snapshot_policy"],
                    "schsnptype": data["snapshot_params"]["policy_type"],
                })
                if "policy_hours" in data["snapshot_params"].viewkeys():
                    hour_string = ""
                    if isinstance(data["snapshot_params"]["policy_hours"], list):
                        for hour in data["snapshot_params"]["policy_hours"]:
                            hour_string += str(hour)
                            hour_string += ","
                        hour_string = hour_string[:-1]
                        options.update({"schsnphours": hour_string})
                        options.update({"SnPolicyHrs": hour_string})
            if "backup_params" in data.viewkeys():
                params = data["backup_params"]
                options.update({
                    "BkPolicyLimit": params["policy_limit"],
                    "schbkuplimit": params["policy_limit"],
                    "BackupPolicy": params["backup_policy"],
                    "schbkuptype": params["policy_type"],
                    "BkPolicyTime": params["policy_time"],
                    "schbkuptime": params["policy_time"],
                })
                if "policy_monthdays" in params.viewkeys():
                    if isinstance(params["policy_monthdays"], list):
                        if "policy_weekdays" in params.viewkeys():
                            if isinstance(params["policy_weekdays"], list):
                                num_monthdays = len(params["policy_monthdays"])
                                num_weekdays = len(params["policy_weekdays"])
                                if num_monthdays == 0:
                                    if num_weekdays > 0:
                                        options.update({
                                            "schbkupon": "weekday"
                                        })
                                        weekday_string = ""
                                        for weekday in params["policy_weekdays"]:
                                            weekday_string += str(weekday)
                                            weekday_string += ","
                                        weekday_string = weekday_string[:-1]
                                        options.update({
                                            "schbkupdet": weekday_string,
                                            "BkPolicyWeekDays": weekday_string
                                        })
                                elif num_weekdays == 0:
                                    if num_monthdays > 0:
                                        options.update({
                                            "schbkupon": "date"
                                        })
                                        monthday_string = ""
                                        for monthday in params["policy_monthdays"]:
                                            monthday_string += str(monthday)
                                            monthday_string += ","
                                        monthday_string = monthday_string[:-1]
                                        options.update({
                                            "schbkupdet": monthday_string,
                                            "BkPolicyMonthDays": monthday_string
                                        })

        # elif obj_type == "security_group":
        # elif obj_type == "security_rule":
        # elif obj_type == "acl_group":
        # elif obj_type == "acl_rule":
        # elif obj_type == "lbs-group":
        # elif obj_type == "lbs_service":
        # elif obj_type == "vpn_group":
        # elif obj_type == "ipsecvpn_network_service":
        elif obj_type == "vdc":
            do_ssh_keys_conversion_to_db(options, data)
            if "metadata" in data.viewkeys():
                options.update({"metadata": data["metadata"]})
                #     "HighAvailabilityOptionPolicy": "VDC overrides device", #TODO are these the same key names?
                #     "SlicePreferencePolicy": "VDC overrides device",
                #     "VDCPerformancePolicy": "Best Effort",
                #     "HighAvailabilityOptions": "Default",
        elif obj_type == "externalnetwork":
            options.update({"servicetype": "externalNetwork",
                            "entitytype": obj_type, })
        elif obj_type == "compute_network_service":
            server_farm_row = get_spec_details_with_parent_id("serverfarm", data["serverfarm"][0], vdc_details["id"])

            try:
                max_inst_count = data["params"]["max_instances_count"]
            except KeyError:
                max_inst_count = ""
            try:
                beg_inst_count = data["params"]["begininstancescount"]
            except KeyError:
                beg_inst_count = ""
            try:
                seq_num = data["sequence_number"]
            except KeyError:
                seq_num = ""
            try:
                thruput = data["params"]["throughput"] #TODO throughput vs throughputinc
            except KeyError:
                thruput = ""
            try:
                qos = data["params"]["qos"]
            except KeyError:
                qos = ""
            try:
                nbound_port = data["params"]["northbound"]
            except KeyError:
                nbound_port = ""

            options.update({
                "id": child_details["id"],
                "vdc_status": "Ready",
                "maxinstancescount": max_inst_count,
                "begininstancescount": beg_inst_count,
                "throughput": thruput,
                "servicetype": "compute",
                "sortsequenceid": seq_num,
                "entitystatus": "Ready",
                "entitytype": "compute",
                "parententityid": vdc_details["id"],
                "qos": qos,
                "throughputsArray": [
                    {
                        "name": "",
                        "id": ""
                    }
                ],
                "lbs_mode": "Layer 4",
                "northbound_port": nbound_port,
                "attached_entities": [
                    {
                        "entitytype": "serverfarm",
                        "entities": [
                            {
                                "attachedentityid": server_farm_row["id"]
                            }
                        ]
                    }
                ]
            })
            # elif obj_type == "vdcs" or obj_type == "departments":
    print "OPTIONS: " + str(options)
    return options


def create_entity(ent_type, parent_uuid, parent_vdc_details, formatted_post_data, r, s_row):
    options = generate_options(ent_type, parent_uuid, formatted_post_data, parent_vdc_details, "create")
    ent = EntityFunctions(db=cloudDB, dbid=0, slice_row=s_row, quick_provision=True)
    entity_res = ent._create(cloudDB, options)
    row = get_spec_details_with_entid(ent.dbid)
    ent.update_all_service_uris(cloudDB, r, slice_url=UA)
    update_entity(ent_type, parent_uuid, parent_vdc_details, formatted_post_data, s_row)

    if "interfaces" in formatted_post_data:
        create_interfaces(formatted_post_data["name"], formatted_post_data["interfaces"], parent_vdc_details["id"])
    entity_res = json.loads(entity_res)
    entity_res.update({"UUID": row["UniqueId"]})
    return json.dumps(entity_res)


def get_entity(details):
    # print details
    # print obj_type
    # print obj_uuid
    """

    :param details:
    :return: Returns details with lowercase keys
    """
    slice_row = cloudDB.get_row_dict("tblSlices", {"tblEntities": 28})  # TODO is slice id hardcoded?
    slice_row_lower = utils.cloud_utils.lower_key(slice_row)
    ent = EntityFunctions(db=cloudDB, dbid=details["id"], slice_row=slice_row_lower, quick_provision=True)
    ent._status(cloudDB, do_get=True)
    # return format_details(ent.row)
    return ent.row

def get_entity_from_id(_dbid):
    # print details
    # print obj_type
    # print obj_uuid
    """

    :param details:
    :return: Returns details with lowercase keys
    """
    slice_row = cloudDB.get_row_dict("tblSlices", {"tblEntities": 28})  # TODO is slice id hardcoded?
    slice_row_lower = utils.cloud_utils.lower_key(slice_row)
    ent = EntityFunctions(db=cloudDB, dbid=_dbid, slice_row=slice_row_lower, quick_provision=True)
    ent._status(cloudDB, do_get=True)
    # return format_details(ent.row)
    return ent.row


def update_entity(ent_type, parent_uuid, parent_vdc_details, formatted_post_data, s_row):
    # print ent_type
    # print parent_uuid
    # print parent_vdc_details
    # print formatted_post_data
    # print s_row
    # print generate_options(ent_type, parent_uuid, formatted_post_data, parent_vdc_details, "create")
    # print get_spec_details_with_parent_id(ent_type, formatted_post_data["name"], parent_vdc_details["id"])
    # print formatted_post_data["name"]
    # print parent_vdc_details["id"]

    ent = EntityFunctions(db=cloudDB, dbid=
    get_spec_details_with_parent_id(ent_type, formatted_post_data["name"], parent_vdc_details["id"])["id"],
                          slice_row=s_row, quick_provision=True)
    ent._status(cloudDB, generate_options(ent_type, parent_uuid, formatted_post_data, parent_vdc_details, "create"),
                do_get=True)
    # print "ENTITY ROW: " + str(ent.row)
    if ent.row is None:
        log.critical("ERROR ENTITY ROW NONE " + str(ent.row))
    options = generate_options(ent_type, parent_uuid, formatted_post_data, parent_vdc_details, "update",
                               child_details=ent.row)
    res = ent._update(cloudDB, options)
    entity.entity_commands.update_multiple(cloudDB, ent.row["id"], options)
    return json.loads(res)


def delete_entity(details, slice_row_lower):
    updated_row = get_entity(details)
    if updated_row["entitystatus"] != "Ready":
        return {"Error": "Cannot delete entity that is not ready"}
    children = load_all_owned(updated_row["id"])
    if len(children) > 0:
        return {"Error": "Cannot delete entity that has children"}
    options = {"parententityid": updated_row["id"]}
    options.update({"entitytype": updated_row["entitytype"]})
    entity = EntityFunctions(db=cloudDB, dbid=updated_row["id"], slice_row=slice_row_lower, quick_provision=True)
    entity_res = entity.do(cloudDB, "delete", options)
    return json.loads(entity_res)


def convert_obj_cont_name(obj_type):
    if obj_type == "subnets":
        obj_cont_name = "Subnet"
    elif obj_type == "nats":
        obj_cont_name = "Nat"
    elif obj_type == "external-networks":  # TODO ?!?!?!?!! does this mean to say external-network-service
        obj_cont_name = "ExternalNetwork"
    elif obj_type == "firewalls":
        obj_cont_name = "Firewall"
    elif obj_type == "load-balancers":
        obj_cont_name = "LoadBalancer"
    elif obj_type == "routers":
        obj_cont_name = "Router"
    elif obj_type == "vpns":
        obj_cont_name = "VPN"
    elif obj_type == "monitors":
        obj_cont_name = "Monitor"
    elif obj_type == "server-farms":
        obj_cont_name = "ServerFarm"
    elif obj_type == "servers":
        obj_cont_name = "Server"
    elif obj_type == "containers":
        obj_cont_name = "Container"
    elif obj_type == "volumes":
        obj_cont_name = "Volume"
    elif obj_type == "security-groups":
        obj_cont_name = "SecurityGroup"
    elif obj_type == "security-rules":
        obj_cont_name = "SecurityRule"
    elif obj_type == "acl-groups":
        obj_cont_name = "AccessGroup"
    elif obj_type == "acl-rules":
        obj_cont_name = "AccessRule"
    elif obj_type == "load-balancer-groups":
        obj_cont_name = "LbsGroup"
    elif obj_type == "load-balancer-services":
        obj_cont_name = "LbsService"
    elif obj_type == "vpn-groups":
        obj_cont_name = "VpnGroup"
    elif obj_type == "ipsec-tunnels":
        obj_cont_name = "VpnConnection"
    elif obj_type == "external-network-services":
        obj_cont_name = "ExternalNetwork"
    elif obj_type == "compute-services":
        obj_cont_name = "ComputeService"
    elif obj_type == "virtual-networks":
        obj_cont_name = "VirtualNetwork"
    elif obj_type == "vdcs" or obj_type == "departments":
        obj_cont_name = "Vdc"
    else:
        return "ERROR: Invalid entity type desired: " + obj_type
    return obj_cont_name


def convert_obj_type_to_db(obj_type):
    if obj_type == "subnets":
        obj_type = "switch_network_service"
    elif obj_type == "nats":
        obj_type = "nat_network_service"
    elif obj_type == "external-networks":  # TODO ?!?!?!?!! does this mean to say external-network-service
        obj_type = "slice_attached_network"
    elif obj_type == "firewalls":
        obj_type = "fws_network_service"
    elif obj_type == "load-balancers":
        obj_type = "lbs_network_service"
    elif obj_type == "routers":
        obj_type = "rts_network_service"
    elif obj_type == "vpns":
        obj_type = "ipsecvpn_network_service"
    elif obj_type == "monitors":
        obj_type = "nms_network_service"
    elif obj_type == "server-farms":
        obj_type = "serverfarm"
    elif obj_type == "servers":
        obj_type = "server"
    elif obj_type == "containers":
        obj_type = "container"
    elif obj_type == "volumes":
        obj_type = "volume"
    elif obj_type == "security-groups":
        obj_type = "security_group"
    elif obj_type == "security-rules":
        obj_type = "security_rule"
    elif obj_type == "acl-groups":
        obj_type = "acl_group"
    elif obj_type == "acl-rules":
        obj_type = "acl_rule"
    elif obj_type == "load-balancer-groups":
        obj_type = "lbs-group"
    elif obj_type == "load-balancer-services":
        obj_type = "lbs_service"
    elif obj_type == "vpn-groups":
        obj_type = "vpn_group"
    elif obj_type == "ipsec-tunnels":
        obj_type = "ipsecvpn_network_service"
    elif obj_type == "external-network-services":
        obj_type = "externalnetwork"  # LOL Confusing
    elif obj_type == "compute-services":
        obj_type = "compute_network_service"  # LOL Confusing
    elif obj_type == "virtual-networks":
        obj_type = "virtual_network"
    elif obj_type == "vdcs" or obj_type == "departments":
        obj_type = "vdc"
    else:
        return "ERROR: Invalid entity type desired"
    return obj_type


# TODO RES_CODE EVERYWHERE!!!!!

def perform_action(reqm, details, obj_uuid, obj_type, user_data, post_data):
    global RES_CODE

    print "PERFORMING ACTION: " + reqm + " " + obj_uuid + " " + obj_type
    if reqm == "POST" or reqm == "PUT":
        # details are the details of parents since we are creating a child
        # create entry in local database
        # post request to cfd

        print str(post_data)
        try:
            data = json.loads(str(post_data))
            data = dict_keys_to_lower(data)
            if len(data) == 0:
                return False
            data["name"]
        except:
            print sys.exc_info()
            print "ENTITY NAME NOT PROVIDED"
            return "ERROR: Entity name was not provided"

    if reqm == "POST" or reqm == "PUT" or reqm == "GET" or reqm == "DELETE":
        obj_cont_name = convert_obj_cont_name(obj_type)
        obj_type = convert_obj_type_to_db(obj_type)

        slice_row = cloudDB.get_row_dict("tblSlices", {"tblEntities": 28})  # TODO is slice id hardcoded?
        slice_row_lower = utils.cloud_utils.lower_key(slice_row)
        headers = {"Content-Type": "clouds.net." + obj_cont_name + "+json"}
        spec_uri = load_spec_uri(bottom_child_details=details)
        entity_res = ""
        print headers
        print spec_uri

        child_table = ent_man.entities[obj_type].child_table
        columns = cloudDB.execute_db("SHOW COLUMNS FROM %s" % child_table)

        if reqm == "POST" or reqm == "PUT":
            for field in columns:
                try:
                    # print
                    data[str(field["Field"]).lower()]
                except:
                    data.update({str(field["Field"]).lower(): None})

            try:
                # print
                data[str("description").lower()]
            except:
                data.update({str("description").lower(): None})

            try:
                dictio = data["params"]
                data.update(dictio)
            except KeyError:
                pass
            try:
                dictio = data["autoscale"]
                data.update(dictio)
            except KeyError:
                pass
            try:
                dictio = data["policy"]
                data.update(dictio)
            except KeyError:
                pass
            print data

        if reqm == "POST":
            print UA + spec_uri
            print data
            r = rest.post_rest(UA + spec_uri, convert_post_data_to_cfd(data), headers)
            if r["http_status_code"] == 200 or r["http_status_code"] == 201 or r["http_status_code"] == 202:
                entity_res = json.loads(create_entity(obj_type, obj_uuid, details, data, r, slice_row_lower))
                RES_CODE = "201 Created"
                created_entity_uuid = entity_res["UUID"]
                row = load_ent_details(created_entity_uuid)
                res = format_details(get_entity_from_id(row["id"]))
                print "RETURNING POST"
                print res
                return res
                # ent = EntityFunctions(db=cloudDB, dbid=0)
                # ent.update_all_service_uris(cloudDB, r, slice_url=UA)
        elif reqm == "PUT":
            # TODO you cannot do this on active things
            r = rest.put_rest(UA + spec_uri, convert_post_data_to_cfd(data), headers)
            if r["http_status_code"] == 200 or r["http_status_code"] == 201 or r["http_status_code"] == 202:
                VDC = get_parent_details(details["id"])
                entity_res = update_entity(obj_type, VDC["UniqueId"], VDC, data, slice_row_lower)
                RES_CODE = "202 Accepted"
                return format_details(get_entity(details))
        elif reqm == "GET":
            RES_CODE = "200 OK"
            return format_details(get_entity(details))
        elif reqm == "DELETE":
            RES_CODE = "202 Accepted"
            return delete_entity(details, slice_row_lower)
        # try:
        #     created_entity_uri = r["uri"]
        # except:
        #     # print sys.exc_info()
        #     if reqm != "DELETE" and obj_type != "network_interface":
        #         return "ERROR: Incorrect/Empty CFD Response: " + str(r)

        # print entity_res
        # comp_res = {"CFD": r, "HAWK-DB": json.loads(entity_res)}
        # return comp_res
        # return "CFD RESPONSE:\n" + json.dumps(r, sort_keys=True, indent=4, separators=(',', ': ')) + "\nHAWK-DB RESPONSE:\n" + str(entity_res)

    return False


def validate(ent_uuid, acls):
    row = get_spec_details(ent_uuid, acls)
    row = dict_keys_to_lower(row)
    command_options = {"command": "validate"}
    hawk_validation = api_actions.validate_vdc(cloudDB, row["id"], command_options, row)
    vdc_uri = load_spec_uri(get_spec_details(ent_uuid, acls))
    r = rest.put_rest(UA + vdc_uri, {"command": "reserve-resources"})
    get_entity(row)
    # r2 = rest.get_rest(UA + vdc_uri)
    print r
    if "resources" in r.viewkeys():
        hawk_validation.update({"resources": r["resources"]})
    else:
        hawk_validation.update({"resource_state": r["resource_state"]["state"]})
    return hawk_validation


def reserve_resources(ent_uuid, acls, return_object):
    row = get_spec_details(ent_uuid, acls)
    row = dict_keys_to_lower(row)
    if row["entitytype"] != "vdc":
        return {"Error": "Invalid entity type: " + str(row["entitytype"])}
    command_options = {"command": "reserve-resources"}
    return api_actions.reserve_resources(cloudDB, row["id"], command_options, row, return_obj=return_object)


def provision(ent_uuid, acls, return_obj):
    # TODO do we need to check status of entity we are trying to provision?
    row = get_spec_details(ent_uuid, acls)
    row = dict_keys_to_lower(row)
    if row["entitytype"] == "serverfarm":
        attach_row = cloudDB.execute_db(
            "SELECT * FROM tblAttachedEntities WHERE tblEntities='%s' or tblAttachedEntities.AttachedEntityId='%s'" % (
            row["id"], row["id"]))
        if attach_row is None:
            return {"Error": "Attempt to provision serverfarm that has no attached compute service."}
    elif row["entitytype"] == "server":
        server_farm_details = cloudDB.get_row_dict("tblServerFarms", {"tblEntities": row["parententityid"]})
        server_farm_ent = cloudDB.get_row_dict("tblEntities", {"id": row["parententityid"]})
        if server_farm_details["Scale_Option"] == "Enabled":
            return {"Error": "Attempt to provision server whose serverfarm has Auto Scale Enabled"}
        if server_farm_ent["EntityStatus"] != "Active":
            return {"Error": "Attempt to provision server whose serverfarm is not active"}
    elif row["entitytype"] == "volume":
        container_ent = cloudDB.get_row_dict("tblEntities", {"id": row["parententityid"]})
        if container_ent["EntityStatus"] != "Active":
            return {"Error": "Attempt to provision volume whose container is not active"}

    command_options = {"command": "provision"}
    # api_actions.prov2(cloudDB, row["id"], command_options, row)
    return api_actions.provision(cloudDB, row["id"], command_options, row, return_obj)


def activate(ent_uuid, acls, return_object):
    row = get_spec_details(ent_uuid, acls)
    row = dict_keys_to_lower(row)
    if row["entitytype"] != "vdc":
        return {"Error": "Invalid entity type: " + str(row["entitytype"])}
    command_options = {"command": "activate"}

    return api_actions.activate(cloudDB, row["id"], command_options, return_object)


def deprovision(ent_uuid, acls):  # TODO not async?!?
    row = get_spec_details(ent_uuid, acls)
    row = dict_keys_to_lower(row)
    if row["entitytype"] == "serverfarm":
        servers = load_owned(row["id"], "server")
        any_active = False
        for server in servers:
            if server["EntityStatus"] != "Ready":
                any_active = True
                break
        if any_active:
            return {"Error": "Cannot deprovision serverfarm that has active servers"}
    elif row["entitytype"] == "server":
        server_farm_details = cloudDB.get_row_dict("tblServerFarms", {"tblEntities": row["parententityid"]})
        if server_farm_details["Scale_Option"] == "Enabled":
            return {"Error": "Cannot deprovision server whose serverfarm has Auto Scale Enabled"}
    elif row["entitytype"] == "container":
        volumes = load_owned(row["id"], "volume")
        any_active = False
        for vol in volumes:
            if vol["EntityStatus"] != "Ready":
                any_active = True
                break
        if any_active:
            return {"Error": "Cannot deprovision container that has active volumes"}

    command_options = {"command": "deprovision"}
    return api_actions.deprovision(cloudDB, row["id"], command_options)


def destroy(ent_uuid, acls):
    vdc = get_spec_details(ent_uuid, acls)
    if vdc is None:
        return
    if vdc["EntityType"] != "vdc":
        return {"Error": "Invalid entity type: " + str(vdc["entitytype"])}
    children_of_vdc = cloudDB.get_multiple_row("tblEntities", "deleted=0 AND ParentEntityId='%s'" % vdc["id"])
    print "VDC CHILDREN: " + str(children_of_vdc)
    for child in children_of_vdc:
        if child["EntityType"] != "container":
            if child["EntityType"] != "volume":  # TODO do we need to update entstat
                e = EntityFunctions(cloudDB, child["id"], quick_provision=True)
                e._delete(cloudDB)
    return deprovision(ent_uuid, acls)
    # not active volumes or containers


def special_action(ent_type, split, reqm, acls, userData, post_data):
    print "RUNNING_ACTION: " + str(post_data) + " " + str(split) + " " + reqm
    ent_uuid = split[1]
    if reqm == "PUT":
        obj_type = convert_obj_type_to_db(ent_type)
        try:
            data = json.loads(str(post_data))
            data = dict_keys_to_lower(data)
            if len(data) == 0:
                return False
        except:
            print sys.exc_info()
            return "ERROR: Failed to parse post data in action request"
        command = data.popitem()[0]
        if command == "validate":
            validation = validate(ent_uuid, acls)
            if "resources" in validation.viewkeys():
                return {command: validation["status"], "validation": validation["resources"]}
            elif "resource_state" in validation.viewkeys():
                return {command: validation["status"], "validation": validation["resource_state"]}
        elif command == "reserve-resources":
            validation = validate(ent_uuid, acls)
            result = reserve_resources(ent_uuid, acls, validation["return_object"])
            return {command: result}
        elif command == "provision":
            validation = validate(ent_uuid, acls)
            result = provision(ent_uuid, acls, validation["return_object"])
            return {command: result}
        elif command == "activate":  # TODO check conditions
            validation = validate(ent_uuid, acls)
            result = activate(ent_uuid, acls, validation["return_object"])
            return {command: result}
        elif command == "deprovision":  # TODO check conditions
            res = deprovision(ent_uuid, acls)
            return {command: res}
        elif command == "destroy":  # TODO check conditions
            res = destroy(ent_uuid, acls)
            return {command: res}
    return False


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
    details = get_spec_details(obj_uuid, acls, True)
    if not details:
        return "ERROR: Parent details not found"
    # print details
    return perform_action(reqm, details, obj_uuid, obj_type, user_data, post_data)  # assume authenticated


def get_dict_details(details):
    dicto = {}
    # if details["EntityType"] == "organization" or details["EntityType"] == "department":
    row = cloudDB.get_row_dict(ent_man.entities[details["EntityType"]].child_table,
                               {"tblEntities": details["id"]})
    print row
    dicto.update(row)
    try:
        dicto.pop("HawkResyncTime")
    except:
        sys.exc_info()

    dicto.update({"Name": details["Name"], "Description": details["Description"]})
    return {details["EntityType"]: dicto}

def add_vdc_elements(things, vdc_id, ent_type):
    for thing in things:
        if "name" in thing.viewkeys():
            row = get_spec_details_with_parent_id(None, thing["name"], vdc_id)
            thing.update({"uuid": row["UniqueId"]})
    return add_elements(things, ent_type)

def add_elements(things, ent_type):
    dicto = {"elements": []}
    if things is None:
        return dicto
    # if len(things) == 0:
    #     return dicto
    for thing in things:
        onedic = {}
        # onedic.update(thing)
        # for key, val in thing.iteritems():
        #     if key != "uri":
        #         onedic.update({key: str(val)})
        if "name" in thing.viewkeys():
            onedic.update({"name": thing["name"]})
        elif "Name" in thing.viewkeys():
            onedic.update({"name": thing["Name"]})
        if "uniqueid" in thing.viewkeys():
            onedic.update({"uuid": thing["uniqueid"]})
        elif "UniqueId" in thing.viewkeys():
            onedic.update({"uuid": thing["UniqueId"]})
        elif "uuid" in thing.viewkeys():
            onedic.update({"uuid": thing["uuid"]})
        #TODO add type
        if len(onedic) > 0:
            dicto["elements"].append(onedic)

    if len(things) > 0:
        dicto.update({"type": ent_type})
    dicto.update({"total": len(things)})
    return dicto


def add_interfaces(things, addresses=None):
    dicto = {"elements": []}
    if things is None:
        return dicto
    if len(things) == 0:
        return dicto
    for thing in things:
        addrs = {}
        onedic = {}
        int_name = thing["name"]

        if addresses is not None:
            for address in addresses:
                net_name = address["network"]  # TODO is network name the right thing here
                if net_name == int_name:
                    addrs.update(address)
                    break
            onedic.update({
                "addresses": addrs
            })
        onedic.update(thing)
        if "uri" in onedic.viewkeys():
            onedic.pop("uri")

        dicto["elements"].append(onedic)
    dicto.update({
        "type": "interface",
        "total": len(things)
    })
    return dicto


def load_details_from_cfd(details):
    spec_uri = load_spec_uri(details)
    r = rest.get_rest(UA + spec_uri)
    if r["http_status_code"] != 200:
        print "FAILED GET " + str(r["http_status_code"])
        return {"Error": "Entity not found in CFD", "successful": False}
        # for item in details.iteritems():
        #     dicto.update({str(item[0]): str(item[1])}) #TODO this is not good, can we look up details from db?
    else:
        d = {"successful": True}
        d.update(r)
        return d


def do_interface_addition(dicto, r):
    if "interfaces" in r.viewkeys():
        interfaces = r["interfaces"]
        if "addresses" in r.viewkeys():
            addresses = r["addresses"]
        else:
            addresses = None
        ints = add_interfaces(interfaces, addresses)
        dicto.update({"interfaces": ints})


def format_details(details):
    print "FORMATTING DETAILS"
    print details
    details = dict_keys_to_lower(details)  # TODO values str()
    dicto = {}
    dicto.update({
        "name": details["name"],
        "type": details["entitytype"],
        "description": details["description"],
        "uuid": details["uniqueid"]
    })
    if "entitystatus" in details.viewkeys():
        dicto.update({
            "resource_state": {
                "state": details["entitystatus"]
            },
        })
    r = load_details_from_cfd(details)
    print "RES: " + str(r)
    if not r["successful"]:
        return {"Error": "Entity not found in the CFD"}
        # cloudDB.update_db("UPDATE tblEntities SET EntityStatus='Ready' WHERE id='%s'" % details["id"])
        # for item in dict_keys_to_lower(get_entity(details["entitytype"], details["uniqueid"], details)).iteritems():
        #         dicto.update({str(item[0]): str(item[1])})
        # return dicto
    # dicto.update({"Name": details["name"], "Description": details["description"]})
    # return {details["entitytype"]: dicto}
    do_interface_addition(dicto, r)

    if details["entitytype"] == "organization":
        depts = add_elements(load_owned(details["id"], "department"), "department")
        imglibs = add_elements(load_owned(details["id"], "imagelibrary"), "imagelibrary")
        virnets = add_elements(load_owned(details["id"], "virtual_network"), "virtual_network")

        dicto.update({
            "location": details["location"],
            "administrator-name": details["administrator"],
            "email-address": details["email"],
            "policies": {
                "enable-flavors": details["flavors_enabled"],
                "enable-multi-slice-vdcs": "???"
            },
            "created": str(details["created_at"]),
            "resource_state": {
                "state": details["entitystatus"]
            },
            "departments": depts,
            "image-libraries": imglibs,
            "virtual-networks": virnets
        })
    elif details["entitytype"] == "department":
        vdcs = add_elements(load_owned(details["id"], "vdc"), "vdc")
        imglibs = add_elements(load_owned(details["id"], "imagelibrary"), "imagelibrary")
        virnets = add_elements(load_owned(details["id"], "virtual_network"), "virtual_network")
        dicto.update({
            "location": details["location"],
            "administrator-name": details["administrator"],
            "email-address": details["email"],
            "created": str(details["created_at"]),
            "resource_state": {
                "state": details["entitystatus"]
            },
            "vdcs": vdcs,
            "image-libraries": imglibs,
            "virtual-networks": virnets
        })
    elif details["entitytype"] == "nat_network_service":
        # TODO when deprovisioned, nat dissapears from cfd
        # dicto.update(r)
        if "cfm" in r.viewkeys():
            dicto.update({"cfm": r["cfm"]})
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
            if "external_address_type" in r["params"].viewkeys():
                dicto.update({"nat_address_type": r["params"]["external_address_type"]})
                if r["params"]["external_address_type"] == "static":
                    dicto.update({"nat_static_address": r["params"]["external_address"]})
        dicto.update({
            "pat_mode": details["nat_pat_mode"]
        })
    elif details["entitytype"] == "externalnetwork":
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "cfm" in r.viewkeys():
            dicto.update({"cfm": r["cfm"]})
    elif details["entitytype"] == "fws_network_service":
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "autoscale" in r.viewkeys():
            dicto.update({"autoscale": r["autoscale"]})
        if "cfm" in r.viewkeys():
            dicto.update({"cfm": r["cfm"]})
        if "service_status" in r.viewkeys() and "params" in r.viewkeys():
            inst_count = r["service_status"]["current_instances_count"]
            max_inst_count = r["params"]["max_instances_count"]
            thruput = r["params"]["throughput"]
            dicto.update({"deployed": inst_count * thruput})
            dicto.update({"provisioned": max_inst_count * thruput})
    elif details["entitytype"] == "lbs_network_service":
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "autoscale" in r.viewkeys():
            dicto.update({"autoscale": r["autoscale"]})
        if "lbs_mode" in r.viewkeys():
            dicto.update({"lbs_mode": r["lbs_mode"]})
        if "cfm" in r.viewkeys():
            dicto.update({"cfm": r["cfm"]})
        if "service_status" in r.viewkeys() and "params" in r.viewkeys():
            inst_count = r["service_status"]["current_instances_count"]
            max_inst_count = r["params"]["max_instances_count"]
            thruput = r["params"]["throughput"]
            dicto.update({"deployed": inst_count * thruput})
            dicto.update({"provisioned": max_inst_count * thruput})

    elif details["entitytype"] == "rts_network_service":
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "autoscale" in r.viewkeys():
            dicto.update({"autoscale": r["autoscale"]})
        if "service_status" in r.viewkeys() and "params" in r.viewkeys():
            inst_count = r["service_status"]["current_instances_count"]
            max_inst_count = r["params"]["max_instances_count"]
            thruput = r["params"]["throughput"]
            dicto.update({"deployed": inst_count * thruput})
            dicto.update({"provisioned": max_inst_count * thruput})
    elif details["entitytype"] == "ipsecvpn_network_service":
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
    elif details["entitytype"] == "nms_network_service":
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "service_pairs" in r.viewkeys():
            dicto.update({"service_pairs": r["service_pairs"]})
    elif details["entitytype"] == "virtual_network":
        dicto.update(r)  # TODO Is this ok
        if "successful" in dicto.viewkeys():
            dicto.pop("successful")
    elif details["entitytype"] == "compute_network_service":
        # dicto.update(r)
        if "serverfarm" in r.viewkeys():
            farms = add_elements(r["serverfarm"]["elements"], "serverfarm")
            dicto.update({"serverfarms": farms})
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "userdata" in r.viewkeys():
            dicto.update({"userdata": r["userdata"]})
        if "ssh_keys" in r.viewkeys():
            keys = add_elements(r["ssh_keys"], "ssh_key")
            dicto.update({"ssh_keys": keys})
        if "metadata" in r.viewkeys():
            metadatas = add_elements(r["metadata"], "metadata")
            dicto.update({"metadata": metadatas})
    elif details["entitytype"] == "serverfarm":
        if "scale_option" in r.viewkeys():
            dicto.update({
                "scale_option": details["scale_option"],
                "min": details["min"],
                "max": details["max"],
                "initial": details["initial"]
            })
            # policies = ["bandwidth", "ram", "cpu"]
            # for one in policies:
            #     if one in r["dynamic_option"].viewkeys():
            #         dicto.update({
            #             str(one) + "_red": r["dynamic_option"][one][0],
            #             str(one) + "_green": r["dynamic_option"][one][1]
            #         })
            dicto.update({"dynamic-option": r["dynamic_option"]})
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        if "userdata" in r.viewkeys():
            dicto.update({"userdata": r["userdata"]})
        if "ssh_keys" in r.viewkeys():
            keys = add_elements(r["ssh_keys"], "ssh_key")
            dicto.update({"ssh_keys": keys})
        if "metadata" in r.viewkeys():
            metadatas = add_elements(r["metadata"], "metadata")
            dicto.update({"metadata": metadatas})
        dicto.update({
            "compute_service": "???TODO",  # TODO HOW TO GET THIS
            "compute_class": "???TODO"  # TODO HOW TO GET THIS
        })
    elif details["entitytype"] == "server":
        dicto.update({
            "hypervisor": r["hypervisor"],
            "cpu": r["cpu"],
            "memory": r["memory"],
            "boot_storage_type": r["boot_storage_type"],
            "ephemeral_storage": r["ephemeral_storage"],
        })
        if "weight" in r.viewkeys():
            dicto.update({
                "weight": r["weight"]
            })
        if "nat" in r.viewkeys():
            dicto.update({
                "nat": r["nat"]
            })
        if "volumes" in r.viewkeys():
            new_vols = []
            for vol in r["volumes"]:
                # if "hierarchy" in vol.viewkeys():
                #     vol.pop("hierarchy")
                new_vols.append(vol)
            dicto.update({
                "volumes": new_vols
            })
        if "server_boot" in r.viewkeys():
            dicto.update({
                "server_boot": r["server_boot"]
            })

        if "userdata" in r.viewkeys():
            dicto.update({"userdata": r["userdata"]})
        if "ssh_keys" in r.viewkeys():
            keys = add_elements(r["ssh_keys"], "ssh_key")
            dicto.update({"ssh_keys": keys})
        if "metadata" in r.viewkeys():
            metadatas = add_elements(r["metadata"], "metadata")
            dicto.update({"metadata": metadatas})
        if "xvpvnc_url" in r.viewkeys():
            dicto.update({
                "xvpvnc_url": r["xvpvnc_url"]
            })
        if "novnc_url" in r.viewkeys():
            dicto.update({
                "novnc_url": r["novnc_url"]
            })
    elif details["entitytype"] == "container":
        r.pop("successful")
        #dicto.update(r)
    elif details["entitytype"] == "volume":
        if "volume_type" in r.viewkeys():
            dicto.update({"volume_type": r["volume_type"]})
        if "capacity" in r.viewkeys():
            dicto.update({"capacity": r["capacity"]})
        if "snapshot_params" in r.viewkeys():
            dicto.update({"snapshot_params": r["snapshot_params"]})
        if "backup_params" in r.viewkeys():
            dicto.update({"backup_params": r["backup_params"]})
    elif details["entitytype"] == "slice_attached_network":
        print "TODO"
        dicto.update(r)
        #todo
    elif details["entitytype"] == "vdc":
        for key, val in r.iteritems():
            if not isinstance(val, dict) and not isinstance(val, list):
                if "uri" not in str(key):
                    dicto.update({key: val})
        if "storage_uri" in r.viewkeys():
            r2 = rest.get_rest(UA + r["storage_uri"])
            if r2["http_status_code"] == 200:
                if r2["containers"]["total"] > 0:
                    cs = r2["containers"]["elements"]
                    elements = []
                    for cont in cs:
                        elements.append({"name": cont["name"]})
                    r.update({"containers": {"total": len(elements), "elements": elements}})
        if "params" in r.viewkeys():
            dicto.update({"params": r["params"]})
        types = ["subnets", "external_networks", "nats", "firewalls", "loadbalancers", "routers", "ipss", "vpns", "network_monitors", "containers"]
        for t in types:
            if t in r.viewkeys():
                if r[t]["total"] == 0:
                    ents = []
                else:
                    ents = r[t]["elements"]
                conf_ents = add_vdc_elements(ents, details["id"], t[:-1])
                dicto.update({t: conf_ents})
        if "subnets" in r.viewkeys():
            if r["subnets"]["total"] > 0:
                subnets = r["subnets"]["elements"]
                snets = add_elements(subnets, "subnet")
                dicto.update({"subnets": snets})

                # dicto.update(r)
    else:
        for item in details.iteritems():
            dicto.update({str(item[0]): str(item[1])})

    if "http_status_code" in dicto.viewkeys():
        dicto.pop("http_status_code")

    return dicto


def get_uuid(ent_id):
    return cloudDB.get_row_dict("tblEntities", {"id": ent_id})["UniqueId"]


def request_api(addr, userData, reqm, post_data):
    # address is relative url
    # data comes in json format
    # TODO Permission checking in: load_all; load_ent_details; load_owned
    if addr[len(addr) - 1:] == '/':
        addr = addr[:-1]

    user_ent_id = userData["tblEntities"]
    acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (user_ent_id))
    if acls is None:
        return False
    aclID = acls[0]["AclEntityId"]
    aclRole = get_acl_role(aclID)

    print "API REQUEST: " + addr + " " + post_data + " " + str(reqm) + " " + aclRole

    split = addr[1:].split('/')
    specific_action_addresses = ["subnets", "nats", "firewalls", "load-balancers", "routers",
                                 "vpns", "monitors", "compute-services", "server-farms", "servers",
                                 "containers", "volumes", "security-groups", "security-rules",
                                 "acl-groups", "acl-rules", "load-balancer-groups", "load-balancer-services",
                                 "vpn-groups", "ipsec-tunnels", "interfaces", "external-network-services"]
    duplicate_specific_action_addresses = ["external-networks", "virtual-networks", "image-libraries"]
    action_entities = ["vdcs", "nats", "external-networks", "firewalls", "load-balancers", "routers", "vpns",
                       "monitors", "compute-services", "server-farms", "servers", "containers", "volumes"]

    for part in split:
        if part in duplicate_specific_action_addresses and len(split) > 1:
            if split[0] in duplicate_specific_action_addresses or split[1] in duplicate_specific_action_addresses:
                #if reqm != "GET" and len(split) < 3:
                if reqm != "GET" and len(split) < 3:
                    return special_process(part, split, reqm, acls, userData, post_data)
        if part in specific_action_addresses and len(split) < 3:
            return special_process(part, split, reqm, acls, userData, post_data)
        if "vdcs" in part and (reqm == "PUT" or reqm == "DELETE") and len(split) < 3:
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
            elif split[0] in action_entities:
                if len(split[1]) == 36:
                    if split[2] == "actions":
                        return special_action(split[0], split, reqm, acls, userData, post_data)
        elif len(split) == 2:  # PUT OR DELETE ON vdcs/vdc_uuid
            if split[0] == "vdcs":
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
                if object_type == "imagelibrary":
                    data.append(load_system_owned("imagelibrary"))
                else:
                    data.append(load_all(object_type))
                if len(data) > 0:
                    return json_list_objects_arr(addr, data, aclRole)
            else:
                if len(split[1]) == 36:
                    details = load_ent_details(split[1])
                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in convert_obj_type_to_db(split[0]):
                            if not (details["EntityType"] == "externalnetwork" and split[
                                0] == "external-networks"):
                                # makes sure you cant ask dept details and give vdc uuid.
                                print details["EntityType"]
                                print convert_obj_type_to_db(split[0])
                                # TODO Fix this
                                #return False
                        return format_details(get_entity(details))
                        # return get_dict_details(details)

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
                        if details["EntityType"] not in convert_obj_type_to_db(split[0]):
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        return get_entity(details)
                        # return get_dict_details(details)

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
            acls = cloudDB.get_multiple_row("tblEntitiesACL", "deleted=0 AND tblEntities='%s'" % (user_ent_id))
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
                        # if split[0] == "vdcs":
                        #     object_type = "vdc"
                        if split[0] == "external-networks":
                            object_type = "slice_attached_network"
                        elif split[0] == "image-libraries":
                            object_type = "imagelibrary"
                        elif split[0] == "virtual-networks":
                            object_type = "virtual_network"
                        elif split[0] == "departments":
                            object_type = "department"
                            data += [load_ent_details(get_uuid(aclID))]
                            if len(data) > 0:
                                resultantData += data
                                continue
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
                        if details["EntityType"] not in convert_obj_type_to_db(split[0]):
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        return get_entity(details)
                        # return get_dict_details(details)

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
            acls = cloudDB.get_multiple_row("tblEntitiesACL", "deleted=0 AND tblEntities='%s'" % (user_ent_id))
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
                        if details["EntityType"] not in convert_obj_type_to_db(split[0]):
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        return get_entity(details)
                        # return get_dict_details(details)

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
        elif "error" in str(api_response).lower():
            RES_CODE = "408 API Error"

        # dic = {"Token": {"ID" : token, "Status": "Valid", "Expires": (datetime.datetime.now() + datetime.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')}, "API Response": api_response}
        dic = api_response
        return json.dumps(dic, sort_keys=True, indent=4, separators=(',', ': '))

    def token_invalid(self, token):
        return [
            json.dumps({"Token": {"ID": token, "Status": "Invalid"}}, sort_keys=True, indent=4, separators=(',', ': '))]

    def wrong_api_version(self):
        return ['{"Error": "Malformed/Unsupported API Version"}']


def serve(env, start_response):
    log.info("Serving! " + str(env))
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
                # dname = escape(data.get("domain")[0])
            except (TypeError):
                start_response('400 Bad Request', defresponse_header)
                return oman.no_post_data()
            tokenResp = get_token_json_response(user, passw)
            if tokenResp is False:
                start_response('401 Unauthorized', defresponse_header)
                return oman.auth_failed()
            return oman.auth_success(tokenResp)
        elif path == '/' or path == '':
            start_response('200 OK', defresponse_header)
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


utils.cloud_utils.setup_flags_logs('hawk-rpc.log', flagfile='cloudflow_flags.conf', logdir=None, init_logger=True)
wsgi.server(eventlet.listen(('', 8091)), serve)
