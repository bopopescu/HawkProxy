# MySQL Connector/Python - MySQL driver written in Python.
# Copyright (c) 2009, 2013, Oracle and/or its affiliates. All rights reserved.

# MySQL Connector/Python is licensed under the terms of the GPLv2
# <http://www.gnu.org/licenses/old-licenses/gpl-2.0.html>, like most
# MySQL Connectors. There are special exceptions to the terms and
# conditions of the GPLv2 as it is applied to this software, see the
# FOSS License Exception
# <http://www.mysql.com/about/legal/licensing/foss-exception.html>.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA

"""Utilities
"""

__MYSQL_DEBUG__ = False

import struct


def intread(buf):
    """Unpacks the given buffer to an integer"""
    try:
        if isinstance(buf, int):
            return buf
        length = len(buf)
        if length == 1:
            return int(ord(buf))
        if length <= 4:
            tmp = buf + '\x00' * (4 - length)
            return struct.unpack('<I', tmp)[0]
        else:
            tmp = buf + '\x00' * (8 - length)
            return struct.unpack('<Q', tmp)[0]
    except:
        raise


def int1store(i):
    """
    Takes an unsigned byte (1 byte) and packs it as string.

    Returns string.
    """
    if i < 0 or i > 255:
        raise ValueError('int1store requires 0 <= i <= 255')
    else:
        return struct.pack('<B', i)


def int2store(i):
    """
    Takes an unsigned short (2 bytes) and packs it as string.

    Returns string.
    """
    if i < 0 or i > 65535:
        raise ValueError('int2store requires 0 <= i <= 65535')
    else:
        return struct.pack('<H', i)


def int3store(i):
    """
    Takes an unsigned integer (3 bytes) and packs it as string.

    Returns string.
    """
    if i < 0 or i > 16777215:
        raise ValueError('int3store requires 0 <= i <= 16777215')
    else:
        return struct.pack('<I', i)[0:3]


def int4store(i):
    """
    Takes an unsigned integer (4 bytes) and packs it as string.

    Returns string.
    """
    if i < 0 or i > 4294967295L:
        raise ValueError('int4store requires 0 <= i <= 4294967295')
    else:
        return struct.pack('<I', i)


def int8store(i):
    """
    Takes an unsigned integer (4 bytes) and packs it as string.

    Returns string.
    """
    if i < 0 or i > 18446744073709551616L:
        raise ValueError('int4store requires 0 <= i <= 2^64')
    else:
        return struct.pack('<Q', i)


def intstore(i):
    """
    Takes an unsigned integers and packs it as a string.

    This function uses int1store, int2store, int3store,
    int4store or int8store depending on the integer value.

    returns string.
    """
    if i < 0 or i > 18446744073709551616:
        raise ValueError('intstore requires 0 <= i <= 2^64')

    if i <= 255:
        formed_string = int1store
    elif i <= 65535:
        formed_string = int2store
    elif i <= 16777215:
        formed_string = int3store
    elif i <= 4294967295L:
        formed_string = int4store
    else:
        formed_string = int8store

    return formed_string(i)


def read_bytes(buf, size):
    """
    Reads bytes from a buffer.

    Returns a tuple with buffer less the read bytes, and the bytes.
    """
    res = buf[0:size]
    return (buf[size:], res)


def read_lc_string(buf):
    """
    Takes a buffer and reads a length coded string from the start.

    This is how Length coded strings work

    If the string is 250 bytes long or smaller, then it looks like this:

      <-- 1b  -->
      +----------+-------------------------
      |  length  | a string goes here
      +----------+-------------------------

    If the string is bigger than 250, then it looks like this:

      <- 1b -><- 2/3/8 ->
      +------+-----------+-------------------------
      | type |  length   | a string goes here
      +------+-----------+-------------------------

      if type == \xfc:
          length is code in next 2 bytes
      elif type == \xfd:
          length is code in next 3 bytes
      elif type == \xfe:
          length is code in next 8 bytes

    NULL has a special value. If the buffer starts with \xfb then
    it's a NULL and we return None as value.

    Returns a tuple (trucated buffer, string).
    """
    if buf[0] == '\xfb':
        # NULL value
        return (buf[1:], None)

    length = lsize = 0
    fst = ord(buf[0])

    if fst <= 250:
        length = fst
        return (buf[1 + length:], buf[1:length + 1])
    elif fst == 252:
        lsize = 2
    elif fst == 253:
        lsize = 3
    if fst == 254:
        lsize = 8

    length = intread(buf[1:lsize + 1])
    return (buf[lsize + length + 1:], buf[lsize + 1:length + lsize + 1])


def read_lc_string_list(buf):
    """Reads all length encoded strings from the given buffer

    Returns a list of strings
    """
    strlst = []

    pos = 0
    len_buf = len(buf)
    while pos < len_buf:
        if buf[pos] == '\xfb':
            # NULL value
            strlst.append(None)
            pos += 1
            continue
        elif buf[pos] == '\xff':
            # Special case when MySQL error (usually 1317) is returned by MySQL.
            # We simply return None.
            return None

        length = lsize = 0
        fst = ord(buf[pos])

        if fst <= 250:
            length = fst
            strlst.append(buf[pos + 1:pos + length + 1])
            pos = pos + length + 1
            continue

        if fst == 252:
            lsize = 2
            fmt = '<H'
        elif fst == 253:
            lsize = 3
            fmt = '<I'
        if fst == 254:
            lsize = 8
            fmt = '<Q'

        tmp = buf[pos + 1:pos + lsize + 1]
        if lsize == 3:
            tmp += '\x00'
        length = struct.unpack(fmt, tmp)[0]

        strlst.append(buf[pos + lsize + 1:pos + length + lsize + 1])
        # buf = buf[lsize + length + 1:]
        pos = pos + lsize + length + 1

    return tuple(strlst)


def read_string(buf, end=None, size=None):
    """
    Reads a string up until a character or for a given size.

    Returns a tuple (trucated buffer, string).
    """
    if end is None and size is None:
        raise ValueError('read_string() needs either end or size')

    if end is not None:
        try:
            idx = buf.index(end)
        except ValueError:
            raise ValueError("end byte not precent in buffer")
        return (buf[idx + 1:], buf[0:idx])
    elif size is not None:
        return read_bytes(buf, size)

    raise ValueError('read_string() needs either end or size (weird)')


def read_int(buf, size):
    """Read an integer from buffer

    Returns a tuple (truncated buffer, int)
    """

    try:
        res = intread(buf[0:size])
    except:
        raise

    return (buf[size:], res)


def read_lc_int(buf):
    """
    Takes a buffer and reads an length code string from the start.

    Returns a tuple with buffer less then integer and the integer read.
    """
    if not buf:
        raise ValueError("Empty buffer.")

    lcbyte = ord(buf[0])
    if lcbyte == 251:
        return (buf[1:], None)
    elif lcbyte < 251:
        return (buf[1:], int(lcbyte))
    elif lcbyte == 252:
        return (buf[3:], struct.unpack('<xH', buf[0:3])[0])
    elif lcbyte == 253:
        return (buf[4:], struct.unpack('<I', buf[1:4] + '\x00')[0])
    elif lcbyte == 254:
        return (buf[9:], struct.unpack('<xQ', buf[0:9])[0])
    else:
        raise ValueError("Failed reading length encoded integer")


#
# For debugging
#
def _digest_buffer(buf):
    """Debug function for showing buffers"""
    return ''.join(["\\x%02x" % ord(c) for c in buf])
