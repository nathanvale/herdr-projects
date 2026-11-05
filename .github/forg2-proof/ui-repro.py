"""CI-only, bounded observation of unchanged public browser regressions."""
import hashlib, json, os, subprocess, sys
from pathlib import Path
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('CI only; no local or live preview execution.')
definition = Path(__file__).resolve().parent
manifest = json.loads((definition / 'ui-repro-manifest.json').read_text())
revision = sys.argv[1]
if revision not in manifest['revisions']:
    raise SystemExit('Unknown fixed revision')
workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
candidate = workspace / 'candidate'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=candidate, text=True).strip()
if head != manifest['revisions'][revision]:
    raise SystemExit('Candidate revision mismatch')
for file, expected in manifest['unchanged_inputs'].items():
    if hashlib.sha256((candidate / file).read_bytes()).hexdigest() != expected:
        raise SystemExit('Browser input differs: ' + file)
out = Path(os.environ['RUNNER_TEMP']) / ('swipe-workload-' + revision)
out.mkdir(exist_ok=False)
command = ['bun', 'run', 'test', 'layout-restart', 'layout-tasks', 'layout-sending', 'layout-settings', 'layout-search', 'layout-split', 'layout-sections']
receipt = {'revision': revision, 'head': head, 'command': command, 'expected_tests': 68, 'expected_files': 7, 'max_observations': 3, 'observations': [], 'qualification': 'diagnostic only; foreground failure attribution required'}
for index in range(manifest['max_observations_per_revision']):
    path = out / ('observation-' + str(index) + '.log')
    with path.open('wb') as log:
        result = subprocess.run(command, cwd=candidate, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    receipt['observations'].append({'index': index, 'exit_code': result.returncode, 'log_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['observations'][-1]), flush=True)
    if result.returncode:
        break
receipt['after_status'] = subprocess.check_output(['git', 'status', '--porcelain'], cwd=candidate, text=True)
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
# Reproduction remains RED. Never convert an observed test failure into GREEN.
raise SystemExit(1 if any(r['exit_code'] for r in receipt['observations']) else 0)
