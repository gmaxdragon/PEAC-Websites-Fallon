"""Regression tests use temporary databases only, never production data."""
from __future__ import annotations
import json, tempfile, unittest, os, csv, io, zipfile
from pathlib import Path
from datetime import date
from unittest.mock import patch
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from peac_community import CommunityService
from peac_core import APIError
from portal_server import PortalRouter, PUBLIC_FILES, PRIVATE_FILES
from peac_people import save_person, list_people

ROOT=Path(__file__).resolve().parent
class HTMLInventory(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.links=[];self.assets=[];self.icons=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('id'):self.ids.append(a['id'])
        if tag=='a' and a.get('href'):self.links.append(a['href'])
        if tag in ('script','link','img'):
            v=a.get('src',a.get('href',''))
            if v.startswith('/'):self.assets.append(v.split('?')[0])
        if tag=='use':self.icons.append(a.get('href',''))

class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=CommunityService(Path(self.tmp.name)/'test.sqlite3',today_fn=lambda:date(2026,10,22))
        self.admin=self.service.auth.create_user({'username':'audit-admin','display_name':'Audit','password':'Audit-test-password-12345','role':'admin'},'test')
        self.member=self.service.auth.create_user({'username':'audit-member','display_name':'Member','password':'Audit-test-password-12345','role':'coordinator'},'test')
        self.router=PortalRouter(self.service,ROOT)
        self.hosted=patch('portal_server.HOSTED',False);self.hosted.start()
        self.lunch=patch.dict(os.environ,{'PEAC_FORCE_LUNCH_OPEN':'1'});self.lunch.start()
        self.base={'Host':'localhost'}
        self.write={**self.base,'Origin':'http://localhost','X-PEAC-Client':'1','Content-Type':'application/json'}
    def tearDown(self):self.lunch.stop();self.hosted.stop();self.tmp.cleanup()
    def call(self,method,path,payload=None,headers=None,peer='127.0.0.1'):
        h={**(self.base if method in ('GET','HEAD') else self.write),**(headers or {})}
        try:
            status,data,mime,extra=self.router.handle(method,path,h,peer,'http',b'' if payload is None else json.dumps(payload).encode())
            return status,(json.loads(data) if mime.startswith('application/json') and data else data),extra
        except APIError as error:return error.status,{'error':str(error)},{}
    def login(self,username='audit-admin'):
        status,data,extra=self.call('POST','/api/auth/login',{'username':username,'password':'Audit-test-password-12345'})
        self.assertEqual(status,200)
        return {'Cookie':extra['Set-Cookie'].split(';',1)[0],'X-CSRF-Token':data['csrf']}
    def request(self):return {'preferred_name':'Audit Student','email':'audit@example.invalid','grade':'8','preferred_date':'2026-10-22','lunch_period':'Lunch A','support':'custom','details':'Sit together','consent':True,'website':''}
    def test_public_routes_and_assets(self):
        for path in PUBLIC_FILES:
            with self.subTest(path=path):self.assertEqual(self.call('GET',path)[0],200)
    def test_private_routes_require_login(self):
        for path in PRIVATE_FILES:
            with self.subTest(path=path):self.assertIn(self.call('GET',path)[0],(401,303))
    def test_private_assets_exist(self):
        headers=self.login()
        for path in PRIVATE_FILES:
            with self.subTest(path=path):self.assertEqual(self.call('GET',path,headers=headers)[0],200)
    def test_admin_alias_is_protected(self):
        self.assertEqual(self.call('GET','/admin')[2].get('Location'),'/login')
        self.assertEqual(self.call('GET','/admin/',headers=self.login())[0],200)
        self.assertEqual(self.call('GET','/login.html')[0],200)
    def test_feedback_idempotent(self):
        h={'Idempotency-Key':'audit-feedback-key-12345'}
        a=self.call('POST','/api/public/feedback',{'message':'Test feedback'},h)
        b=self.call('POST','/api/public/feedback',{'message':'Test feedback'},h)
        self.assertEqual(a[0],201);self.assertEqual(a[1]['id'],b[1]['id'])
        self.assertEqual(len(self.service.feedback_items(self.admin)),1)
    def test_feedback_retries_do_not_exhaust_quota(self):
        h={'Idempotency-Key':'audit-feedback-repeat-12345'}
        for _ in range(20):self.assertEqual(self.call('POST','/api/public/feedback',{'message':'Same message'},h)[0],201)
        self.assertEqual(len(self.service.feedback_items(self.admin)),1)
    def test_feedback_conflicting_retry(self):
        h={'Idempotency-Key':'audit-feedback-key-12345'}
        self.call('POST','/api/public/feedback',{'message':'First'},h)
        self.assertEqual(self.call('POST','/api/public/feedback',{'message':'Different'},h)[0],409)
    def test_feedback_limits_are_per_visitor(self):
        for _ in range(12):self.assertTrue(self.service.save_feedback({'message':'Test'},'public',rate_key='visitor-a')['ok'])
        with self.assertRaises(APIError) as c:self.service.save_feedback({'message':'Test'},'public',rate_key='visitor-a')
        self.assertEqual(c.exception.status,429)
        self.assertTrue(self.service.save_feedback({'message':'Test'},'public',rate_key='visitor-b')['ok'])
        self.assertTrue(all(x['created_by']=='public' for x in self.service.feedback_items(self.admin)))
    def test_feedback_validation(self):
        for value in ('','x'*1501,42,None):
            with self.subTest(value_type=type(value).__name__):self.assertEqual(self.call('POST','/api/public/feedback',{'message':value})[0],400)
    def test_private_feedback_retry(self):
        h={**self.login(),'Idempotency-Key':'audit-private-feedback-12345'}
        a=self.call('POST','/api/portal/site-feedback',{'message':'Private'},h)
        b=self.call('POST','/api/portal/site-feedback',{'message':'Private'},h)
        self.assertEqual(a[0],201);self.assertEqual(a[1]['id'],b[1]['id'])
    def test_private_feedback_not_public(self):
        self.service.save_feedback({'message':'Private'},'private',self.admin['id'])
        self.assertEqual(self.call('GET','/api/portal/site-feedback')[0],401)
        self.assertEqual(self.call('GET','/api/portal/site-feedback',headers=self.login('audit-member'))[0],403)
    def test_invalid_login_and_session(self):
        self.assertEqual(self.call('POST','/api/auth/login',{'username':'audit-admin','password':'wrong'})[0],401)
        self.assertIsNone(self.call('GET','/api/auth/session')[1]['user'])
    def test_logout_revokes_session(self):
        h=self.login();self.assertEqual(self.call('POST','/api/auth/logout',{},h)[0],200)
        self.assertIsNone(self.call('GET','/api/auth/session',headers=h)[1]['user'])
    def test_csrf_required(self):
        h=self.login();h.pop('X-CSRF-Token')
        self.assertEqual(self.call('POST','/api/portal/site-feedback',{'message':'No token'},h)[0],403)
    def test_same_origin_required(self):
        self.assertEqual(self.call('POST','/api/public/feedback',{'message':'Cross origin'},{'Origin':'http://other.invalid'})[0],403)
        self.assertEqual(self.call('POST','/api/public/feedback',{'message':'No marker'},{'X-PEAC-Client':'0'})[0],403)
    def test_private_permission_boundaries(self):
        h=self.login('audit-member')
        for path in ['/api/backup.sqlite3','/api/portal/users','/api/portal/export','/api/portal/content']:
            with self.subTest(path=path):self.assertEqual(self.call('GET',path,headers=h)[0],403)
    def test_lunch_retry_is_not_duplicate(self):
        h={'Idempotency-Key':'audit-lunch-retry-12345'};a=self.call('POST','/api/public/lunch',self.request(),h);b=self.call('POST','/api/public/lunch',self.request(),h)
        self.assertEqual(a[0],201);self.assertEqual(b[0],200);self.assertEqual(a[1]['reference'],b[1]['reference'])
    def test_lunch_key_conflict(self):
        h={'Idempotency-Key':'audit-lunch-retry-12345'};self.call('POST','/api/public/lunch',self.request(),h)
        payload=self.request();payload['preferred_name']='Different'
        self.assertEqual(self.call('POST','/api/public/lunch',payload,h)[0],409)
    def test_lunch_required_fields(self):
        for field,value in [('consent',False),('lunch_period','Lunch C'),('details',''),('email','invalid'),('preferred_date','2026-10-21'),('preferred_date','2027-10-21'),('grade','9')]:
            with self.subTest(field=field,value=value):
                payload=self.request();payload[field]=value
                self.assertEqual(self.call('POST','/api/public/lunch',payload,{'Idempotency-Key':'audit-lunch-invalid-12345'})[0],400)
    def test_lunch_private_data_not_exposed(self):
        self.call('POST','/api/public/lunch',self.request(),{'Idempotency-Key':'audit-lunch-privacy-12345'})
        self.assertEqual(self.call('GET','/api/portal/lunch')[0],401)
        self.assertNotIn('audit@example.invalid',json.dumps(self.call('GET','/api/public/config')[1]))
    def test_named_totals_whitespace_normalized(self):
        a=save_person(self.service,{'name':'Alex  Doe','week_start':'2026-10-19','grade':'8','count':2},'audit-person-first-12345',self.admin)
        b=save_person(self.service,{'name':'alex doe','week_start':'2026-10-19','grade':'8','count':5},'audit-person-second-12345',self.admin)
        result=list_people(self.service)
        self.assertEqual(result['total_records'],1);self.assertEqual(result['total_compliments'],5)
    def test_named_totals_unicode_normalized(self):
        for i,name in enumerate(['Straße','STRASSE']):save_person(self.service,{'name':name,'week_start':'2026-10-19','grade':'8','count':i+1},f'audit-unicode-person-{i}-12345',self.admin)
        self.assertEqual(list_people(self.service)['total_records'],1)
    def test_named_totals_separate_grade_and_week(self):
        for i,(week,grade) in enumerate([('2026-10-19','8'),('2026-10-12','8'),('2026-10-19','7')]):save_person(self.service,{'name':'Alex','week_start':week,'grade':grade,'count':2},f'audit-person-scope-{i}-12345',self.admin)
        self.assertEqual(list_people(self.service)['total_records'],3)
    def test_csv_templates_are_blank_and_correct(self):
        for name,first in [('counts','date'),('people','week_start'),('campaigns','date')]:
            with self.subTest(name=name):
                rows=list(csv.reader(io.StringIO((ROOT/f'{name}-template.csv').read_text())))
                self.assertEqual(len(rows),1);self.assertEqual(rows[0][0],first)
    def test_workbook_templates_are_valid(self):
        for file in (ROOT/'templates').glob('*.xlsx'):
            with self.subTest(file=file.name),zipfile.ZipFile(file) as z:
                self.assertIsNone(z.testzip());ET.fromstring(z.read('xl/workbook.xml'))
    def test_markup_assets_and_anchors(self):
        inventories={}
        for name in ['public.html','login.html','console.html','changelog.html']:
            p=HTMLInventory();p.feed((ROOT/name).read_text());inventories[name]=p
            self.assertEqual(len(p.ids),len(set(p.ids)),name)
            for asset in p.assets:
                self.assertIn(asset,{**PUBLIC_FILES,**PRIVATE_FILES},(name,asset))
                self.assertTrue((ROOT/({**PUBLIC_FILES,**PRIVATE_FILES}[asset])).exists(),asset)
        public=set(inventories['public.html'].ids)
        for name,p in inventories.items():
            for link in p.links:
                if link.startswith('/#'):self.assertIn(link[2:],public,(name,link))
                elif link.startswith('#') and name!='console.html':self.assertIn(link[1:],p.ids,(name,link))
    def test_all_svg_symbols_exist(self):
        symbols={}
        for filename in ('icons.svg','doodles.svg'):
            tree=ET.fromstring((ROOT/filename).read_text());symbols['/'+filename]={e.attrib['id'] for e in tree.iter() if 'id' in e.attrib}
        for name in ['public.html','console.html','login.html','changelog.html']:
            parser=HTMLInventory();parser.feed((ROOT/name).read_text())
            for href in parser.icons:
                base,frag=href.split('#');base=base.split('?')[0];self.assertIn(frag,symbols[base],(name,href))
    def test_auth_headers(self):
        h=self.login();self.assertIn('Cookie',h);self.assertTrue(h['X-CSRF-Token'])
        status,_,extra=self.call('POST','/api/auth/login',{'username':'audit-admin','password':'Audit-test-password-12345'})
        self.assertIn('HttpOnly',extra['Set-Cookie']);self.assertIn('SameSite=Strict',extra['Set-Cookie'])
    def test_hosted_requires_https(self):
        with patch('portal_server.HOSTED',True),patch.dict(os.environ,{'PEAC_ALLOWED_HOSTS':'localhost'}):
            self.assertEqual(self.call('GET','/')[0],403)
            self.assertEqual(self.call('GET','/api/health')[0],200)
    def test_path_traversal_denied(self):
        for path in ('/../peac.py','/.env','/data/peac.sqlite3','/templates/PEAC_Input_Template.xlsx'):
            with self.subTest(path=path):self.assertNotEqual(self.call('GET',path)[0],200)
    def test_post_body_shape(self):
        for payload in (None,[],['x'],42,'message'):
            with self.subTest(payload=payload):self.assertEqual(self.call('POST','/api/public/feedback',payload)[0],400)

if __name__=='__main__':unittest.main()
