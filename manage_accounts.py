"""Local account recovery. Requires access to the private database on this computer.
This is not exposed over HTTP. Stop the server and back up the database first.
"""
from __future__ import annotations
import argparse,getpass,os
from pathlib import Path
from peac_core import APIError
from peac_community import CommunityService
from portal_auth import hash_password


def recover(service,username,password):
    encoded=hash_password(password)
    with service.store.transaction() as db:
        row=db.execute('SELECT id FROM portal_users WHERE username=? AND active=1',(username.strip().lower(),)).fetchone()
        if not row: raise APIError('Active account not found. No password was changed.',404)
        db.execute('UPDATE portal_users SET password_hash=? WHERE id=?',(encoded,row['id']))
        db.execute('DELETE FROM portal_sessions WHERE user_id=?',(row['id'],))
        service.auth.audit(db,'local-recovery','account.password_recovered',row['id'])
    return {'ok':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['reset-password','revoke-sessions'])
    parser.add_argument('--db',default=os.getenv('PEAC_DB_PATH',str(Path(__file__).resolve().parent/'data'/'peac.sqlite3')))
    parser.add_argument('--username')
    args=parser.parse_args()
    if not Path(args.db).is_file(): parser.error('Database not found. Use the correct --db path. Nothing was created.')
    service=CommunityService(Path(args.db))
    if args.command=='revoke-sessions':
        if input('Type REVOKE SESSIONS to sign out every account: ').strip()!='REVOKE SESSIONS':
            raise SystemExit('Cancelled. No sessions changed.')
        with service.store.transaction() as db:
            db.execute('DELETE FROM portal_sessions')
            service.auth.audit(db,'local-recovery','all_sessions.revoked')
        print('All sessions were revoked. Accounts and school records were kept.')
    else:
        if not args.username: parser.error('--username is required.')
        password=getpass.getpass('New password (12+ characters, hidden): ')
        if password!=getpass.getpass('Repeat password: '): raise SystemExit('Passwords did not match. Nothing changed.')
        try: recover(service,args.username,password)
        except APIError as e: raise SystemExit(str(e))
        print('Password changed. This account must sign in again.')

if __name__=='__main__':main()
