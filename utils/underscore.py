#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

import os
import gettext

_localedir = os.environ.get('hawk'.upper() + '_LOCALEDIR')
_t = gettext.translation('hawk', localedir=_localedir, fallback=True)


def _(msg):
    return _t.ugettext(msg)
