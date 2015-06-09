__author__ = 'vkorolik'
import eventlet
import ujson as json
import logging
from eventlet.green import urllib2
from eventlet import wsgi
from urlparse import urlparse, parse_qs
from cgi import escape
import requests
import cryptC as crypt
import MySQLdb
import time
from datetime import datetime, timedelta
from utils.cloud_utils import CloudGlobalBase

UA = "192.168.228.23:8231"
AUTH_URL = "http://192.168.228.23:8002/v3"
ENDPOINT_URL = "http://192.168.228.23:8002/v3"
MYSQL_HOST = "192.168.228.23"
MYSQL_PORT = 8000

log = logging.getLogger("log")
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)

db = MySQLdb.connect(host=MYSQL_HOST, port=MYSQL_PORT, user="root", passwd="cloud2674", db="CloudFlowPortal")
db.autocommit(True)

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
    cur = db.cursor()
    cur.execute("SELECT * FROM tblUsers WHERE LoginId='" + uname + "'")
    rows = cur.fetchall()
    print rows[0]
    if len(rows) > 1:
        log.critical("More than one user with same login id in mysql db.")
    elif len(rows) == 0:
        log.warning("User not found in mysql db.")
    else:
        entID = str(rows[0][1])
        t = time.strftime('%Y-%m-%d %H:%M:%S')
        t_ex = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        cloudDB.update_db("UPDATE tblUsers SET Token = '%s' WHERE tblEntities = '%s'" % (token, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenIssuedAt = '%s' WHERE tblEntities = '%s'" % (t, entID))
        cloudDB.update_db("UPDATE tblUsers SET TokenExpiresAt = '%s' WHERE tblEntities = '%s'" % (t_ex, entID))
        print cloudDB.get_row("SELECT * FROM tblUsers WHERE tblEntities=%s" % (entID))
    cur.close()


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
    # TODO mysql check here, extend expiration date
    # headers = {'X-Auth-Token':token, 'X-Subject-Token':token}
    # r = requests.get(AUTH_URL + "/auth/tokens", headers=headers)
    # log.info(r.text)
    # log.info(r.headers)
    # log.info(r.status_code)
    return False


def request_api(command):
    return False


def servePUT(env, start_response):
    response_header = [('Content-Type', 'cloudflows.net.Authenticate+json')]
    if env['REQUEST_METHOD'] == "PUT":
        if env['PATH_INFO'] == '/':
            try:
                token = env['HTTP_X_AUTH_TOKEN']
            except KeyError:
                start_response('400 Bad Request', response_header)
                return ['No auth-token present\r\n']
            start_response('200 OK', response_header)
            command = ""
            if validate_token(token):
                request_api(command)
            # else cannot auth
            return [env["HTTP_X_AUTH_TOKEN"]]
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
