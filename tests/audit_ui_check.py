"""Public/private regression checks. Only disposable local data and intercepted failure responses."""
from __future__ import annotations
import json, os, sys, tempfile, subprocess, time, urllib.request
from pathlib import Path
from datetime import date, timedelta
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from peac_community import CommunityService
from peac_people import save_person
OUT=ROOT/'test-artifacts';OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:5011'
PASSWORD='Disposable-audit-password-12345'

def login(page):
    page.goto(BASE+'/login',wait_until='networkidle')
    page.locator('#loginForm [name=username]').fill('peacadmin')
    page.locator('#loginForm [name=password]').fill(PASSWORD)
    page.locator('#loginButton').click();page.wait_for_url('**/console')
    expect(page.locator('body')).to_have_attribute('data-role','admin')

def no_emoji(page):
    bad=page.evaluate('''() => {
      const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
      const bad=[];let n;
      while(n=walker.nextNode()){
        if(n.parentElement.closest('script,style,textarea,svg'))continue;
        if(/\\p{Extended_Pictographic}/u.test(n.data))bad.push(n.data.slice(0,100));
      }
      return bad;
    }''')
    assert not bad,bad
    assert page.locator('.peac-icon').count()>0

def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),page.viewport_size

def fill_lunch(page):
    expect(page.locator('#lunchFields')).to_be_enabled()
    page.locator('[name=preferred_name]').fill('Local Test')
    page.locator('[name=email]').fill('local@example.invalid')
    page.locator('#lunchDate').fill(page.locator('#lunchDate').get_attribute('min'))
    page.locator('[name=lunch_period][value="Lunch A"]').check()
    page.locator('[name=details]').fill('Talk during lunch')
    page.locator('[name=consent]').check()

def smoke(browser,engine,width,height):
    context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<900,reduced_motion='reduce')
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    try:
        page.goto(BASE,wait_until='networkidle');no_emoji(page);no_overflow(page)
        page.locator('#feedback').scroll_into_view_if_needed();page.screenshot(path=str(OUT/f'audit-public-{engine}-{width}.png'),animations='disabled')
        login(page)
        for name in ['home','overview','reports','people','lunch','contacts','newsletter','website','assistant','feedback','settings']:
            page.evaluate('(name)=>location.hash=name',name)
            target='#dashboardView' if name=='overview' else '#reportsSection' if name=='reports' else f'[data-portal-panel="{name}"]'
            expect(page.locator(target)).to_be_visible();page.wait_for_load_state('networkidle')
            no_emoji(page);no_overflow(page)
        page.evaluate("location.hash='people'")
        expect(page.locator('[data-portal-panel=people]')).to_be_visible()
        page.locator('[data-entry-mode=rapid]').focus();page.keyboard.press('ArrowRight')
        expect(page.locator('[data-entry-mode=roster]')).to_be_focused()
        expect(page.locator('[data-entry-panel=roster]')).to_be_visible()
        week=(date.today()-timedelta(days=date.today().weekday())).isoformat()
        page.locator('#rosterWeek').fill(week);page.locator('#rosterWeek').dispatch_event('change')
        page.locator('#rosterGrade').select_option('8')
        field=page.locator('#rosterGrid label').filter(has_text='Audit Alpha').locator('input')
        expect(field).to_be_visible();field.fill('');page.locator('#saveRoster').click();expect(page.locator('#rosterStatus')).to_contain_text('Check the total');field.fill('9')
        page.locator('#rosterSearch').fill('Beta');expect(page.locator('#rosterChanged')).to_have_text('1')
        page.locator('#rosterSearch').fill('');expect(field).to_have_value('9')
        page.locator('#rosterGrade').select_option('7');page.locator('#rosterGrade').select_option('8');expect(field).to_have_value('9')
        # Search must not drop the changed Alpha row when Save is clicked on the filtered view.
        page.locator('#rosterSearch').fill('Beta');saved=[]
        def save_route(route):
            saved.extend(route.request.post_data_json['records'])
            route.fulfill(json={'ok':True,'saved':len(saved),'created':0,'updated':len(saved)})
        page.route('**/api/portal/compliment-people/batch',save_route)
        page.locator('#saveRoster').click();expect(page.locator('#rosterStatus')).to_contain_text('Saved 1')
        assert saved[0]['name']=='Audit Alpha' and saved[0]['count']==9,saved
        page.unroute('**/api/portal/compliment-people/batch',save_route)
        page.screenshot(path=str(OUT/f'audit-console-{engine}-{width}.png'),animations='disabled')
        # Every file offered by the console must download with the current authenticated session.
        for path in ['/counts-template.csv','/people-template.csv','/campaigns-template.csv','/PEAC_Input_Template.xlsx','/PEAC_Weekly_Compliments_Template.xlsx']:
            response=context.request.get(BASE+path);assert response.status==200,(path,response.status)
            assert len(response.body())>5
        assert not errors,errors
        print(f'PASS audit {engine} {width}x{height}: 11 private sections, SVG icons, overflow, keyboard tabs, roster drafts, 5 downloads',flush=True)
    finally:
        page.screenshot(path=str(OUT/f'audit-last-{engine}-{width}.png'),animations='disabled');context.close()

