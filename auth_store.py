"""Local demo account store: PBKDF2 password hashes, roles, and login throttling.

Educational authentication for a localhost / synthetic-data portfolio demo.
Use a reputable OIDC identity provider for real customer deployments.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from ticket_store import DEFAULT_DB, connection

ROLES = {'customer', 'agent', 'admin'}
ITERATIONS = 600_000
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


class AuthError(ValueError):
    pass


def init_auth(db_path=DEFAULT_DB):
    with connection(db_path) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS app_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('customer','agent','admin')),
                customer_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                CHECK ((role='customer' AND customer_id IS NOT NULL) OR
                       (role IN ('agent','admin') AND customer_id IS NULL))
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                username TEXT PRIMARY KEY,
                failures INTEGER NOT NULL,
                last_failed_epoch REAL NOT NULL
            );
        ''')


def normalized_username(username):
    if not isinstance(username, str):
        raise AuthError('Invalid username.')
    name = username.strip().lower()
    if not re.fullmatch(r'[a-z][a-z0-9_.-]{2,39}', name):
        raise AuthError('Use 3–40 lowercase letters, digits, underscore, dash or dot (start with a letter).')
    return name


def _password_is_valid(password):
    return isinstance(password, str) and 12 <= len(password) <= 256 and not password.isspace()


def hash_password(password):
    if not _password_is_valid(password):
        raise AuthError('Password must contain 12–256 characters.')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}'


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 100_000 <= int(iterations) <= 1_000_000:
            return False
        if not isinstance(password, str) or len(password) > 256:
            return False
        tested = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                     bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(tested, bytes.fromhex(digest_hex))
    except (ValueError, TypeError, AttributeError):
        return False


def create_user(db_path, *, username, password, role, customer_id=None):
    name = normalized_username(username)
    if role not in ROLES:
        raise AuthError('Invalid role.')
    if role == 'customer':
        if not isinstance(customer_id, str) or not re.fullmatch(r'CUST-[A-Za-z0-9-]{1,35}', customer_id):
            raise AuthError('Customer accounts require a valid CUST-... identifier.')
    elif customer_id is not None:
        raise AuthError('Agent and admin accounts cannot be bound to a customer ID.')
    secret_hash = hash_password(password)
    try:
        with connection(db_path) as db:
            cur = db.execute('''INSERT INTO app_users (username,password_hash,role,customer_id)
                                VALUES (?,?,?,?)''', (name, secret_hash, role, customer_id))
            return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise AuthError('Username already exists.') from exc


def authenticate(db_path, *, username, password, now=None):
    """Return an identity or None. Lock after 5 failures for 15 minutes, across sessions."""
    try:
        name = normalized_username(username)
    except AuthError:
        return None
    now = time.time() if now is None else float(now)
    with connection(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        attempt = db.execute('SELECT * FROM login_attempts WHERE username=?', (name,)).fetchone()
        failed_recently = attempt and now - attempt['last_failed_epoch'] < LOCK_SECONDS
        if failed_recently and attempt['failures'] >= MAX_FAILURES:
            return None
        user = db.execute('SELECT * FROM app_users WHERE username=? AND is_active=1', (name,)).fetchone()
        valid = bool(user and verify_password(password, user['password_hash']))
        if valid:
            db.execute('DELETE FROM login_attempts WHERE username=?', (name,))
            return {'id': user['id'], 'username': user['username'],
                    'role': user['role'], 'customer_id': user['customer_id']}
        count = (attempt['failures'] if failed_recently else 0) + 1
        db.execute('''INSERT INTO login_attempts(username, failures, last_failed_epoch) VALUES(?,?,?)
                      ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,
                          last_failed_epoch=excluded.last_failed_epoch''', (name, count, now))
        return None


def active_user(db_path, user_id):
    if not isinstance(user_id, int):
        return None
    with connection(db_path) as db:
        u = db.execute('SELECT id,username,role,customer_id FROM app_users WHERE id=? AND is_active=1',
                       (user_id,)).fetchone()
        return dict(u) if u else None


def bootstrap_from_env(db_path=DEFAULT_DB):
    """Optional first-run users from secret environment variables. Never overwrite accounts."""
    configs = (('ADMIN', 'admin'), ('AGENT', 'agent'), ('CUSTOMER', 'customer'))
    for prefix, role in configs:
        name = os.getenv(f'QC_BOOTSTRAP_{prefix}_USER')
        secret = os.getenv(f'QC_BOOTSTRAP_{prefix}_PASSWORD')
        if not name and not secret:
            continue
        if not name or not secret:
            raise AuthError(f'Incomplete QC_BOOTSTRAP_{prefix} credentials.')
        normal = normalized_username(name)
        with connection(db_path) as db:
            exists = db.execute('SELECT 1 FROM app_users WHERE username=?', (normal,)).fetchone()
        if not exists:
            create_user(db_path, username=normal, password=secret, role=role,
                        customer_id=os.getenv('QC_BOOTSTRAP_CUSTOMER_ID') if role == 'customer' else None)
