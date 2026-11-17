"""Offline HTML extraction dispatched only through the canonical fabric."""
import hashlib
import json
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.langgraph.agency.obscura_worker import _extract, slot
from services.langgraph.agency.obscura_egress import retrieve
from ..verifiers import Verdict


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
    html: str | None = Field(default=None, min_length=1, max_length=262144)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    source_ref: str = Field(min_length=1, max_length=2048)

    @model_validator(mode='after')
    def one_source(self):
        if (self.html is None) == (self.url is None):
            raise ValueError('Supply exactly one of html or url')
        if self.url:
            from urllib.parse import urlsplit
            value = urlsplit(self.url)
            if value.scheme != 'https' or not value.hostname or value.username is not None or value.password is not None or value.port not in {None, 443}:
                raise ValueError('Only public HTTPS URLs on port 443 are supported')
        return self


def available() -> bool:
    from services.langgraph.agency.obscura_runtime import runtime_status
    return runtime_status()['ready']


def run(payload: dict) -> dict:
    if not available():
        raise RuntimeError('OBSCURA_DISABLED')
    inputs = Input.model_validate(payload['inputs'])
    if inputs.url and os.environ.get('AMC_OBSCURA_PUBLIC_ENABLED') != '1':
        raise RuntimeError('PUBLIC_BROWSING_DISABLED')
    with slot():
        page = retrieve(inputs.url) if inputs.url else None
        html = page['html'] if page else inputs.html
        text = _extract(html, Path(os.environ['AMC_OBSCURA_BINARY_DIR']))
    report = {'kind': 'obscura_extraction', 'provider': 'obscura/v0.2.7',
              'source_ref': inputs.source_ref, 'source_status': 'RETRIEVED' if page else 'UNVERIFIED_SUPPLIED_HTML',
              'input_sha256': hashlib.sha256(html.encode()).hexdigest(),
              'output_sha256': hashlib.sha256(text.encode()).hexdigest(), 'markdown': text,
              'runtime_image': os.environ['AMC_OBSCURA_RUNTIME_IMAGE'],
              'network_requests': page['http_requests'] if page else 0, 'untrusted_content': True,
              'retrieval': {k:v for k,v in page.items() if k!='html'} if page else None,
              'source_html': html if page else None,
              'limitations':['External scripts, images and subresources are not fetched; use Chromium for full-page compatibility.']}
    return {'content': json.dumps(report, sort_keys=True), 'mime_type': 'application/json',
            'subtype': 'obscura_extraction'}


def verify(output: dict, payload: dict) -> Verdict:
    try:
        inputs = Input.model_validate(payload['inputs'])
        report = json.loads(output['content'])
        html = report['source_html'] if inputs.url else inputs.html
        expected_status = 'RETRIEVED' if inputs.url else 'UNVERIFIED_SUPPLIED_HTML'
        retrieval_valid = not inputs.url or (report['retrieval']['source_sha256'] == hashlib.sha256(html.encode()).hexdigest() and report['retrieval']['final_url'].startswith('https://') and bool(report['retrieval']['retrieved_at']))
        ok = (retrieval_valid and report['input_sha256'] == hashlib.sha256(html.encode()).hexdigest()
              and report['output_sha256'] == hashlib.sha256(report['markdown'].encode()).hexdigest()
              and report['source_status'] == expected_status
              and report['untrusted_content'] is True
              and report['source_ref'] == inputs.source_ref
              and report['runtime_image'] == os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE')
              and report['provider'] == 'obscura/v0.2.7')
    except (ValueError, KeyError, TypeError):
        ok = False
    return Verdict('obscura_readback', ok, 'Extraction identity and untrusted source status')
