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


def load_all_vdcs():
    vdcArr = []
    return vdcArr


def load_ent_details(uuid):
    return cloudDB.get_row_dict("tblEntities", {"UniqueId": uuid})


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


def json_list_objects_arr(address, givens, aclRole):
    jStack = {}

    organizations = {}
    libraryimage = {}
    departments = {}
    virtual_networks = {}
    vdcs_complete = {}

    objects = [organizations, libraryimage, departments, virtual_networks, vdcs_complete]

    jStack.update({"uri": address, "type": aclRole})
    for one in givens:
        num = len(one)
        oneSpecs = {"type": "organization", "total": num}
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
        objects.append(load_all_orgs())
        objects.append(load_system_ilibs())
        # depts = load_all_depts(orgs)
    else:
        objects.append(load_owned_libraries(parent_ent_id=aclID))
        objects.append(load_owned_departments(parent_ent_id=aclID))
        objects.append(load_owned_virnets(parent_ent_id=aclID))
        objects.append(load_owned_vdcs(parent_ent_id=aclID))
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
            objects.append(load_all_orgs())
            objects.append(load_system_ilibs())
        elif aclRole == "vdc":
            # VDC USER LEVEL NEEDS SPECIAL CASE
            return False
        else:
            objects.append(load_owned_libraries(parent_ent_id=aclID))
            objects.append(load_owned_departments(parent_ent_id=aclID))
            objects.append(load_owned_virnets(parent_ent_id=aclID))
            objects.append(load_owned_vdcs(parent_ent_id=aclID))

    jStack = json_list_objects_arr(addr, objects, aclRole)
    stringVal = json.dumps(jStack, sort_keys=True, indent=4, separators=(',', ': '))


def request_api(addr, data, userData, reqm):
    # address is relative url
    # data comes in json format
    if addr[len(addr) - 1:] == '/':
        addr = addr[:-1]

    ent_id = userData["tblEntities"]
    acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (ent_id))
    print "API REQUEST: " + addr + " " + data + " " + str(reqm)

    split = addr[1:].split('/')

    if addr == '/listAll' and reqm == "GET":
        stringVal = listAll(acls, addr)
        print stringVal
        return stringVal
    elif reqm == "GET":
        # if split[0] == "organizations" or split[0] == "departments" or split[0] == "vdcs" or split[0] == "subnets" or split[0] == "nats" or split[0] == "organizations":
        if len(split[1]) == 36:
            data = {}
            details = load_ent_details(split[1])
            if len(split) < 3:
                data = details
                element = {}
                for key, value in data.iteritems():
                    element.update({str(key): str(value)})  # DUMP ALL DETAILS
                return json.dumps(element, sort_keys=True, indent=4, separators=(',', ': '))
            elif len(split) == 3:
                if split[2] == "departments":
                    ent_id_parent = details["id"]
                    data = load_owned_departments(ent_id_parent)

            return json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '))

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
                return ["NO Post data provided"]
            user = escape(data.get("user")[0])
            passw = escape(data.get("pass")[0])
            tokenResp = get_token_json_response(user, passw)
            if tokenResp is False:
                start_response('401 Unauthorized', response_header)
                return ["Authentication failed"]  # TODO Format json
            return [tokenResp]
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
                return ["TOKEN VALID: " + token + "\nAPI RESPONSE:\n" + apiResponse]

            # else cannot auth
            start_response('401 Unauthorized', defresponse_header)
            return ["TOKEN INVALID: " + token]
    else:
        start_response('400 Bad Request', defresponse_header)
        return ["Malformed/Unsupported API Version"]


wsgi.server(eventlet.listen(('', 8091)), serve)
