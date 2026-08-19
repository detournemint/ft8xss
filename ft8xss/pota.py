"""Parks On The Air: self-spotting, park lookup, and activation upload.

An activation is ten contacts and a log file, and the two things that decide
whether you get the ten are whether hunters know you are there and whether you
are on a frequency they are watching. Self-spotting is therefore not a
convenience -- it is most of the activation.

Three of the four calls here need no credentials at all:

    spot()      tell pota.app you are on the air        no auth
    park()      look up a reference                     no auth
    nearby()    parks near a grid square                no auth
    upload()    file the activation log                 Cognito

The authentication is AWS Cognito's SRP flow, which is intricate enough that
getting it slightly wrong fails in ways that look like a bad password. The
implementation is ported from ft8web by Clint Todish, W5EEZ, which is GPLv3 as
this is -- see https://github.com/w5eez/ft8web, backend/scripts/pota_api.py.
It is reproduced rather than reinvented because there is exactly one correct
answer and his already works.

Standard library only. A park activation runs on whatever laptop is in the
car, and "pip install" is not a thing you want to discover you need at a
picnic table with no signal.
"""
import base64
import binascii
import datetime
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

REGION = "us-east-2"
POOL_ID = "us-east-2_nA5jZ0klh"
CLIENT_ID = "7hluqct0n2nckib7i7sd5753oa"
COGNITO_URL = "https://cognito-idp.%s.amazonaws.com/" % REGION
API = "https://api.pota.app"
AGENT = "ft8xss/1.0"
TIMEOUT = 20

# The SRP group AWS uses. Both sides must agree on it exactly.
N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64"
    "ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6B"
    "F12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB31"
    "43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF"
)
G_HEX = "2"
INFO_BITS = bytearray("Caldera Derived Key", "utf-8")


class PotaError(Exception):
    pass


# ---------------------------------------------------------------- transport --
def _http(url, data=None, headers=None, method=None):
    hdr = {"User-Agent": AGENT}
    if headers:
        hdr.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdr.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdr, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise PotaError("%s said %d: %s" % (url.split("/")[2], e.code, detail))
    except OSError as e:
        raise PotaError("could not reach %s: %s" % (url.split("/")[2], e))
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


# ------------------------------------------------------------------- grids --
def grid_to_latlon(grid):
    """Maidenhead locator to the centre of the square.

    Nearby-park lookup wants a position and a station already knows its grid,
    so this saves asking for something the operator has already typed in.
    """
    g = (grid or "").strip().upper()
    if len(g) < 4 or not g[0:2].isalpha() or not g[2:4].isdigit():
        raise PotaError("%r is not a grid square" % (grid,))
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) >= 6 and g[4:6].isalpha():
        lon += (ord(g[4]) - 65) * (2 / 24.0) + (1 / 24.0)
        lat += (ord(g[5]) - 65) * (1 / 24.0) + (1 / 48.0)
    else:
        lon += 1.0
        lat += 0.5
    return round(lat, 4), round(lon, 4)


# ------------------------------------------------------- unauthenticated --
def spot(activator, reference, freq_khz, mode="FT8", comments="",
         source="ft8xss"):
    """Tell pota.app you are on the air. This is what brings the hunters.

    POTA takes frequency in kilohertz as a string. Sending megahertz puts you
    on a frequency nobody is listening to, and the API will accept it.
    """
    activator = (activator or "").strip().upper()
    reference = (reference or "").strip().upper()
    if not activator or not reference:
        raise PotaError("callsign and park reference are both required")
    freq = str(freq_khz).strip()
    if freq.replace(".", "", 1).isdigit() and float(freq) < 1000:
        raise PotaError("frequency looks like MHz (%s); POTA wants kHz" % freq)
    return _http(API + "/spot", data={
        "activator": activator, "spotter": activator, "frequency": freq,
        "reference": reference, "mode": mode, "source": source,
        "comments": comments[:100],
    }, headers={"origin": "https://pota.app",
                "referer": "https://pota.app/"})


def park(reference):
    """Details for one reference, with how many times it has been activated."""
    ref = (reference or "").strip().upper()
    if not ref:
        raise PotaError("no reference given")
    d = _http("%s/park/%s" % (API, ref))
    if not isinstance(d, dict) or not d:
        # POTA renumbered: US-#### replaced K-#### for the United States, and
        # the API answers a retired reference with a bare null rather than an
        # error, so this has to be checked rather than trusted.
        raise PotaError("%s is not a park reference (US- replaced K- for "
                        "United States parks)" % ref)
    try:
        s = _http("%s/park/stats/%s" % (API, ref))
        if isinstance(s, dict) and "activations" in s:
            d["activations"] = s["activations"]
    except PotaError:
        pass                      # stats are a nicety, the park is the answer
    return d


