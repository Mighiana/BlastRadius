import tomllib
from pathlib import Path

from blastradius import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_package_metadata_and_entry_points():
    metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    project = metadata['project']
    assert project['name'] == 'blastradius'
    assert project['requires-python'] == '>=3.11'
    assert project['scripts']['blastradius'] == 'blastradius.cli:main'
    assert project['scripts']['blastradius-comment'] == 'blastradius.github_pr:main'
    assert metadata['tool']['setuptools']['dynamic']['version']['attr'] == 'blastradius.__version__'
    assert __version__
    assert metadata['tool']['setuptools']['packages']['find']['include'] == ['blastradius', 'blastradius.*']


def test_cli_install_does_not_require_the_dashboard():
    metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    dependencies = metadata['project']['dependencies']
    assert not any('streamlit' in d or 'pyvis' in d for d in dependencies)
    assert all('==' in dep for dep in dependencies)
    assert 'ui' in metadata['project']['optional-dependencies']


def test_readme_distinguishes_published_source_and_hosted_verification():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'Attack-path diff for Terraform pull requests.' in readme
    assert 'No PyPI package or `v1` tag is published.' in readme
    assert 'Hosted PR analysis and comment updates are verified' in readme
    assert '35441550348' in readme and '35441968970' in readme
    assert '5741664556' in readme
    assert 'Fork/read-only-token behavior remains locally tested' in readme
    assert 'docs/screenshot-' not in readme
    assert 'Vendor the `blastradius/` package' not in readme
    roadmap = readme.split('## Future roadmap', 1)[1]
    assert 'A GitHub Action wrapping' not in roadmap
