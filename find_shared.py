"""从 shared.js 提取 BirdwatchFetchGlobalTimeline"""
import json, urllib.request, ssl, os, tempfile, subprocess
from bs4 import BeautifulSoup

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request('https://x.com/', headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})
resp = urllib.request.urlopen(req, timeout=30, context=ctx)
soup = BeautifulSoup(resp.read().decode('utf-8', errors='replace'), 'html.parser')

shared_url = None
for script in soup.select('script[src]'):
    src = script.get('src', '')
    if 'shared~bundle' in src and src.endswith('.js'):
        shared_url = src
        break
if not shared_url:
    print('No shared~bundle found')
    # Try other bundles
    for script in soup.select('script[src]'):
        src = script.get('src', '')
        if src.endswith('.js') and 'chunk' in src:
            print(f'  Found: {src}')
    exit(1)

if shared_url.startswith('//'):
    shared_url = 'https:' + shared_url
elif shared_url.startswith('/'):
    shared_url = 'https://x.com' + shared_url

print(f'Downloading shared.js from: {shared_url}')
req2 = urllib.request.Request(shared_url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})
resp2 = urllib.request.urlopen(req2, timeout=120, context=ctx)
content = resp2.read().decode('utf-8', errors='replace')
print(f'Got {len(content)} bytes')

JSCODE = """
window = global;
window.self = window;
window.__SCRIPTS_LOADED__ = {};
window.__SCRIPTS_LOADED__.vendor = true;
window.webpackChunk_twitter_responsive_web = [];
%s
function getExportValues() {
    try {
        const exportValues = {};
        if (self.webpackChunk_twitter_responsive_web && 
            self.webpackChunk_twitter_responsive_web[0] && 
            self.webpackChunk_twitter_responsive_web[0][1]) {
            const moduleFunctions = self.webpackChunk_twitter_responsive_web[0][1];
            Object.values(moduleFunctions).forEach(func => {
                try {
                    if (typeof func === 'function' && func.length === 1) {
                        const temp = {};
                        func(temp);
                        if (temp.exports && 
                            typeof temp.exports === 'object' && 
                            temp.exports.operationName) {
                            exportValues[temp.exports.operationName] = temp.exports;
                        }
                    }
                } catch (err) {}
            });
        }
        return exportValues;
    } catch (err) {
        return {};
    }
}
"""

print('\nExtracting with Node.js...')
js_code = JSCODE % content
js_file = os.path.join(tempfile.gettempdir(), 'extract_shared.js')
with open(js_file, 'w', encoding='utf-8') as f:
    f.write(js_code + '\nconst r = getExportValues(); process.stdout.write(JSON.stringify(r));')

proc = subprocess.run(['node', js_file], capture_output=True, text=True, timeout=120)
if proc.returncode == 0:
    try:
        result = json.loads(proc.stdout.strip())
        if result:
            print(f'Extracted {len(result)} endpoints from shared.js')
            if 'BirdwatchFetchGlobalTimeline' in result:
                ep = result['BirdwatchFetchGlobalTimeline']
                print(f'\n=== BirdwatchFetchGlobalTimeline ===')
                print(json.dumps(ep, indent=2))
            else:
                print('BirdwatchFetchGlobalTimeline NOT in shared.js')
                print('Shared keys:')
                for k in sorted(result.keys()):
                    print(f'  {k}')
        else:
            print('Empty result')
    except json.JSONDecodeError as e:
        print(f'JSON error: {e}')
        if proc.stderr:
            print('stderr:', proc.stderr[:1000])
else:
    print(f'Node error: {proc.stderr[:2000]}')
