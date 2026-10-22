"""Read-only browser regression checks against an isolated local PEAC database."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from peac_community import CommunityService

OUT = ROOT / 'test-artifacts'
OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:5000'


def check_fade(page):
    """Check the rendered cascade, not just the presence of a CSS string."""
    state = page.locator('#programs').evaluate('''e => {
        const s = getComputedStyle(e), b = getComputedStyle(e, '::before');
        const heading = e.querySelector('.future-heading');
        return {background: s.backgroundColor, border: s.borderTopWidth,
            shadow: s.boxShadow, mask: b.maskImage || b.webkitMaskImage,
            pointerEvents: b.pointerEvents, layer: b.zIndex,
            padding: parseFloat(s.paddingTop), opacity: getComputedStyle(heading).opacity,
            headingTop: heading.getBoundingClientRect().top - e.getBoundingClientRect().top};
    }''')
    assert state['background'] == 'rgba(0, 0, 0, 0)', state
    assert state['border'] == '0px' and state['shadow'] == 'none', state
    assert 'linear-gradient' in state['mask'], state
    assert state['pointerEvents'] == 'none' and state['layer'] == '-1', state
    assert state['opacity'] == '1' and state['padding'] >= 120, state
    assert state['headingTop'] >= state['padding'] - 1, state
    return state


def run_checks():
    report = []
    with tempfile.TemporaryDirectory(prefix='peac-ui-') as temp:
        database = Path(temp) / 'peac.sqlite3'
        # Seed a disposable test account in this temporary database only.
        service = CommunityService(database)
        service.auth.create_user({'username': 'ui-test-admin', 'display_name': 'UI Test',
                                  'password': 'UI-test-only-password-12345', 'role': 'admin'}, 'test')
        env = {**os.environ, 'PEAC_DEPLOY_MODE': '', 'PEAC_HOST': '127.0.0.1',
               'PEAC_PORT': '5000', 'PEAC_DB_PATH': str(database)}
        with (OUT / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, 'peac.py', '--local-server'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(60):
                    if server.poll() is not None:
                        raise RuntimeError('Local server exited: ' + (OUT / 'server.log').read_text())
                    try:
                        with urllib.request.urlopen(BASE + '/api/health', timeout=1) as response:
                            assert response.status == 200
                        break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError('Local server did not become healthy')
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    for width in (1440, 1024, 768, 390, 320):
                        page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        response = page.goto(BASE, wait_until='networkidle')
                        page.screenshot(path=str(OUT / f'home-{width}.png'), full_page=True, animations='disabled')
                        page.locator('#programs').screenshot(path=str(OUT / f'coming-soon-{width}.png'), animations='disabled')
                        assert response.status == 200
                        expect(page.locator('body')).to_have_attribute('data-layout-revision', '2026.10.21.2')
                        expect(page.locator('.future-card')).to_have_count(6)
                        expect(page.locator('.symbol-trail')).to_have_count(7)
                        fade = check_fade(page)
                        assert page.locator('.symbol-trail').evaluate_all('(els) => els.every(e => e.getAttribute("aria-hidden") === "true" && getComputedStyle(e).pointerEvents === "none")')
                        overflow = page.evaluate('''() => [...document.querySelectorAll('body *')].filter(e => {
                            const r = e.getBoundingClientRect();
                            return r.width && r.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed';
                        }).map(e => ({tag:e.tagName, cls:e.className, right:e.getBoundingClientRect().right})).slice(0,12)''')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), f'Horizontal overflow at {width}: {overflow}'
                        assert page.locator('.symbol-trail svg').first.evaluate('(e) => getComputedStyle(e).animationName') == 'none'
                        ids = page.locator('[id]').evaluate_all('(els) => els.map(e => e.id)')
                        assert len(ids) == len(set(ids)), 'Duplicate HTML ids'
                        assert page.locator('a[href^="#"]').evaluate_all('(els) => els.every(e => !!document.getElementById(e.hash.slice(1)))'), 'Broken page anchor'
                        assert page.evaluate('''() => {
                            const rects = [...document.querySelectorAll('input:not([type=hidden]), textarea, select, button')]
                                .filter(e => e.getClientRects().length).map(e => e.getBoundingClientRect());
                            return [...document.querySelectorAll('.symbol-trail svg, .doodle-rail svg')]
                                .filter(e => e.getClientRects().length).every(e => {
                                    const a = e.getBoundingClientRect();
                                    return rects.every(b => a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
                                });
                        }'''), f'Decoration overlaps controls at {width}'
                        trigger = page.get_by_role('button', name='Box breathing', exact=True)
                        trigger.click()
                        expect(page.locator('#breathingDialog')).to_be_visible()
                        assert page.locator('#breathingDialog').evaluate('(e) => e.open')
                        page.screenshot(path=str(OUT / f'breathing-{width}.png'), animations='disabled')
                        page.keyboard.press('Escape')
                        expect(page.locator('#breathingDialog')).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        assert not errors, errors
                        report.append({'width': width, 'status': 'passed', 'fade': fade, 'javascript_errors': errors})
                        print(f'PASS {width}px: background fade, opaque content, six feature areas, distributed symbols, no overflow, breathing dialog and focus return', flush=True)
                        page.close()
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.goto(BASE, wait_until='networkidle')
                    page.locator('#motionToggle').click()
                    expect(page.locator('html')).to_have_attribute('data-motion', 'off')
                    assert page.locator('.symbol-trail svg').first.evaluate('(e) => getComputedStyle(e).animationName') == 'none'
                    check_fade(page)
                    print('PASS manual reduced-motion toggle; static fade preserved', flush=True)
                    browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                (OUT / 'results.json').write_text(json.dumps(report, indent=2))

if __name__ == '__main__':
    run_checks()
