"""Owner-signed login; the private viewer password never leaves the viewer."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading
import time

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from control_protocol import APP


def owner_signer(secret):
    if not isinstance(secret, str) or not 32 <= len(secret) <= 128:
        raise ValueError('Enter your private connection password, or use the saved password on this viewer.')
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(('RoomCam-owner:' + secret).encode()).digest())


def owner_public(secret):
    return base64.b64encode(owner_signer(secret).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def owner_topic(public):
    return 'roomcam-owner-' + hashlib.sha256(public.encode()).hexdigest()[:40]


def session_proof(challenge, password):
    body = json.dumps({key: challenge[key] for key in ('owner', 'session', 'token', 'host_key', 'endpoint', 'certificate')}, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(password.encode(), body, hashlib.sha256).hexdigest()


def login_message(payload):
    return json.dumps({key: payload[key] for key in ('app', 'operation', 'session', 'token', 'host_key', 'endpoint', 'certificate', 'viewer_key', 'nonce', 'credential')},
                      sort_keys=True, separators=(',', ':')).encode()


def public_bytes(key):
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def channel_key(private, public):
    shared = private.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True)))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'RoomCam-owner-login-v1').derive(shared)


def sign_login(secret, challenge, username, password):
    valid_username(username)
    key = X25519PrivateKey.generate()
    payload = dict(app=APP, operation='owner-login-v1', session=challenge['session'], token=challenge['token'],
                   host_key=challenge['host_key'], endpoint=challenge['endpoint'], certificate=challenge['certificate'], viewer_key=public_bytes(key))
    nonce = secrets.token_bytes(12)
    # Encrypt the disposable API credential to the host's challenge key. A
    # spoofed discovery endpoint cannot relay a proof and learn this password.
    credential = json.dumps(dict(username=username, password=password)).encode()
    aad = (payload['session'] + ':' + payload['token']).encode()
    payload['nonce'] = base64.b64encode(nonce).decode()
    payload['credential'] = base64.b64encode(AESGCM(channel_key(key, payload['host_key'])).encrypt(nonce, credential, aad)).decode()
    payload['proof'] = base64.b64encode(owner_signer(secret).sign(login_message(payload))).decode()
    return payload


def valid_username(username):
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', username):
        raise ValueError('Choose a username using 1–64 letters, numbers, dots, underscores, @ or hyphens.')
    return username


def saved_owner_secret(directory):
    path = Path(directory) / 'owner-password.txt'
    if not path.is_file():
        return None
    if path.stat().st_size > 256:
        raise ValueError('Saved private connection password is invalid.')
    secret = path.read_text(encoding='utf-8').strip()
    owner_signer(secret)
    return secret


class OwnerAuth:
    def __init__(self, public, session, lifetime=45):
        self.public = public
        self.key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True))
        self.session = session
        self.lifetime = lifetime
        self.pending = {}
        self.channel = X25519PrivateKey.generate()
        self.host_key = public_bytes(self.channel)
        self.lock = threading.Lock()

    def challenge(self, endpoint='', certificate=''):
        with self.lock:
            now = time.monotonic()
            self.pending = {token: created for token, created in self.pending.items() if now - created <= self.lifetime}
            if len(self.pending) >= 32:
                raise RuntimeError('Too many login attempts. Try again shortly.')
            token = secrets.token_urlsafe(32)
            self.pending[token] = now
            return dict(owner=self.public, session=self.session, token=token, host_key=self.host_key, endpoint=endpoint, certificate=certificate)

    def accept(self, payload):
        if not isinstance(payload, dict) or payload.get('app') != APP or payload.get('operation') != 'owner-login-v1' or payload.get('session') != self.session:
            raise ValueError('Private viewer login rejected.')
        if payload.get('host_key') != self.host_key:
            raise ValueError('Login belongs to another host.')
        token = payload.get('token')
        if not isinstance(token, str):
            raise ValueError('Invalid login challenge.')
        try:
            proof = base64.b64decode(payload.get('proof', ''), validate=True)
            self.key.verify(proof, login_message(payload))
            aad = (self.session + ':' + token).encode()
            credential = json.loads(AESGCM(channel_key(self.channel, payload['viewer_key'])).decrypt(
                base64.b64decode(payload['nonce'], validate=True), base64.b64decode(payload['credential'], validate=True), aad))
            valid_username(credential.get('username'))
            if not isinstance(credential.get('password'), str) or not 32 <= len(credential['password']) <= 128:
                raise ValueError('Invalid connection credential.')
        except (InvalidSignature, InvalidTag, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError('Private viewer login rejected.') from exc
        with self.lock:
            created = self.pending.get(token)
            if created is None or time.monotonic() - created > self.lifetime:
                raise ValueError('Login challenge expired or already used.')
            del self.pending[token]
        return credential['username'], credential['password']
