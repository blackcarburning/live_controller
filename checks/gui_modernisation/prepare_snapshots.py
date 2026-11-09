#!/usr/bin/env python3
"""Reconstruct and hash-check exact release inputs; never imports controller code.

Use an existing, empty, explicitly chosen scratch directory. Reads the tagged
baseline through git show and the candidate as bytes; writes two new .py files.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess

BASELINE_REF = 'pre-gui-modernisation-20261109'
BASELINE_COMMIT = 'e0f1f6be9641c5bb611102903899a90919b5ae01'
BASELINE_LF = '605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346'
BASELINE_CRLF = '56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee'
CANDIDATE_LF = '64d017ce7635598156a8328d5123bbf8744ca8630e950f09fdb0088631f076b5'
CANDIDATE_CRLF = '05ca1aa58da4a4c38e4cf40c4322efd0c4d7259bf446f642e41d66569b125896'


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.output_dir.resolve()
    require(out.is_dir(), 'Create an explicit empty scratch --output-dir first.')
    require(not any(out.iterdir()), 'Output directory is not empty; nothing overwritten.')
    names = ('baseline.py', 'candidate.py')
    destinations = [out / name for name in names]
    candidate = (repo / 'live_controller.py').read_bytes()
    # The tag may be annotated: peel to the verified pre-GUI commit explicitly.
    commit = subprocess.check_output(
        ['git', '-C', str(repo), 'rev-parse', BASELINE_REF + '^{}'], text=True).strip()
    require(commit == BASELINE_COMMIT, 'Baseline tag points to a different commit.')
    baseline = subprocess.check_output(
        ['git', '-C', str(repo), 'show', BASELINE_REF + ':live_controller.py'])
    inputs = ((baseline, BASELINE_LF, BASELINE_CRLF),
              (candidate, CANDIDATE_LF, CANDIDATE_CRLF))
    prepared = []
    for data, lf_pin, crlf_pin in inputs:
        normalized = data.replace(b'\r\n', b'\n')
        require(digest(normalized) == lf_pin, 'Normalized input hash mismatch; release changed.')
        crlf = normalized.replace(b'\n', b'\r\n')
        require(digest(crlf) == crlf_pin, 'Reconstructed CRLF hash mismatch.')
        compile(crlf, '<read-only release snapshot>', 'exec', dont_inherit=True)
        prepared.append(crlf)
    require((repo / 'live_controller.py').read_bytes() == candidate,
            'Candidate changed while preparing snapshots.')
    for destination, data in zip(destinations, prepared):
        with destination.open('xb') as stream:
            stream.write(data)
        require(destination.read_bytes() == data, 'Snapshot write verification failed.')
        print(digest(data) + '  ' + str(destination))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
