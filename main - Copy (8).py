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


def get_token_json_response(un, pa):
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
                            "id": "f01928a59aab423dbf7e5c4d9113a340"
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
        now = time.strftime('%Y-%m-%d %H:%M:%S')
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
    # TODO Recursively load all objects that the user has control over
    # Takes a ACLEntityID
    # Looks at all entities with that parent ID
    # For each entity, look at other entities that are children of that entity
    # Don't go deeper than VDC?
    # Maybe load everything and then sort out unnecessary
    if ent_id == 0 or ent_id == 1:
        log.critical("This method should not be used with IT")
        return
    print "ENT ID: " + str(ent_id)
    ents = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s'" % (ent_id))
    # if len(ents) == 1:
    if len(ents) is not 0 and ents is not None:
        for ent in ents:
            # if ent["EntityType"] == "organization" or ent["EntityType"] == "department" or ent["EntityType"] == "imagelibrary" or ent["EntityType"] == "vdc":  # TODO how to use this
            array.append(ent)
            load_owned_objects_rec_nonnest(ent["id"], array)


def load_all_orgs():
    orgs = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("organization"))
    orgsArr = []
    for org in orgs:
        orgsArr.append(org)
        # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
        # for dept in depts:
        #     array.append(dept)
    return orgsArr


def load_all_ilibs():
    libs = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("imagelibrary"))
    libraries = []
    for lib in libs:
        libraries.append(lib)
        # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
        # for dept in depts:
        #     array.append(dept)
    return libraries


def load_system_ilibs():
    # load all ilibs that are children of slice
    slices = cloudDB.get_multiple_row("tblEntities", "EntityType='%s'" % ("slice"))
    libraries = []
    for slice in slices:
        libs = cloudDB.get_multiple_row("tblEntities",
                                        "EntityType='%s' AND ParentEntityId='%s'" % ("imagelibrary", slice["id"]))
        for lib in libs:
            libraries.append(lib)
            # depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
            # for dept in depts:
            #     array.append(dept)
    return libraries


def load_all_depts(orgs_mysql_result):
    deptsArr = []
    for org in orgs_mysql_result:
        depts = cloudDB.get_multiple_row("tblEntities",
                                         "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
        for dept in depts:
            deptsArr.append(dept)
    return deptsArr


def load_owned_libraries(parent_ent_id):
    libArr = []
    libs = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (
        parent_ent_id, "imagelibrary"))  # TODO BROKEN, NEED TO FIND LIB WHERE PARENT IS THE ORGANIZATION
    for lib in libs:
        libArr.append(lib)
    return libArr


def load_owned_departments(parent_ent_id):
    depArr = []
    depts = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (
        parent_ent_id, "department"))  # TODO BROKEN, NEED TO FIND LIB WHERE PARENT IS THE ORGANIZATION
    for dept in depts:
        depArr.append(dept)
    return depArr


def load_owned_virnets(parent_ent_id):
    virnetsArr = []
    virNets = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (
        parent_ent_id, "virtual_network"))  # TODO BROKEN, NEED TO FIND LIB WHERE PARENT IS THE ORGANIZATION
    for virNet in virNets:
        virnetsArr.append(virNet)
    return virnetsArr


def load_owned_vdcs(parent_ent_id):
    vdcsArr = []
    vdcs = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s' AND EntityType='%s'" % (
        parent_ent_id, "vdc"))  # TODO BROKEN, NEED TO FIND LIB WHERE PARENT IS THE ORGANIZATION
    for vdc in vdcs:
        vdcsArr.append(vdc)
    return vdcsArr


def get_acl_role(aclID):
    user = cloudDB.get_row("tblEntitiesACL", "AclEntityId='%s'" % (aclID))
    return user["AclRole"]


# TODO WITH ALL MYSQL SEARCHES, MAKE SURE ROW DELETED == 0; replace get_row with get_row_dict


