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
OUT = ROOT / 'test-artifacts'
OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:5000'


def run_checks():
    report = []
    with tempfile.TemporaryDirectory(prefix='peac-ui-') as temp:
        env = {**os.environ, 'PEAC_DEPLOY_MODE': '', 'PEAC_HOST': '127.0.0.1',
               'PEAC_PORT': '5000', 'PEAC_DB_PATH': str(Path(temp) / 'peac.sqlite3')}
        with (OUT / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, 'peac.py', '--local-server'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(60):
                    if server.poll() is not None:
                        raise RuntimeError('Local server exited; see server.log')
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
                        assert response.status == 200
                        expect(page.locator('body')).to_have_attribute('data-layout-revision', '2026.10.21.2')
                        expect(page.locator('.future-card')).to_have_count(6)
                        expect(page.locator('.symbol-trail')).to_have_count(7)
                        assert page.locator('.symbol-trail').evaluate_all('(els) => els.every(e => e.getAttribute("aria-hidden") === "true" && getComputedStyle(e).pointerEvents === "none")')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), f'Horizontal overflow at {width}'
                        assert page.locator('.symbol-trail svg').first.evaluate('(e) => getComputedStyle(e).animationName') == 'none'
                        ids = page.locator('[id]').evaluate_all('(els) => els.map(e => e.id)')
                        assert len(ids) == len(set(ids)), 'Duplicate HTML ids'
                        assert page.locator('a[href^="#"]').evaluate_all('(els) => els.every(e => !!document.getElementById(e.hash.slice(1)))'), 'Broken page anchor'
                        # Every visible decoration stays outside interactive form controls.
                        assert page.evaluate('''() => {
                            const rects = [...document.querySelectorAll('input:not([type=hidden]), textarea, select, button')]
                                .filter(e => e.getClientRects().length).map(e => e.getBoundingClientRect());
                            return [...document.querySelectorAll('.symbol-trail svg, .doodle-rail svg')]
                                .filter(e => e.getClientRects().length).every(e => {
                                    const a = e.getBoundingClientRect();
                                    return rects.every(b => a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
                                });
                        }'''), f'Decoration overlaps controls at {width}'
                        page.screenshot(path=str(OUT / f'home-{width}.png'), full_page=True, animations='disabled')
                        page.locator('#programs').screenshot(path=str(OUT / f'coming-soon-{width}.png'), animations='disabled')
                        trigger = page.get_by_role('button', name='Box breathing', exact=True)
                        trigger.click()
                        expect(page.locator('#breathingDialog')).to_be_visible()
                        assert page.locator('#breathingDialog').evaluate('(e) => e.open')
                        page.screenshot(path=str(OUT / f'breathing-{width}.png'), animations='disabled')
                        page.keyboard.press('Escape')
                        expect(page.locator('#breathingDialog')).not_to_be_visible()
                        expect(trigger).to_be_focused()
                        assert not errors, errors
                        report.append({'width': width, 'status': 'passed', 'javascript_errors': errors})
                        print(f'PASS {width}px: six feature areas, distributed symbols, no overflow, breathing dialog and focus return')
                        page.close()
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.goto(BASE, wait_until='networkidle')
                    page.locator('#motionToggle').click()
                    expect(page.locator('html')).to_have_attribute('data-motion', 'off')
                    assert page.locator('.symbol-trail svg').first.evaluate('(e) => getComputedStyle(e).animationName') == 'none'
                    print('PASS manual reduced-motion toggle')
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
