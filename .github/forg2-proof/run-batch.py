"""CI-only orchestration; proof source remains separate from the tested commit."""
import json, os, subprocess, sys
from pathlib import Path
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub Actions only; no local or live application execution.')
workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
temporary = Path(os.environ['RUNNER_TEMP']).resolve()
definition = workspace / '.github/forg2-proof'
manifest = json.loads((definition / 'manifest.json').read_text())
batch = int(sys.argv[1])
output = temporary / ('forg2-controls-' + str(batch))
output.mkdir(exist_ok=False)
results = []
for control in manifest['negative_controls'][batch::4]:
    identifier = control['id']
    candidate = temporary / ('candidate-' + identifier)
    evidence = output / identifier
    evidence.mkdir()
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(workspace), str(candidate)], check=True)
    subprocess.run(['git', 'checkout', '--quiet', '--detach', manifest['head']], cwd=candidate, check=True)
    subprocess.run(['bun', 'install', '--frozen-lockfile', '--ignore-scripts'], cwd=candidate, check=True)
    target = control.get('test_target', 'core-bitbucket')
    if target not in ('core-bitbucket', 'core-forge-observer'):
        raise SystemExit('Unsupported fixed CI test target.')
    command = ['bun', 'run', 'test', target, '-t', control['selector']]
    row = {'control': identifier, 'candidate': manifest['head'], 'expected_test_count': control['expected_test_count'], 'discovery_verified': False, 'failure_attribution': 'foreground inspection required'}
    with (evidence / 'BASELINE.log').open('wb') as log:
        result = subprocess.run(command, cwd=candidate, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    row['baseline_exit_code'] = result.returncode
    if result.returncode == 0:
        with (evidence / 'driver.log').open('wb') as log:
            result = subprocess.run([sys.executable, str(definition / 'ci-control.py'), '--checkout', str(candidate), '--control', identifier, '--evidence-dir', str(evidence / 'mutation')], cwd=workspace, stdout=log, stderr=subprocess.STDOUT, timeout=400)
        row['driver_exit_code'] = result.returncode
    else:
        row['driver_exit_code'] = None
    results.append(row)
    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(row), flush=True)
if any(r['baseline_exit_code'] != 0 or r['driver_exit_code'] != 0 for r in results):
    raise SystemExit(1)
