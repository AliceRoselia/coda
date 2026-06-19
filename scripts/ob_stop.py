#!/usr/bin/env python3
"""Stop an OpenBench test (or tune) via the web UI.

Usage:
    python3 ob_stop.py <test_id>
    python3 ob_stop.py 93

Environment variables (or use --flags):
    OPENBENCH_SERVER   (default: https://ob.atwiss.com)
    OPENBENCH_USERNAME (default: claude)
    OPENBENCH_PASSWORD (required)

Behaviour notes
---------------
A successful STOP POST redirects (302) to ``/index/`` — that redirect IS the
expected, accepted-action response, not an error. We then confirm by
re-fetching the workload detail page: a *running* workload renders an enabled
``href="/<prefix>/<id>/STOP"`` link; once it stops/finishes that link is
removed (and an enabled ``RESTART`` link appears). The stop is asynchronous —
workers finish their in-flight games first — so we poll briefly. If the 302
arrived but the workload still shows active after polling, the request was
still accepted and the test is just draining; we report that as success, not a
failure. (The previous version looked for JSON ``"finished"``/``"active"``
fields that don't exist in this HTML, so it printed a false WARNING on every
successful stop.)
"""

import argparse
import os
import time
import requests

SERVER   = os.environ.get('OPENBENCH_SERVER',   'https://ob.atwiss.com')
USERNAME = os.environ.get('OPENBENCH_USERNAME', 'claude')
PASSWORD = os.environ.get('OPENBENCH_PASSWORD', '')


def _login(s, args):
    s.get(f'{args.server}/login/')
    csrf = s.cookies.get('csrftoken')
    r = s.post(f'{args.server}/login/', data={
        'username': args.username,
        'password': args.password,
        'csrfmiddlewaretoken': csrf,
    }, headers={'Referer': f'{args.server}/login/'}, allow_redirects=False)
    return r.headers.get('Location', '') == '/index/'


def _detail(s, args):
    """Fetch the workload detail page and infer its prefix ('test' or 'tune').

    Prefix is read from the DELETE link, which is present in both the running
    and finished states (the STOP link is not). Returns (html, prefix).
    """
    html = s.get(f'{args.server}/test/{args.test_id}/').text
    if f'/tune/{args.test_id}/DELETE' in html:
        return html, 'tune'
    if f'/test/{args.test_id}/DELETE' in html:
        return html, 'test'
    # Fall back to the explicit tune URL if the test page didn't resolve.
    html = s.get(f'{args.server}/tune/{args.test_id}/').text
    if f'/tune/{args.test_id}/DELETE' in html:
        return html, 'tune'
    return html, 'test'


def _is_running(html, prefix, test_id):
    """True iff the workload is still stoppable (renders an enabled Stop link).

    A stopped/finished workload drops the Stop link entirely (the UI shows a
    disabled Stop / an enabled Restart instead), so the absence of this href is
    the reliable 'no longer active' signal.
    """
    return f'href="/{prefix}/{test_id}/STOP"' in html


def stop_test(args):
    s = requests.Session()
    if not _login(s, args):
        print('Error: login failed')
        return False

    html, prefix = _detail(s, args)
    if not _is_running(html, prefix, args.test_id):
        print(f'Test #{args.test_id} is already stopped/finished '
              f'(no active Stop link). Nothing to do.')
        return True

    # POST STOP to the detected workload type. Action MUST be uppercase STOP —
    # modify_workload's action dict only has uppercase keys.
    csrf = s.cookies.get('csrftoken')
    r = s.post(f'{args.server}/{prefix}/{args.test_id}/STOP/', data={
        'csrfmiddlewaretoken': csrf,
    }, headers={
        'Referer': f'{args.server}/{prefix}/{args.test_id}/',
    }, allow_redirects=False)

    location = r.headers.get('Location', '')
    if r.status_code in (301, 302) and location == '/index/':
        # 302 -> /index/ is the expected accepted-action response. Confirm the
        # workload actually leaves the active state, polling for the async stop
        # (workers finish in-flight games before it flips).
        for _ in range(6):
            html, prefix = _detail(s, args)
            if not _is_running(html, prefix, args.test_id):
                print(f'Test #{args.test_id} stopped '
                      f'(confirmed: STOP accepted, workload no longer active).')
                return True
            time.sleep(2)
        # Accepted but still draining in-flight games. The request succeeded.
        print(f'Test #{args.test_id}: STOP accepted (302 -> /index/). Still '
              f'showing active — draining in-flight games; it will finish '
              f'shortly. Re-check ob_status.py if needed.')
        return True

    print(f'Error: STOP not accepted '
          f'(status {r.status_code}, Location {location!r}).')
    return False


def main():
    p = argparse.ArgumentParser(description='Stop an OpenBench test')
    p.add_argument('test_id', type=int, help='Test ID to stop')
    p.add_argument('--server', default=SERVER, help=f'Server (default: {SERVER})')
    p.add_argument('--username', default=USERNAME, help='Username')
    p.add_argument('--password', default=PASSWORD, help='Password')
    args = p.parse_args()

    if not args.password:
        print('Error: password required. Set OPENBENCH_PASSWORD or use --password')
        return

    stop_test(args)


if __name__ == '__main__':
    main()