def nearby(grid=None, lat=None, lon=None, span=0.5):
    """Parks in a box around a position, nearest-ish first.

    `span` is degrees either side: half a degree is roughly 55 km north-south
    and less east-west as you go north, which is about the distance worth
    driving to activate something else on the same trip.
    """
    if lat is None or lon is None:
        lat, lon = grid_to_latlon(grid)
    url = "%s/park/grids/%.4f/%.4f/%.4f/%.4f/0" % (
        API, lat - span, lon - span, lat + span, lon + span)
    got = _http(url)
    # GeoJSON: a FeatureCollection whose features carry the reference and name
    # in properties and the position in geometry.coordinates as [lon, lat] --
    # longitude first, which is the opposite order to how anyone says it.
    out = []
    for f in (got.get("features") or []) if isinstance(got, dict) else []:
        props = f.get("properties") or {}
        ref = props.get("reference")
        if not ref:
            continue
        coords = ((f.get("geometry") or {}).get("coordinates") or [None, None])
        rec = {"reference": ref, "name": props.get("name", ""),
               "longitude": coords[0], "latitude": coords[1]}
        try:
            rec["km"] = round(_haversine(lat, lon, float(coords[1]),
                                         float(coords[0])), 1)
        except (TypeError, ValueError, IndexError):
            rec["km"] = None
        out.append(rec)
    out.sort(key=lambda p: (p["km"] is None, p["km"] or 0))
    return out


def _haversine(lat1, lon1, lat2, lon2):
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


# ------------------------------------------------ Cognito SRP (from ft8web) --
def _hash(buf):
    return hashlib.sha256(buf).hexdigest().rjust(64, "0")


def _hex_hash(hex_string):
    return _hash(bytearray.fromhex(hex_string))


def _pad_hex(value):
    """Even length, and a leading 00 when the high bit is set so the number
    reads as positive. Getting this wrong fails as 'bad password'."""
    h = value if isinstance(value, str) else "%x" % value
    if len(h) % 2 == 1:
        h = "0" + h
    elif h[0] in "89ABCDEFabcdef":
        h = "00" + h
    return h


def _hkdf(ikm, salt):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, INFO_BITS + bytearray(chr(1), "utf-8"),
                    hashlib.sha256).digest()[:16]


def _timestamp():
    """AWS wants 'Ddd Mmm D HH:MM:SS UTC YYYY' in English with an unpadded
    day, whatever the host locale says."""
    now = datetime.datetime.now(datetime.timezone.utc)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return "%s %s %d %02d:%02d:%02d UTC %d" % (
        days[now.weekday()], months[now.month - 1], now.day,
        now.hour, now.minute, now.second, now.year)


def _cognito(target, payload):
    return _http(COGNITO_URL, data=payload, headers={
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService." + target,
    })


def authenticate(username, password):
    """Log in to pota.app and return an id token."""
    big_n = int(N_HEX, 16)
    g = int(G_HEX, 16)
    k = int(_hex_hash(_pad_hex(N_HEX) + _pad_hex(G_HEX)), 16)
    small_a = int(binascii.hexlify(os.urandom(128)), 16) % big_n
    big_a = pow(g, small_a, big_n)
    if big_a % big_n == 0:
        raise PotaError("SRP safety check on A failed")

    init = _cognito("InitiateAuth", {
        "AuthFlow": "USER_SRP_AUTH", "ClientId": CLIENT_ID,
        "AuthParameters": {"USERNAME": username, "SRP_A": "%x" % big_a},
    })
    ch = init.get("ChallengeParameters") or {}
    try:
        user_id, salt = ch["USER_ID_FOR_SRP"], ch["SALT"]
        secret_block = ch["SECRET_BLOCK"]
        server_b = int(ch["SRP_B"], 16)
    except KeyError:
        raise PotaError("unexpected Cognito challenge -- is the account valid?")
    if server_b % big_n == 0:
        raise PotaError("SRP B mod N cannot be zero")

    u_value = int(_hex_hash(_pad_hex(big_a) + _pad_hex(server_b)), 16)
    if u_value == 0:
        raise PotaError("SRP U cannot be zero")
    pool = POOL_ID.split("_")[1]
    id_hash = _hash(("%s%s:%s" % (pool, user_id, password)).encode())
    x_value = int(_hex_hash(_pad_hex(salt) + id_hash), 16)
    s_value = pow(server_b - k * pow(g, x_value, big_n),
                  small_a + u_value * x_value, big_n)
    key = _hkdf(bytearray.fromhex(_pad_hex("%x" % s_value)),
                bytearray.fromhex(_pad_hex("%x" % u_value)))

    stamp = _timestamp()
    msg = (pool.encode() + user_id.encode()
           + base64.standard_b64decode(secret_block) + stamp.encode())
    sig = base64.standard_b64encode(
        hmac.new(key, msg, hashlib.sha256).digest()).decode()

    resp = _cognito("RespondToAuthChallenge", {
        "ClientId": CLIENT_ID, "ChallengeName": "PASSWORD_VERIFIER",
        "ChallengeResponses": {
            "USERNAME": user_id, "PASSWORD_CLAIM_SECRET_BLOCK": secret_block,
            "PASSWORD_CLAIM_SIGNATURE": sig, "TIMESTAMP": stamp,
        },
    })
    result = resp.get("AuthenticationResult") or {}
    if not result.get("IdToken"):
        raise PotaError("no auth result -- check the POTA username and password")
    return result["IdToken"]


def upload(token, adif_text, filename="ft8xss.adi"):
    """File an activation log."""
    if not adif_text.strip():
        raise PotaError("nothing to upload")
    return _http(API + "/adif", data={
        "filename": filename, "file": adif_text,
    }, headers={"Authorization": token})


def activations(token):
    return _http(API + "/user/activations?all=1", headers={
        "Authorization": token})
