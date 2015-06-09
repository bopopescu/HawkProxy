__author__ = 'vkorolik'
import ujson as json
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
    # log.info("AUTH RESP BODY: %s", json.loads(r.text))
    # log.info("AUTH RESP HEADERS: %s", str(r.headers))
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
    log.info(token)
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


def load_owned_objects_rec(ent_id):
    # THIS SHOULD RETURN ONE ARRAY OF NESTED ARRAYS OF DICTIONARIES
    # TODO Recursively load all objects that the user has control over
    # Takes a ACLEntityID
    # Looks at all entities with that parent ID
    # For each entity, look at other entities that are children of that entity
    # Don't go deeper than VDC?
    # Maybe load everything and then sort out unnecessary
    ents = cloudDB.get_multiple_row("tblEntities", "ParentEntityId='%s'" % (ent_id))
    # if len(ents) == 1:
    if len(ents) == 0 or ents is None:
        return dict()

    data = []
    for ent in ents:
        data.append(ent)
        data.append(load_owned_objects_rec(ent["id"]))

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


def load_all_depts(orgs_mysql_result):
    deptsArr = []
    for org in orgs_mysql_result:
        depts = cloudDB.get_multiple_row("tblEntities",
                                         "ParentEntityId='%s' AND EntityType='%s'" % (org["id"], "department"))
        for dept in depts:
            deptsArr.append(dept)
    return deptsArr


def request_api(address, data, userData):
    # address is relative url
    # data comes in json format
    ent_id = userData["tblEntities"]
    acls = cloudDB.get_multiple_row("tblEntitiesACL", "tblEntities='%s'" % (ent_id))
    print "API REQUEST: " + address + " " + data + " " + str(ent_id)

    if address == '/':
        objects = []  # array, contains array of org dictionaries, and array of dept dictionaries
        for acl in acls:
            aclID = acl["AclEntityId"]
            print aclID
            if aclID == 0 or aclID == 1:
                # ITSA LEVEL
                orgs = load_all_orgs()
                depts = load_all_depts(orgs)
                objects.append(orgs)
                objects.append(depts)
            else:
                load_owned_objects_rec_nonnest(aclID, objects)  # produces array of dictionaries
        # objects = json.loads(json.dumps(objects))
        pp.pprint(objects)

    return False


def servePUT(env, start_response):
    response_header = [('Content-Type', 'cloudflows.net.Authenticate+json')]
    if env['REQUEST_METHOD'] == "PUT":
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
            request_api(address, data, userData)
            return ["TOKEN VALID: " + token]

        # else cannot auth
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
