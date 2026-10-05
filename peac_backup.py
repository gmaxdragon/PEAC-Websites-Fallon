"""Consistent SQLite backups, including all internal tables and save receipts.
The live database must stay on the application server, not a cloud-sync folder.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
import tempfile
from pathlib import Path


def backup_bytes(store) -> bytes:
    with tempfile.TemporaryDirectory(prefix='peac-backup-') as temporary:
        target=Path(temporary)/'backup.sqlite3'
        with store.connection() as source:
            destination=sqlite3.connect(target)
            try: source.backup(destination)
            finally: destination.close()
        return target.read_bytes()


def main():
    from peac_core import Store
    parser=argparse.ArgumentParser(description='Create a consistent, private backup of the PEAC database.')
    parser.add_argument('--db',default=str(Path(__file__).resolve().parent/'data'/'peac.sqlite3'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not Path(args.db).is_file(): parser.error('Source database does not exist.')
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        with target.open('xb') as f:
            f.write(backup_bytes(Store(Path(args.db))))
    except FileExistsError: parser.error('Backup target already exists; choose a new name.')
    print(f'Backup saved: {target}. Keep it private.')


if __name__=='__main__': main()
