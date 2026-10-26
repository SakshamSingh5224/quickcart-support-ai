"""Provision local demo logins without putting passwords in shell history.

Usage:
  python -m scripts.manage_users create --username admin --role admin
  python -m scripts.manage_users create --username agent1 --role agent
  python -m scripts.manage_users create --username client1 --role customer --customer-id CUST-12232
"""
import argparse
import getpass
import os
from auth_store import AuthError, create_user, init_auth
from ticket_store import DEFAULT_DB, init_db


def main():
    parser = argparse.ArgumentParser(description='Create a QuickCart local demo account.')
    sub = parser.add_subparsers(dest='cmd', required=True)
    create = sub.add_parser('create')
    create.add_argument('--username', required=True)
    create.add_argument('--role', required=True, choices=('customer','agent','admin'))
    create.add_argument('--customer-id', help='Required for customer role. Use a customer_id from data/orders_clean.csv.')
    args = parser.parse_args()
    if args.cmd == 'create':
        first = getpass.getpass('Password (12+ characters): ')
        second = getpass.getpass('Confirm password: ')
        if first != second:
            raise SystemExit('Passwords do not match.')
        init_db(DEFAULT_DB)
        init_auth(DEFAULT_DB)
        try:
            uid = create_user(DEFAULT_DB, username=args.username, password=first, role=args.role,
                              customer_id=args.customer_id)
        except AuthError as exc:
            raise SystemExit(f'Cannot create user: {exc}') from exc
        print(f'Created {args.role} account {args.username} (internal ID {uid}).')


if __name__ == '__main__':
    main()
