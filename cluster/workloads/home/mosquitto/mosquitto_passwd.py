#!/usr/bin/python3

import hashlib
import base64
import random
import sys

print()

chars   = b'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

salt    = bytes([random.choice(chars) for i in range(16)])
saltB64 = base64.b64decode(salt)

passwd  = b'Put your password in here'

m = hashlib.sha512()
m.update(passwd)
m.update(saltB64)
dg = m.digest()

print('$6$%s$%s' % (repr(salt)[2:-1],repr(base64.b64encode(dg))[2:-1]))