def json_list_objects(address, orgs, imagelibraries, departm, vir_nets, vdcs,
                      aclRole):  # TODO list only one type of obj
    # TODO Resource state?
    jStack = {}
    organizations = {}
    libraryimage = {}
    departments = {}
    virtual_networks = {}
    vdcs_complete = {}

    jStack.update({"uri": address, "type": aclRole})

    numOrgs = len(orgs)
    numLibs = len(imagelibraries)
    numDepts = len(departm)
    numVirNets = len(vir_nets)
    numVDCS = len(vdcs)

    orgSpecs = {"type": "organization", "total": numOrgs}
    elements = []
    for org in orgs:
        uriInfo = cloudDB.get_row_dict("tblUris", {"tblEntities": (org["id"])})
        element = {"name": org["Name"]}
        element.update({"uuid": org["UniqueId"]})
        element.update({"uri": trim_uri(uriInfo["uri"])})
        elements.append(element)
    orgSpecs.update({"elements": elements})
    if len(elements) > 0:
        organizations = {"organizations": orgSpecs}

    libspecs = {"type": "imagelibrary", "total": numLibs}
    elements = []
    for lib in imagelibraries:
        uriInfo = cloudDB.get_row_dict("tblUris", {"tblEntities": (lib["id"])})
        element = {"name": lib["Name"]}
        element.update({"uuid": lib["UniqueId"]})
        element.update({"uri": trim_uri(uriInfo["uri"])})
        elements.append(element)
    libspecs.update({"elements": elements})
    if len(elements) > 0:
        libraryimage = {"libraryimage": libspecs}

    depspecs = {"type": "department", "total": numDepts}
    elements = []
    for dept in departm:
        uriInfo = cloudDB.get_row_dict("tblUris", {"tblEntities": (dept["id"])})
        element = {"name": dept["Name"]}
        element.update({"uuid": dept["UniqueId"]})
        element.update({"uri": trim_uri(uriInfo["uri"])})
        elements.append(element)
    depspecs.update({"elements": elements})
    if len(elements) > 0:
        departments = {"departments": depspecs}

    vnspecs = {"type": "networks", "total": numVirNets}
    elements = []
    for virnet in vir_nets:
        uriInfo = cloudDB.get_row_dict("tblUris", {"tblEntities": (virnet["id"])})
        element = {"name": virnet["Name"]}
        element.update({"uuid": virnet["UniqueId"]})
        element.update({"uri": trim_uri(uriInfo["uri"])})
        elements.append(element)
    vnspecs.update({"elements": elements})
    if len(elements) > 0:
        virtual_networks = {"virtual_networks": vnspecs}

    vdcspecs = {"type": "vdc", "total": numVDCS}
    elements = []
    for vdc in vdcs:
        uriInfo = cloudDB.get_row_dict("tblUris", {"tblEntities": (vdc["id"])})
        element = {"name": vdc["Name"]}
        element.update({"uuid": vdc["UniqueId"]})
        element.update({"uri": trim_uri(uriInfo["uri"])})
        elements.append(element)
    vdcspecs.update({"elements": elements})
    if len(elements) > 0:
        vdcs_complete = {"vdcs": vdcspecs}

    jStack.update(organizations)
    jStack.update(libraryimage)
    jStack.update(departments)
    jStack.update(virtual_networks)
    jStack.update(vdcs_complete)
    return jStack


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


def request_api(address, data, userData, reqmethod):
    # address is relative url
    # data comes in json format
    ent_id = userData["tblEntities"]
    acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (ent_id))
    print "API REQUEST: " + address + " " + data + " " + str(ent_id)

    if address == '/':
        orgs = []
        imagelibraries = []
        departm = []
        vir_nets = []
        vdcs = []
        for acl in acls:
            aclID = acl["AclEntityId"]
            aclRole = get_acl_role(aclID)
            # print aclID
            if aclID == 0 or aclID == 1:
                # ITSA LEVEL
                orgs = load_all_orgs()
                imagelibraries = load_system_ilibs()
                # depts = load_all_depts(orgs)
            else:
                imagelibraries = load_owned_libraries(parent_ent_id=aclID)
                departm = load_owned_departments(parent_ent_id=aclID)
                vir_nets = load_owned_virnets(parent_ent_id=aclID)
                vdcs = load_owned_vdcs(parent_ent_id=aclID)

                # load_owned_objects_rec_nonnest(aclID, objects)  # produces array of dictionaries
        # objects = json.loads(json.dumps(objects))
        jStack = json_list_objects(address, orgs, imagelibraries, departm, vir_nets, vdcs, aclRole)
        print json.dumps(jStack, sort_keys=True, indent=4, separators=(',', ': '))

    return False


def servePUT(env, start_response):
    response_header = [('Content-Type', 'cloudflows.net.Authenticate+json')]
    if env['REQUEST_METHOD'] == "PUT":  # TODO NOT ALL OF THEM ARE PUT, LOOK AT DOCS
        try:
            token = env['HTTP_X_AUTH_TOKEN']
        except KeyError:
            start_response('400 Bad Request', response_header)
            return ['No auth-token present\r\n']
        start_response('200 OK', response_header)

        address = env['PATH_INFO']
        try:
            request_body_size = int(env.get('CONTENT_LENGTH', 0))
        except (ValueError):
            request_body_size = 0
        data = env['wsgi.input'].read(request_body_size)

        userData = validate_token(token)
        if userData is not False:
            request_api(address, data, userData, env['REQUEST_METHOD'])
            return ["TOKEN VALID: " + token]

        # else cannot auth
        start_response('401 Unauthorized', response_header)
        return ["TOKEN INVALID: " + token]
    elif env['REQUEST_METHOD'] == "POST":
        if env['PATH_INFO'] == '/authenticate':
            start_response('200 OK', response_header)

            try:
                request_body_size = int(env.get('CONTENT_LENGTH', 0))
            except (ValueError):
                request_body_size = 0
            request_body = env['wsgi.input'].read(request_body_size)
            data = parse_qs(request_body)
            user = escape(data.get("user")[0])
            passw = escape(data.get("pass")[0])
            tokenResp = get_token_json_response(user, passw)
            if tokenResp is False:
                start_response('401 Unauthorized', response_header)
                return ["Authentication failed"]
            return [tokenResp]  # TODO Formatting?
    start_response('400 Bad Request', response_header)
    return [str(str(x) + ": " + str(env[x]) + "\n") for x in env]
    # return ['Only use PUT requests\r\n']

# scp
wsgi.server(eventlet.listen(('', 8091)), servePUT)
db.close()
