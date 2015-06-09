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
    ws = websocket.create_connection('ws://192.168.1.118:8088/ws?user_id=123456789')
    eventlet.spawn_n(display_response, ws)
    message = {"function": "chart_start",
               "sequnece_id": 1,
               "message_id": "abcded",
               "parameters": [{"dbid": 2790, "type": ["throughput_percentage", "cpu_percentage"], "entity": "Compute"},
                              {"dbid": 2810, "type": ["throughput_percentage", "cpu_percentage"], "entity": "Network"}]}

    ws.send(ujson.dumps(message))

    while True:
        time.sleep(1)
