import hashlib
import io
import json
import tarfile

import pytest
from services.langgraph.agency import obscura_artifact as artifact


def fixture(tmp_path, monkeypatch, members):
    archive = tmp_path / 'fixture.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'assets': [{'name': 'fixture', 'digest': 'sha256:' + hashlib.sha256(archive.read_bytes()).hexdigest()}]}))
    monkeypatch.setattr(artifact, 'MANIFEST', manifest)
    return archive


def test_verified_bytes(tmp_path, monkeypatch):
    archive = fixture(tmp_path, monkeypatch, [('obscura', b'fixture'), ('obscura-worker', b'worker')])
    assert artifact.verified_members(archive, 'fixture')['obscura'] == b'fixture'
    archive.write_bytes(archive.read_bytes() + b'altered')
    with pytest.raises(ValueError, match='DIGEST_MISMATCH'):
        artifact.verified_members(archive, 'fixture')


@pytest.mark.parametrize('names', [ ['../escape'], ['/absolute'], ['obscura', 'obscura'], ['obscura'], ['extra'] ])
def test_archive_refusals(tmp_path, monkeypatch, names):
    archive = fixture(tmp_path, monkeypatch, [(name, b'fixture') for name in names])
    with pytest.raises(ValueError, match='UNSAFE_ARCHIVE|MISSING_MEMBER'):
        artifact.verified_members(archive, 'fixture')


def test_unknown_asset_does_not_open_file(tmp_path):
    with pytest.raises(ValueError, match='UNSUPPORTED_ASSET'):
        artifact.verified_members(tmp_path / 'absent', 'untrusted')


def test_install_refuses_existing_destination(tmp_path, monkeypatch):
    archive=fixture(tmp_path,monkeypatch,[('obscura',b'fixture'),('obscura-worker',b'worker')])
    destination=tmp_path/'installed'
    actual=artifact.install(archive,destination,'fixture')
    assert actual['obscura']==hashlib.sha256(b'fixture').hexdigest()
    assert (destination/'obscura').read_bytes()==b'fixture'
    with pytest.raises(ValueError,match='DESTINATION_EXISTS'):
        artifact.install(archive,destination,'fixture')