def failure_paths(browser):
    context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    # Invalid persisted data must not lock the form.
    page.add_init_script("sessionStorage.setItem('peac.lunch.pending','[]');sessionStorage.setItem('peac.pending','null');")
    page.goto(BASE,wait_until='networkidle');fill_lunch(page);keys=[]
    def broken(route):keys.append(route.request.headers['idempotency-key']);route.fulfill(status=200,content_type='text/html',body='not a JSON receipt')
    page.route('**/api/public/lunch',broken);page.locator('#submitLunchBtn').click()
    expect(page.locator('#lunchStatus')).to_contain_text('could not be confirmed',timeout=15000)
    expect(page.locator('#lunchSuccess')).not_to_be_visible();expect(page.locator('[name=preferred_name]')).to_have_value('Local Test')
    assert len(keys)==3 and len(set(keys))==1,keys
    page.unroute('**/api/public/lunch',broken)
    def recover(route):
        assert route.request.headers['idempotency-key']==keys[0]
        route.fulfill(json={'ok':True,'reference':'LB-ABC123','message':'Confirmed test receipt'})
    page.route('**/api/public/lunch',recover);page.locator('#submitLunchBtn').click();expect(page.locator('#lunchSuccess')).to_be_visible()
    page.unroute('**/api/public/lunch',recover)
    # Input typed while a successful feedback response arrives must survive.
    page.locator('#publicFeedbackText').fill('Original feedback')
    def feedback(route):
        page.locator('#publicFeedbackText').fill('New unsent draft')
        route.fulfill(json={'ok':True,'id':'local-public-feedback'})
    page.route('**/api/public/feedback',feedback);page.locator('#publicFeedbackBtn').click()
    expect(page.locator('#publicFeedbackStatus')).to_contain_text('saved privately');expect(page.locator('#publicFeedbackText')).to_have_value('New unsent draft')
    page.unroute('**/api/public/feedback',feedback)
    # Configuration connection errors offer a usable retry rather than a permanent disabled form.
    page.route('**/api/public/config',lambda route:route.abort())
    page.reload(wait_until='networkidle');expect(page.locator('#retryPublicConfig')).to_be_visible()
    page.unroute('**/api/public/config');page.locator('#retryPublicConfig').click();expect(page.locator('#lunchFields')).to_be_enabled()
    # Published text is never interpreted as markup, including in the reader.
    title='<img src=x onerror=alert(1)>'
    page.route('**/api/public/newsletter',lambda route:route.fulfill(json={'items':[{'title':title,'body':'<script>throw Error(1)</script>','published_at':'2026-10-22T10:00:00Z'}]}))
    page.reload(wait_until='networkidle');page.locator('.newsletter-read').first.click()
    expect(page.locator('#newsletterPostTitle')).to_have_text(title);assert page.locator('#newsletterPostTitle img').count()==0
    page.keyboard.press('Escape');expect(page.locator('.newsletter-read').first).to_be_focused();no_emoji(page)
    page.unroute('**/api/public/newsletter')
    # Failed login responses must not be treated as successful authentication.
    page.goto(BASE+'/login',wait_until='networkidle')
    page.route('**/api/auth/login',lambda route:route.fulfill(status=200,content_type='text/html',body='not JSON'))
    page.locator('#loginForm [name=username]').fill('peacadmin');page.locator('#loginForm [name=password]').fill(PASSWORD);page.locator('#loginButton').click()
    expect(page.locator('#loginStatus')).to_contain_text('could not be confirmed');assert page.url.endswith('/login')
    page.unroute('**/api/auth/login');page.locator('#loginButton').click();page.wait_for_url('**/console');expect(page.locator('body')).to_have_attribute('data-role','admin')
    page.evaluate("location.hash='feedback'");expect(page.locator('#privateFeedbackText')).to_be_visible();page.locator('#privateFeedbackText').fill('Original private feedback')
    def private_feedback(route):
        if route.request.method=='POST':
            page.locator('#privateFeedbackText').fill('New private draft');route.fulfill(json={'ok':True,'id':'local-private-feedback'})
        else:route.continue_()
    page.route('**/api/portal/site-feedback',private_feedback);page.locator('#privateFeedbackBtn').click();expect(page.locator('#privateFeedbackStatus')).to_contain_text('saved privately');expect(page.locator('#privateFeedbackText')).to_have_value('New private draft')
    page.unroute('**/api/portal/site-feedback',private_feedback)
    assert not errors,errors
    print('PASS failure paths: malformed replies, stable retry key, corrupt storage, draft preservation, config retry, newsletter text safety, login recovery',flush=True)
    context.close()

