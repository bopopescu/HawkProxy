import websocket
import ujson
import eventlet
import time

eventlet.monkey_patch()


def display_response(ws):
    while True:
        got = ws.recv()
        print "Got....%s" % got


if __name__ == '__main__':
    ws = websocket.create_connection('ws://localhost:8088/ws?user_id=123456789')
    eventlet.spawn_n(display_response, ws)
    message = {"function": "chart_start",
               "sequnece_id": 1,
               "message_id": "abcded",
               "parameters": [

                   {"dbid": 2790, "entity": "Widget", "widgetId": 4455, "type": [{"chart": "System",

                                                                                  "interfaceId": "0",
                                                                                  "serverFarmId": "0",
                                                                                  "serverId": "0"}]}
               ]}

    ws.send(ujson.dumps(message))

    while True:
        time.sleep(1)

    x = {{"dbid": 2790, "entity": "Widget", "widgetId": 4455, "type": [{"chart": "Network",
                                                                        "interfaceId": "2792",
                                                                        "serverFarmId": "0",
                                                                        "serverId": "0"}
                                                                       ]},
         {"dbid": 2790, "entity": "Widget", "widgetId": 4455, "type": [{"chart": "Storage",
                                                                        "interfaceId": "0",
                                                                        "serverFarmId": "0",
                                                                        "serverId": "0"}
                                                                       ]}}
