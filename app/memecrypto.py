import hashlib

DER = bytes.fromhex(
    "307c300d06092a864886f70d0101010500036b003068026100b61e192091f90a8f76a6eaaa9a3ce58c863f39ae253f037816f5975854e07a"
    "9a456601e7c94c29759fe155c064eddfa111443f81ef1a428cf6cd32f9dac9d48e94cfb3f690120e8e6b9111addaf11e7c96208c37c0143f"
    "f2bf3d7e831141a9730203010001")
D = int.from_bytes(bytes.fromhex(
    "00775455668fff3cba3026c2d0b26b8085895958341157aeb03b6b0495ee57803e2186eb6cb2eb62a71df18a3c9c6579077670961b3a6102"
    "dabe5a194ab58c3250aed597fc78978a326db1d7b28dcccb2a3e014edbd397ad33b8f28cd525054251"), "big")
N = int.from_bytes(DER[0x18:0x18 + 0x61], "big")
E = int.from_bytes(DER[0x7B:0x7E], "big")
SIG = 0x60
SIZES = {0x6BE00: (0x6BA00 + 0x100, 0x140), 0x6CC00: (0x6C000 + 0x100, 0x150)}

_SBOX = []
_INV = [0] * 256


def _init():
    p = q = 1
    box = [0] * 256
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1 | q >> 7) & 0xFF) ^ ((q << 2 | q >> 6) & 0xFF) ^ ((q << 3 | q >> 5) & 0xFF) ^ ((q << 4 | q >> 4) & 0xFF)
        box[p] = x ^ 0x63
        if p == 1:
            break
    box[0] = 0x63
    _SBOX.extend(box)
    for i, v in enumerate(box):
        _INV[v] = i


_init()


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rc = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rc
            rc = _xt(rc)
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(11)]


def _enc(rk, block):
    s = [a ^ b for a, b in zip(block, rk[0])]
    for r in range(1, 11):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]
        if r < 10:
            m = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                m += [_mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3], a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3],
                      a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3), _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)]
            s = m
        s = [a ^ b for a, b in zip(s, rk[r])]
    return bytes(s)


def _dec(rk, block):
    s = [a ^ b for a, b in zip(block, rk[10])]
    for r in range(9, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]
        s = [_INV[b] for b in s]
        s = [a ^ b for a, b in zip(s, rk[r])]
        if r:
            m = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                m += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9),
                      _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13),
                      _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11),
                      _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
            s = m
    return bytes(s)


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _subkey(t):
    out = bytearray(16)
    for i in range(0, 16, 2):
        out[i] = (2 * t[i] + (t[i + 1] >> 7)) & 0xFF
        out[i + 1] = (2 * t[i + 1] + (t[i + 2] >> 7 if i + 2 < 16 else 0)) & 0xFF
    if t[0] & 0x80:
        out[15] ^= 0x87
    return bytes(out)


def _key(payload):
    return _expand(hashlib.sha1(DER + bytes(payload)).digest()[:16])


def _aes_encrypt(data):
    rk = _key(data[:-SIG])
    sig = [bytes(data[-SIG + i:len(data) - SIG + i + 16]) for i in range(0, SIG, 16)]
    temp = bytes(16)
    for i in range(len(sig)):
        sig[i] = _enc(rk, _xor(sig[i], temp))
        temp = sig[i]
    nxt = _subkey(_xor(temp, sig[0]))
    sig = [_xor(s, nxt) for s in sig]
    temp = bytes(16)
    for i in range(len(sig) - 1, -1, -1):
        keep = sig[i]
        sig[i] = _xor(_enc(rk, sig[i]), temp)
        temp = keep
    return bytes(data[:-SIG]) + b"".join(sig)


def _aes_decrypt(data):
    rk = _key(data[:-SIG])
    sig = [bytes(data[-SIG + i:len(data) - SIG + i + 16]) for i in range(0, SIG, 16)]
    temp = bytes(16)
    for i in range(len(sig) - 1, -1, -1):
        temp = _dec(rk, _xor(temp, sig[i]))
        sig[i] = temp
    nxt = _subkey(_xor(temp, sig[-1]))
    sig = [_xor(s, nxt) for s in sig]
    nxt = bytes(16)
    for i in range(len(sig)):
        keep = sig[i]
        sig[i] = _xor(_dec(rk, sig[i]), nxt)
        nxt = keep
    return bytes(data[:-SIG]) + b"".join(sig)


def verify(data):
    m = pow(int.from_bytes(data[-SIG:], "big"), E, N)
    for top in (0, 0x80):
        sig = bytearray(m.to_bytes(SIG, "big"))
        sig[0] |= top
        out = _aes_decrypt(bytes(data[:-SIG]) + bytes(sig))
        if hashlib.sha1(out[:-8]).digest()[:8] == out[-8:]:
            return out
    return None


def sign(data):
    data = bytearray(data)
    data[-8:] = hashlib.sha1(bytes(data[:-8])).digest()[:8]
    data = bytearray(_aes_encrypt(bytes(data)))
    data[-SIG] &= 0x7F
    data[-SIG:] = pow(int.from_bytes(data[-SIG:], "big"), D, N).to_bytes(SIG, "big")
    return bytes(data)


def resign_save(raw):
    raw = bytearray(raw)
    if len(raw) not in SIZES:
        raise ValueError("sauvegarde 7G : taille inconnue")
    at, length = SIZES[len(raw)]
    table = bytes(raw[len(raw) - 0x200:len(raw) - 0x200 + length])
    raw[at:at + 0x80] = sign(hashlib.sha256(table).digest() + bytes(0x60))
    return bytes(raw)


def check_save(raw):
    if len(raw) not in SIZES:
        return False
    at, length = SIZES[len(raw)]
    out = verify(bytes(raw[at:at + 0x80]))
    return bool(out) and out[:0x20] == hashlib.sha256(bytes(raw[len(raw) - 0x200:len(raw) - 0x200 + length])).digest()