def full_breathing_round(browser):
    context=browser.new_context(reduced_motion='reduce');page=context.new_page();page.goto(BASE,wait_until='networkidle');page.clock.install()
    page.locator('[data-open-breathing]').first.click();page.locator('.breathing-main').click();expect(page.locator('#breathingDialog')).to_have_attribute('data-breathing-state','running')
    page.clock.fast_forward(49000);expect(page.locator('#breathingDialog')).to_have_attribute('data-breathing-state','complete')
    expect(page.locator('.breathing-main')).to_have_text('Redo 3 rounds');page.locator('.breathing-main').click();expect(page.locator('#breathingDialog')).to_have_attribute('data-breathing-state','running')
    page.keyboard.press('Escape');expect(page.locator('#breathingDialog')).not_to_be_visible()
    print('PASS full breathing session: three rounds, completion, replay and Escape',flush=True);context.close()

def main():
    if os.getenv('PEAC_TEST_URL'):raise SystemExit('This suite must never run against a live site.')
    with tempfile.TemporaryDirectory(prefix='peac-audit-') as temp:
        db=Path(temp)/'data.sqlite3';s=CommunityService(db);user=s.auth.create_user({'username':'peacadmin','display_name':'Audit Admin','password':PASSWORD,'role':'admin'},'test')
        week=(date.today()-timedelta(days=date.today().weekday())).isoformat()
        for i,name in enumerate(['Audit Alpha','Audit Beta']):save_person(s,{'name':name,'week_start':week,'grade':'8','count':2},f'audit-seed-person-{i}-12345',user)
        env={**os.environ,'PEAC_DEPLOY_MODE':'','PEAC_HOST':'127.0.0.1','PEAC_PORT':'5011','PEAC_DB_PATH':str(db),'PEAC_FORCE_LUNCH_OPEN':'1'}
        with (OUT/'audit-server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'peac.py','--local-server'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(60):
                    try:
                        with urllib.request.urlopen(BASE+'/api/health',timeout=1):break
                    except OSError:time.sleep(.25)
                else:raise RuntimeError('Isolated server failed to start')
                with sync_playwright() as p:
                    for engine in ['chromium','webkit']:
                        with getattr(p,engine).launch() as browser:
                            for width,height in [(1440,1000),(390,844),(320,700),(844,390)]:smoke(browser,engine,width,height)
                            failure_paths(browser)
                            if engine=='chromium':full_breathing_round(browser)
            finally:
                server.terminate()
                try:server.wait(timeout=8)
                except subprocess.TimeoutExpired:server.kill();server.wait()

if __name__=='__main__':main()
