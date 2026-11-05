"""Proposed foreground CI control driver. Never run on the worker checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--checkout', required=True, type=Path)
parser.add_argument('--control', required=True)
parser.add_argument('--evidence-dir', required=True, type=Path)
args = parser.parse_args()
manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
checkout = args.checkout.resolve(strict=True)
live = Path(manifest['worker_checkout']).resolve()
if checkout == live or checkout.is_relative_to(live):
    raise SystemExit('Refuse worker/live candidate. Supply a disposable CI clone.')

def git(*words):
    return subprocess.check_output(['git', *words], cwd=checkout, text=True).strip()

common = Path(git('rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()
if not common.is_relative_to(checkout):
    raise SystemExit('Require a standalone disposable CI clone, not shared live Git metadata.')
if git('rev-parse', 'HEAD') != manifest['head'] or git('rev-parse', 'HEAD^{tree}') != manifest['tree']:
    raise SystemExit('CI checkout differs from the exact reviewed candidate.')
if git('status', '--porcelain'):
    raise SystemExit('CI checkout must start clean.')
controls = {control['id']: control for control in manifest['negative_controls']}
control = controls[args.control]
hashes = {**manifest['source_files'], **manifest['protected_docs']}

def source(path):
    file = checkout / path
    if file.is_symlink() or not file.resolve(strict=True).is_relative_to(checkout):
        raise SystemExit('Candidate source escapes the disposable CI clone.')
    return file

def verify():
    for path, expected in hashes.items():
        if hashlib.sha256(source(path).read_bytes()).hexdigest() != expected:
            raise SystemExit('Exact candidate bytes differ: ' + path)

verify()
original = {mutation['file']: source(mutation['file']).read_bytes() for mutation in control['mutations']}
evidence = args.evidence_dir.resolve()
if evidence.is_relative_to(checkout) or evidence == live or evidence.is_relative_to(live):
    raise SystemExit('Keep raw CI evidence outside both candidate and worker checkouts.')
evidence.mkdir(parents=True, exist_ok=False)
command = ['bun', 'run', 'test', 'core-bitbucket', '-t', control['selector']]
receipt = {'head': manifest['head'], 'tree': manifest['tree'], 'control': control['id'], 'cwd': str(checkout),
           'command': command, 'expected_test_count': control['expected_test_count'], 'discovery_verified': False}

def run(phase):
    with (evidence / (phase + '.log')).open('wb') as log:
        result = subprocess.run(command, cwd=checkout, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    receipt[phase + '_exit_code'] = result.returncode
    return result.returncode

try:
    try:
        for mutation in control['mutations']:
            file = source(mutation['file'])
            value = file.read_text()
            if value.count(mutation['find']) != 1:
                raise SystemExit('Control anchor is not unique.')
            file.write_text(value.replace(mutation['find'], mutation['replace'], 1))
        if run('RED') == 0:
            raise SystemExit('Control failed to demonstrate RED sensitivity.')
    finally:
        for path, value in original.items():
            source(path).write_bytes(value)
        verify()
    if run('GREEN') != 0:
        raise SystemExit('Restored exact candidate did not pass GREEN.')
    verify()
    if git('status', '--porcelain'):
        raise SystemExit('CI execution changed candidate files beyond its bounded mutation.')
finally:
    (evidence / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

# The foreground owner must inspect both complete Bun logs for discovery/counts,
# skips, failure cause and collateral errors. Exit status alone is insufficient.
print(json.dumps(receipt))
