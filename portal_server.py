"""Shared authenticated router for local preview and explicit hosted PEAC deployments."""
from __future__ import annotations
import hmac
import json
import os
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from peac_core import APIError, export_csv
from portal_auth import COOKIE, SESSION_SECONDS, require_admin

LOOPBACK={"127.0.0.1","localhost","::1"}
HOSTED=os.getenv("PEAC_DEPLOY_MODE","").lower()=="hosted"

def configured_hosts():
    values={h.strip().lower() for h in os.getenv("PEAC_ALLOWED_HOSTS","").split(",") if h.strip()}
    railway=os.getenv("RAILWAY_PUBLIC_DOMAIN","").strip().lower()
    if railway: values.add(railway)
    return values

HEADERS={
    "X-Content-Type-Options":"nosniff", "Referrer-Policy":"no-referrer", "X-Frame-Options":"DENY",
    "Cache-Control":"no-store", "Permissions-Policy":"camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}
PUBLIC_FILES={"/":"public.html","/index.html":"public.html","/public.html":"public.html","/login":"login.html",
              "/community.css":"community.css","/public.js":"public.js","/login.js":"login.js","/ribbon.svg":"ribbon.svg"}
PRIVATE_FILES={"/console":"console.html","/console.html":"console.html","/style.css":"style.css","/console.css":"console.css",
               "/script.js":"script.js","/charts.js":"charts.js","/auth.js":"auth.js","/console.js":"console.js",
               "/counts-template.csv":"counts-template.csv","/people-template.csv":"people-template.csv","/campaigns-template.csv":"campaigns-template.csv",
               "/PEAC_Input_Template.xlsx":"templates/PEAC_Input_Template.xlsx",
               "/PEAC_Weekly_Compliments_Template.xlsx":"templates/PEAC_Weekly_Compliments_Template.xlsx"}


def guard(method,host,origin,marker,peer,scheme="http"):
    try: hostname=(urlsplit("//"+host).hostname or "").lower()
    except ValueError: raise APIError("Invalid host.")
    if HOSTED:
        allowed=configured_hosts()
        if not allowed or hostname not in allowed:
            raise APIError("This hostname is not configured for PEAC.",403)
        if scheme != "https":
            raise APIError("Hosted PEAC requires HTTPS.",403)
    else:
        if hostname not in LOOPBACK or peer not in LOOPBACK:
            raise APIError("Local preview only. Use the hosted deployment configuration for internet access.",403)
    expected=f"{scheme}://{host}"
    if origin is not None and origin!=expected:
        raise APIError("Cross-origin access is not allowed.",403)
    if method not in {"GET","HEAD","OPTIONS"}:
        if marker!="1" or origin!=expected:
            raise APIError("Open this form from the PEAC site. Same-origin writes are required.",403)


class PortalRouter:
    def __init__(self,service,base_dir):
        self.service,self.base_dir=service,Path(base_dir)

    @staticmethod
    def json_response(value,status=200,extra=None):
        return status,json.dumps(value,allow_nan=False).encode(),"application/json; charset=utf-8",extra or {}

    def handle(self,method,path,headers,peer="127.0.0.1",scheme="http",body=b""):
        # headers is a case-insensitive mapping in both transports.
        path=urlsplit(path).path
        verb="GET" if method=="HEAD" else method
        # Minimal health check is safe before host/origin enforcement and lets hosted
        # platforms probe the service over their internal route.
        if verb=="GET" and path=="/api/health":
            return self.json_response({"ok":True,"service":"PEAC Community","mode":"hosted" if HOSTED else "local_preview"})
        guard(method,headers.get("Host",""),headers.get("Origin"),headers.get("X-PEAC-Client"),peer,scheme)
        if verb=="OPTIONS": return 204,b"","text/plain",{}
        if verb=="GET" and path in PUBLIC_FILES:
            return self.asset(PUBLIC_FILES[path])
        if verb=="GET" and path=="/api/public/config": return self.json_response(self.service.public_content())
        payload=None
        if verb in {"POST","PUT","DELETE"}:
            if len(body)>(3_000_000 if path.startswith("/api/import/") else 65536): raise APIError("Request too large.",413)
            if headers.get("Content-Type","").split(";")[0].strip().lower()!="application/json": raise APIError("Send application/json.",415)
            try: payload=json.loads(body,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            except (ValueError,UnicodeDecodeError): raise APIError("Malformed JSON body.")
        if path=="/api/auth/login" and verb=="POST":
            token,result=self.service.auth.login(payload,peer)
            # Local HTTP only; hosted deployments must additionally enforce Secure cookies.
            cookie=f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}" + ("; Secure" if HOSTED else "")
            return self.json_response(result,200,{"Set-Cookie":cookie})
        if path=="/api/auth/signup" and verb=="POST":
            return self.json_response(self.service.auth.request_signup(payload,peer),201)
        if path=="/api/public/feedback" and verb=="POST":
            return self.json_response(self.service.save_feedback(payload,"public","public"),201)
        if path=="/api/public/lunch" and verb=="POST":
            result=self.service.submit_lunch(payload,headers.get("Idempotency-Key",""),peer)
            return self.json_response(result,200 if result.get("replayed") else 201)
        session=self.service.auth.session(headers.get("Cookie",""))
        if path=="/api/auth/session" and verb=="GET":
            return self.json_response(session or {"user":None,"csrf":None})
        if not session:
            if path in {"/console","/console.html"}: return 303,b"","text/plain",{"Location":"/login"}
            raise APIError("Sign in to the private PEAC console.",401)
        user=session["user"]
        if verb not in {"GET","HEAD","OPTIONS"}:
            if not hmac.compare_digest(session["csrf"].encode(),headers.get("X-CSRF-Token","").encode()):
                raise APIError("Your security token expired. Sign in again before saving.",403)
        if path=="/api/auth/logout" and verb=="POST":
            self.service.auth.logout(headers.get("Cookie",""))
            return self.json_response({"ok":True},200,{"Set-Cookie":f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" + ("; Secure" if HOSTED else "")})
        if verb=="GET" and path in PRIVATE_FILES: return self.asset(PRIVATE_FILES[path])
        if path=="/api/portal/notifications" and verb=="GET": return self.json_response(self.service.notifications(user))
        if path=="/api/portal/notifications/read" and verb=="POST": return self.json_response(self.service.mark_notifications_read(user))
        if path=="/api/portal/site-feedback" and verb=="GET": return self.json_response(self.service.feedback_items(user))
        if path=="/api/portal/site-feedback" and verb=="POST": return self.json_response(self.service.save_feedback(payload,"private",user["id"]),201)
        if path=="/api/backup.sqlite3" and verb=="GET":
            require_admin(user)
            from peac_backup import backup_bytes
            return 200,backup_bytes(self.service.store),"application/octet-stream",{"Content-Disposition":"attachment; filename=peac-private-backup.sqlite3"}
        if path=="/api/export.csv" and verb=="GET":
            return 200,export_csv(self.service.store.snapshot()).encode(),"text/csv; charset=utf-8",{"Content-Disposition":"attachment; filename=peac-counts.csv"}
        m=re.fullmatch(r"/api/portal/mail/([a-f0-9-]{36})/draft.eml",path)
        if m and verb=="GET":
            from peac_mail import get_job,safe_message
            return 200,safe_message(get_job(self.service,m[1])).as_bytes(),"message/rfc822",{"Content-Disposition":"attachment; filename=peac-notification-draft.eml"}
        result,status=self.service.private_dispatch(verb,path,payload,headers.get("Idempotency-Key",""),user)
        return self.json_response(result,status)

    def asset(self,filename):
        file=self.base_dir/filename
        if not file.is_file(): raise APIError("Asset not found.",404)
        mime=mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in {"application/javascript","image/svg+xml"}: mime+="; charset=utf-8"
        return 200,file.read_bytes(),mime,{}


def make_server(service,base_dir,host="127.0.0.1",port=5000):
    if host not in {"localhost","127.0.0.1"}: raise ValueError("Local server binds only to localhost.")
    if not hasattr(service,"auth") or not hasattr(service,"private_dispatch"):
        raise TypeError("Use CommunityService: this server never exposes the unauthenticated legacy Service.")
    router=PortalRouter(service,base_dir)
    class Handler(BaseHTTPRequestHandler):
        protocol_version="HTTP/1.0"
        def setup(self):
            super().setup();self.connection.settimeout(15)
        def handle_request(self):
            try:
                body=b""
                if self.command in {"POST","PUT","DELETE"}:
                    if self.headers.get("Transfer-Encoding"): raise APIError("Chunked bodies are not supported.")
                    try: length=int(self.headers.get("Content-Length","0"))
                    except ValueError: raise APIError("Invalid body length.")
                    limit=3_000_000 if urlsplit(self.path).path.startswith("/api/import/") else 65536
                    if not 0<=length<=limit: raise APIError("Request too large.",413)
                    body=self.rfile.read(length)
                result=router.handle(self.command,self.path,self.headers,self.client_address[0],body=body)
            except APIError as e: result=router.json_response({"error":str(e)},e.status)
            except (ConnectionError,TimeoutError): return
            except Exception:
                import traceback;traceback.print_exc()
                result=router.json_response({"error":"Server error. A successful save has not been confirmed."},500)
            status,data,mime,extra=result
            try:
                self.send_response(status)
                for k,v in {**HEADERS,**extra,"Content-Type":mime,"Content-Length":str(len(data))}.items(): self.send_header(k,v)
                self.end_headers()
                if self.command!="HEAD": self.wfile.write(data)
            except (ConnectionError,TimeoutError): pass
        do_GET=do_HEAD=do_POST=do_PUT=do_DELETE=do_OPTIONS=handle_request
        def log_message(self,*args): pass
    server=ThreadingHTTPServer((host,port),Handler);server.daemon_threads=True
    return server
