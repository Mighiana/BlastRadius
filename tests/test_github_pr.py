import io
import json
from urllib.error import HTTPError

import pytest

from blastradius.github_pr import BOT_LOGIN, MARKER, GitHubClient, GitHubError, _NoRedirect, publish_report
from blastradius.graph import compare
from blastradius.report import build_pr_comment

SHA = 'a' * 40


class FakeClient:
    def __init__(self, pages=None, head=SHA):
        self.pages = pages or [[]]
        self.head = head
        self.calls = []
        self.saved = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if '/pulls/' in path:
            return {'head': {'sha': self.head}}
        if method == 'GET':
            page = int(path.rsplit('=', 1)[1])
            return self.pages[page - 1]
        self.saved = payload['body']
        return {'id': 12}


def comment(body=MARKER + '\nold', login=BOT_LOGIN, kind='Bot'):
    return {'id': 12, 'user': {'login': login, 'type': kind}, 'body': body}


def test_create_then_update_without_duplicate():
    client = FakeClient()
    report = MARKER + '\nnew'
    assert publish_report('owner/repo', 1, report, client=client, head_sha=SHA).status == 'created'
    client.pages = [[comment(report)]]
    assert publish_report('owner/repo', 1, report, client=client).status == 'unchanged'
    assert publish_report('owner/repo', 1, report + '\nfixed', client=client).status == 'updated'
    assert [m for m, _, _ in client.calls if m != 'GET'] == ['POST', 'PATCH']


def test_paginated_lookup_and_author_guard():
    client = FakeClient([[comment(login='contributor', kind='User')] * 100, [comment()]])
    assert publish_report('owner/repo', 7, MARKER + '\nresult', client=client).status == 'updated'
    assert 'page=2' in client.calls[1][1]
    assert client.calls[-1][0] == 'PATCH'


def test_marker_on_human_comment_does_not_get_overwritten():
    client = FakeClient([[comment(login='contributor', kind='User')]])
    assert publish_report('owner/repo', 7, MARKER + '\nresult', client=client).status == 'created'
    assert client.calls[-1][0] == 'POST'


def test_stale_head_does_not_publish():
    client = FakeClient(head='b' * 40)
    assert publish_report('owner/repo', 7, MARKER, head_sha=SHA, client=client).status == 'stale'
    assert len(client.calls) == 1


def test_no_token_is_a_clear_skip():
    assert publish_report('owner/repo', 7, MARKER).status == 'skipped'


@pytest.mark.parametrize('repository,number,body', [('../repo', 1, MARKER), ('owner/repo', 0, MARKER),
    ('owner/repo', 1, 'unmarked'), ('owner/repo', 1, MARKER + 'x' * 60000)],
    ids=['invalid-repo', 'invalid-number', 'missing-marker', 'oversized'])
def test_invalid_publication_is_rejected(repository, number, body):
    with pytest.raises(GitHubError):
        publish_report(repository, number, body, client=FakeClient())


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_api_errors_never_leak_token_or_response_body(status):
    class Denied:
        def open(self, request, timeout):
            assert request.get_header('Authorization') == 'Bearer private-token'
            raise HTTPError(request.full_url, status, 'secret response', {}, io.BytesIO(b'private-token'))
    client = GitHubClient('private-token')
    client._opener = Denied()
    with pytest.raises(GitHubError) as error:
        client.request('GET', '/repos/owner/repo/issues/1/comments')
    assert str(status) in str(error.value)
    assert 'private-token' not in str(error.value)
    assert 'secret response' not in str(error.value)


def test_http_methods_headers_and_redirect_protection():
    class Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()
    class Opener:
        def open(self, request, timeout):
            assert request.method == 'PATCH'
            assert request.full_url.startswith('https://api.github.com/repos/')
            assert json.loads(request.data) == {'body': MARKER}
            assert timeout == 20
            return Response(b'{"id": 12}')
    client = GitHubClient('private-token')
    client._opener = Opener()
    assert client.request('PATCH', '/repos/owner/repo/issues/comments/12', {'body': MARKER})['id'] == 12
    assert _NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com') is None


def test_concise_marked_report(safe_result, vulnerable_result):
    report = build_pr_comment(compare(safe_result, vulnerable_result))
    assert report.startswith(MARKER)
    assert '**Decision: 🚫 BLOCK CHANGE**' in report
    assert '**Security score:** 100 → 20' in report
    assert '**New critical attack paths:** 1' in report
    assert 'Internet → Web SG → Web Server → App Role → Customer Data' in report
    assert 'not proof of infrastructure safety' in report
    fixed = build_pr_comment(compare(vulnerable_result, safe_result))
    assert '✅ SAFE TO MERGE' in fixed
    assert 'No new modeled critical attack paths detected.' in fixed


def test_comment_reports_unsupported_coverage(safe_result, vulnerable_result):
    vulnerable_result.graph.graph['unsupported'] = ['aws_lambda_function']
    report = build_pr_comment(compare(safe_result, vulnerable_result))
    assert 'Outside current model coverage' in report
    assert 'aws\\_lambda\\_function' in report
