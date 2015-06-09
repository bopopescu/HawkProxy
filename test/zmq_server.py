#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from eventlet.green import zmq
from random import randrange

if __name__ == '__main__':

    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind("tcp://127.0.0.1:5556")

    while True:
        zipcode = randrange(1, 100000)
        temperature = randrange(-80, 135)
        relhumidity = randrange(10, 60)

        publisher.send_string("%i %i %i" % (zipcode, temperature, relhumidity))

    publisher.close()
    context.term()
