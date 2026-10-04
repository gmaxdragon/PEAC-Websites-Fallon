"""PEAC Community v3. Public homepage + authenticated team console.
Local preview by default; explicit hosted mode is available for approved HTTPS deployment. Python 3.10+.
"""
from __future__ import annotations
import argparse
import getpass
import os
import sys
from pathlib import Path
from peac_core import APIError
from peac_community import CommunityService
from portal_server import HEADERS, PortalRouter, make_server
BASE_DIR=Path(__file__).resolve().parent


def _bootstrap_hosted_admin(service):
    if os.getenv("PEAC_DEPLOY_MODE","").lower()!="hosted" or service.auth.has_users():
        return
    username=os.getenv("PEAC_ADMIN_USERNAME","").strip()
    display=os.getenv("PEAC_ADMIN_DISPLAY_NAME","").strip() or username
    password=os.getenv("PEAC_ADMIN_PASSWORD","")
    if not username or not password:
        raise RuntimeError("Hosted first start requires PEAC_ADMIN_USERNAME and PEAC_ADMIN_PASSWORD environment variables.")
    service.auth.create_user({"username":username,"display_name":display,"password":password,"role":"admin"},"hosted-bootstrap")


def create_app(db_path=None,service=None):
    from flask import Flask,request
    from werkzeug.exceptions import HTTPException
    from werkzeug.middleware.proxy_fix import ProxyFix
    app=Flask(__name__,static_folder=None)
    app.config["MAX_CONTENT_LENGTH"]=3_000_000
    instance=service or CommunityService(Path(db_path or os.getenv("PEAC_DB_PATH",BASE_DIR/"data"/"peac.sqlite3")))
    _bootstrap_hosted_admin(instance)
    if os.getenv("PEAC_DEPLOY_MODE","").lower()=="hosted":
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
    app.extensions["peac"]=instance
    router=PortalRouter(instance,BASE_DIR)
    @app.route("/",defaults={"path":""},methods=["GET","POST","PUT","DELETE","OPTIONS"])
    @app.route("/<path:path>",methods=["GET","POST","PUT","DELETE","OPTIONS"])
    def route(path):
        limit=3_000_000 if request.path.startswith("/api/import/") else 65536
        if (request.content_length or 0)>limit: raise APIError("Request too large.",413)
        status,data,mime,extra=router.handle(request.method,request.path,request.headers,request.remote_addr or "",request.scheme,request.get_data())
        return app.response_class(data,status=status,headers={**HEADERS,**extra},content_type=mime)
    @app.errorhandler(APIError)
    def api_error(e):
        status,data,mime,extra=router.json_response({"error":str(e)},e.status)
        return app.response_class(data,status=status,headers=HEADERS,content_type=mime)
    @app.errorhandler(HTTPException)
    def http_error(e):
        status,data,mime,extra=router.json_response({"error":e.description},e.code)
        return app.response_class(data,status=status,headers=HEADERS,content_type=mime)
    @app.errorhandler(Exception)
    def error(e):
        app.logger.exception("PEAC request failed")
        status,data,mime,extra=router.json_response({"error":"Server error. A successful save has not been confirmed."},500)
        return app.response_class(data,status=status,headers=HEADERS,content_type=mime)
    return app


def first_admin(service):
    if service.auth.has_users(): return
    if not sys.stdin.isatty():
        raise SystemExit("Create an admin in a terminal first: python peac.py --setup-admin")
    print("First start: create your private administrator account. No default password is included.")
    username=input("Username (3+ characters): ").strip()
    display=input("Display name for the console: ").strip() or username
    password=getpass.getpass("Password (12+ characters, hidden): ")
    if password!=getpass.getpass("Repeat password: "): raise SystemExit("Passwords did not match. Run again; no account was created.")
    service.auth.create_user({"username":username,"display_name":display,"password":password,"role":"admin"})
    print("Administrator created. Store your password privately.")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-server",action="store_true")
    parser.add_argument("--setup-admin",action="store_true")
    parser.add_argument("--port",type=int,default=int(os.getenv("PEAC_PORT","5000")))
    parser.add_argument("--db",default=os.getenv("PEAC_DB_PATH",str(BASE_DIR/"data"/"peac.sqlite3")))
    args=parser.parse_args()
    hosted=os.getenv("PEAC_DEPLOY_MODE","").lower()=="hosted"
    host=os.getenv("PEAC_HOST","0.0.0.0" if hosted else "127.0.0.1")
    if not hosted and host not in {"127.0.0.1","localhost"}: parser.error("Local preview must bind to localhost. Use PEAC_DEPLOY_MODE=hosted for an approved HTTPS deployment.")
    if not 1<=args.port<=65535: parser.error("Choose a port between 1 and 65535.")
    service=CommunityService(Path(args.db),use_ml=os.getenv("PEAC_ENABLE_ML","0")=="1")
    try:
        if hosted: _bootstrap_hosted_admin(service)
        else: first_admin(service)
    except (APIError,RuntimeError) as e: raise SystemExit(str(e))
    if args.setup_admin: return
    print(f"Public preview: http://{host}:{args.port}/",flush=True)
    print(f"Private console: http://{host}:{args.port}/console",flush=True)
    print(f"One database: {service.store.path}. {'Hosted mode.' if hosted else 'Local preview.'} Stop with Ctrl+C.",flush=True)
    if not args.local_server:
        try: app=create_app(service=service)
        except ModuleNotFoundError as e:
            if e.name not in {"flask","werkzeug","blinker"}: raise
            print("Using the included local server. Flask is optional.",flush=True)
        else:
            app.run(host=host,port=args.port,debug=False,use_reloader=False);return
    server=make_server(service,BASE_DIR,host,args.port)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=="__main__": main()
