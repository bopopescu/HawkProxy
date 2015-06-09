__author__ = 'vkorolik'
# import ujson as json
import json
import logging
import pprint
from urlparse import parse_qs
from cgi import escape
import time
from datetime import datetime, timedelta

import eventlet
from eventlet.green import urllib2
from eventlet import wsgi
import requests

import cryptC as crypt
from utils.cloud_utils import CloudGlobalBase

UA = "192.168.228.23:8231"
AUTH_URL = "http://192.168.228.23:8002/v3"
ENDPOINT_URL = "http://192.168.228.23:8002/v3"

log = logging.getLogger("log")
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)

pp = pprint.PrettyPrinter(indent=4)

cloudDB = CloudGlobalBase(pool=False)


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
        t = time.strftime('%Y-%m-%d %H:%M:%S')
        t_ex = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        cloudDB.update_db("UPDATE tblUsers SET Token = '%s' WHERE tblEntities = '%s'" % (token, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenIssuedAt = '%s' WHERE tblEntities = '%s'" % (t, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenExpiresAt = '%s' WHERE tblEntities = '%s'" % (t_ex, entID))
        cloudDB.update_db("UPDATE tblUsers SET LastActivityDate = '%s' WHERE tblEntities = '%s'" % (t, entID))
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
    if len(rows) > 1:
        log.critical("More than one user with same login token in mysql db.")
    elif len(rows) == 0 or rows is None:
        log.warning("User with given token not found in mysql db.")
        # FAILED TO AUTH
    else:
        now = time.strftime('%Y-%m-%d %H:%M:%S')  # TODO THIS DOES NOT CORRESPOND WITH HAWK TIME IN DB
        entID = str(rows[0]["tblEntities"])
        exp_time = str(rows[0]["TokenExpiresAt"])
        if now > exp_time:
            return False
        n_t_ex = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        cloudDB.update_db("UPDATE tblUsers SET TokenIssuedAt = '%s' WHERE tblEntities = '%s'" % (now, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenExpiresAt = '%s' WHERE tblEntities = '%s'" % (n_t_ex, entID))
        cloudDB.update_db("UPDATE tblUsers SET LastActivityDate = '%s' WHERE tblEntities = '%s'" % (now, entID))
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


def json_list_objects_arr(address, givens, aclRole):
    jStack = {}

    organizations = {}
    libraryimage = {}
    departments = {}
    virtual_networks = {}
    vdcs_complete = {}

    objects = [organizations, libraryimage, departments, virtual_networks, vdcs_complete]

    jStack.update({"uri": address, "user_type": aclRole})
    for one in givens:
        num = len(one)
        oneSpecs = {"type": None, "total": num}  # TODO Type needs to be established
        elements = []
        for thing in one:
            element = {"name": thing["Name"]}

            # details = load_ent_details(thing["UniqueId"])
            # for key, value in details.iteritems():
            #     element.update({str(key): str(value)}) # DUMP ALL DETAILS

            element.update({"uuid": thing["UniqueId"]})
            selfLinkString = thing["EntityType"] + "/" + thing["UniqueId"]
            element.update({"links": {"self": selfLinkString}})
            elements.append(element)
        oneSpecs.update({"elements": elements})
        if len(elements) > 0:
            new = {one[0]["EntityType"]: oneSpecs}
            jStack.update(new)

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


def request_api(addr, data, userData, reqm):
    # address is relative url
    # data comes in json format
    # TODO Permission checking in: load_all; load_ent_details; load_owned
    if addr[len(addr) - 1:] == '/':
        addr = addr[:-1]

    ent_id = userData["tblEntities"]
    acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (ent_id))
    aclID = acls[0]["AclEntityId"]  # TODO INCORRECT ASSUMPTION FOR DSA OR VDCUSER <<<<<<<<<<<<<<CRITICAL
    aclRole = get_acl_role(aclID)

    print "API REQUEST: " + addr + " " + data + " " + str(reqm) + " " + aclRole

    split = addr[1:].split('/')

    if addr == '/listAll' and reqm == "GET":
        stringVal = listAll(acls, addr)
        print stringVal
        return stringVal
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
                    return json.dumps(json_list_objects_arr(addr, data, aclRole), sort_keys=True, indent=4,
                                      separators=(',', ': '))
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
                        return json.dumps(element, sort_keys=True, indent=4, separators=(',', ': '))

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
                        return json.dumps(json_list_objects_arr(addr, data, aclRole), sort_keys=True, indent=4,
                                          separators=(',', ': '))
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
                    return json.dumps(json_list_objects_arr(addr, data, aclRole), sort_keys=True, indent=4,
                                      separators=(',', ': '))
            else:  # maybe redundant with IT just add this to it as well and remove aclRole if separation
                if len(split[1]) == 36:
                    details = load_ent_details(uuid=split[1])
                    if not authorization_object_check_bot_up(details["id"], aclID):
                        # make sure you actually own this
                        log.critical("ATTEMPT TO ACCESS ILLEGAL OBJECT")
                        print "ATTEMPT TO ACCESS ILLEGAL OBJECT"
                        return False

                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in split[0]:
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        element = {}
                        for key, value in details.iteritems():
                            element.update({str(key): str(value)})  # DUMP ALL DETAILS
                        return json.dumps(element, sort_keys=True, indent=4, separators=(',', ': '))

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
                        return json.dumps(json_list_objects_arr(addr, data, aclRole), sort_keys=True, indent=4,
                                          separators=(',', ': '))
        elif aclRole == "department":
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
                data.append(load_owned(aclID, object_type))
                if len(data) > 0:
                    return json.dumps(json_list_objects_arr(addr, data, aclRole), sort_keys=True, indent=4,
                                      separators=(',', ': '))
            else:  # maybe redundant with IT just add this to it as well and remove aclRole if separation
                print "swag"
                if len(split[1]) == 36:
                    details = load_ent_details(uuid=split[1])
                    if not authorization_object_check_bot_up(details["id"], aclID):
                        # make sure you actually own this
                        log.critical("ATTEMPT TO ACCESS ILLEGAL OBJECT")
                        print "ATTEMPT TO ACCESS ILLEGAL OBJECT"
                        return False

                    if len(split) < 3:  # details about one thing like departments/uuid
                        if details["EntityType"] not in split[0]:
                            # makes sure you cant ask dept details and give vdc uuid
                            return False
                        element = {}
                        for key, value in details.iteritems():
                            element.update({str(key): str(value)})  # DUMP ALL DETAILS
                        return json.dumps(element, sort_keys=True, indent=4, separators=(',', ': '))

                    elif len(split) == 3:  # details about nested thing like departments/uuid/vdcs
                        ent_id_parent = details["id"]
                        object_type = split[2][:-1]
                        if object_type == "image-librarie":
                            object_type = "imagelibrary"
                        elif object_type == "virtual-network":
                            object_type = "virtual_network"

                        if object_type == "imagelibrary" and split[0] == "vdcs":
                            data.append(load_all_available(vdc_id=ent_id_parent, enttype=object_type))
                        elif object_type == "virtual_network" and split[0] == "vdcs":
                            data.append(load_all_available_vir_nets(ent_id_parent))  # this is wrong, too simple
                        else:
                            data.append(load_owned(ent_id_parent, object_type))
                        return json.dumps(json_list_objects_arr(addr, data, aclRole), sort_keys=True, indent=4,
                                          separators=(',', ': '))
    return False


def serve(env, start_response):
    path = env['PATH_INFO']
    defresponse_header = [('Content-Type', 'cloudflows.net+json')]

    apiVer = path[:3]  # contains starting / no trailing /
    if apiVer == '/':
        start_response('200 OK', defresponse_header)
        return ["API Info here"]
    elif apiVer == "/v2":
        path = path[3:]  # contains starting / no trailing /
        if path == '/authenticate':
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
                return ["No post data provided"]
            try:
                user = escape(data.get("user")[0])
                passw = escape(data.get("pass")[0])
                dname = escape(data.get("domain")[0])
            except (TypeError):
                start_response('400 Bad Request', defresponse_header)
                return ["Improper post data provided"]
            tokenResp = get_token_json_response(user, dname, passw)
            if tokenResp is False:
                start_response('401 Unauthorized', response_header)
                return ["Authentication failed"]  # TODO Format json
            return [tokenResp]
        elif path == '/':
            start_response('200 OK', defresponse_header)
            return ["API Running on version 2"]
        else:
            try:
                token = env['HTTP_X_AUTH_TOKEN']
            except KeyError:
                start_response('400 Bad Request', defresponse_header)
                return ['No auth-token present\r\n']
            start_response('200 OK', defresponse_header)

            try:
                request_body_size = int(env.get('CONTENT_LENGTH', 0))
            except (ValueError):
                request_body_size = 0
            data = env['wsgi.input'].read(request_body_size)

            userData = validate_token(token)
            if userData is not False:
                apiResponse = str(request_api(path, data, userData, env['REQUEST_METHOD']))  # TODO Use req method
                if apiResponse == "False":
                    start_response('400 Bad Request', defresponse_header)
                    apiResponse = "BAD API REQUEST"
                return ["TOKEN VALID: " + token + "\nAPI RESPONSE:\n" + apiResponse]

            # else cannot auth
            start_response('401 Unauthorized', defresponse_header)
            return ["TOKEN INVALID: " + token]
    else:
        start_response('400 Bad Request', defresponse_header)
        return ["Malformed/Unsupported API Version"]


wsgi.server(eventlet.listen(('', 8091)), serve)
