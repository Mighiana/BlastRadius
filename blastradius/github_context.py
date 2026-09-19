from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


class GitHubContextError(ValueError):
    pass


@dataclass(frozen=True)
class PullRequestContext:
    repository: str
    number: int
    base_sha: str
    head_sha: str
    workspace: Path

    @classmethod
    def from_environment(cls, environ=None):
        env = os.environ if environ is None else environ
        if env.get('GITHUB_EVENT_NAME') != 'pull_request':
            raise GitHubContextError('--github-action requires a pull_request event; pull_request_target is not supported')
        event_path = env.get('GITHUB_EVENT_PATH')
        if not event_path:
            raise GitHubContextError('GITHUB_EVENT_PATH is required')
        try:
            event = json.loads(Path(event_path).read_text(encoding='utf-8'))
            pr = event['pull_request']
            number = pr['number']
            repository = event['repository']['full_name']
            base_repository = pr['base']['repo']['full_name']
            base = pr['base']['sha']
            head = pr['head']['sha']
        except (OSError, ValueError, KeyError, TypeError):
            raise GitHubContextError('Invalid or unreadable pull_request event payload') from None
        if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*', repository):
            raise GitHubContextError('Event repository must be owner/name')
        if repository != env.get('GITHUB_REPOSITORY') or base_repository != repository:
            raise GitHubContextError('PR base repository does not match GITHUB_REPOSITORY')
        if type(number) is not int or number < 1:
            raise GitHubContextError('Event PR number must be a positive integer')
        if not all(isinstance(sha, str) and re.fullmatch(r'[0-9a-fA-F]{40}', sha) for sha in (base, head)):
            raise GitHubContextError('PR base and head must be full commit SHAs, not branch names')
        workspace = env.get('GITHUB_WORKSPACE')
        if not workspace:
            raise GitHubContextError('GITHUB_WORKSPACE is required')
        return cls(repository, number, base, head, Path(workspace))
