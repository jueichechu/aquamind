"""Prepare fictional bill layouts and score deliberately run extraction trials.

Provider calls require --run-live and --share-with-ai. There are no automatic downloads.
Public samples must be obtained separately.
Run from the repository root. Pillow/reportlab are optional fixture-authoring tools.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

MANIFEST = Path(__file__).parent / 'fixtures/bill-import-layout-v1.json'


def load_cases():
    return json.loads(MANIFEST.read_text())['cases']


def prepare(folder):
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.pdfgen import canvas
    folder.mkdir(parents=True, exist_ok=True)
    for case in load_cases():
        if not case['synthetic']:
            continue
        target = folder / case['file']
        if case['media_type'] == 'application/pdf':
            document = canvas.Canvas(str(target), pagesize=(612, 792))
            document.setTitle('Fictional water-bill evaluation fixture')
            for page in case['pages']:
                for index, line in enumerate(page):
                    document.setFont('Helvetica-Bold' if index == 0 else 'Helvetica', 11)
                    document.drawString(36, 744 - 32 * index, line)
                document.showPage()
            document.save()
        else:
            image = Image.new('RGB', (1600, 1800), 'white')
            draw = ImageDraw.Draw(image)
            for index, line in enumerate(case['pages'][0]):
                draw.text((48, 70 + 90 * index), line, fill='black', font=ImageFont.load_default(size=28))
            image.save(target, quality=90)


def score(case, report):
    """Score fields against independent expectations; blanks may be explicitly valid."""
    issues = []
    if report.get('status') != 'completed' or not isinstance(report.get('extraction'), dict):
        return ['Extraction did not complete']
    output = report['extraction']
    fields, warnings = output.get('fields', {}), set(output.get('warnings', []))
    if case.get('all_fields_null') and (len(fields) != 7 or any(value is not None for value in fields.values())):
        issues.append('Expected all fields to be withheld')
    for name, allowed in case.get('expected', {}).items():
        if name not in fields or fields[name] not in allowed:
            issues.append(f'Unexpected {name}')
    for warning in case.get('required_warnings', []):
        if warning not in warnings:
            issues.append(f'Missing warning: {warning}')
    for warning in case.get('excluded_warnings', []):
        if warning in warnings:
            issues.append(f'Unexpected warning: {warning}')
    if 'reading_type' in case and output.get('evidence', {}).get('reading_type') != case['reading_type']:
        issues.append('Unexpected reading type')
    return issues


async def run_trial(case, documents, results):
    """One explicit paid call. A started case can never be replayed in this folder."""
    import base64
    import hashlib
    import time
    from dotenv import load_dotenv
    from openai import AsyncOpenAI
    from aquamind_ml.agent import AgentConfig
    from aquamind_ml.bill_import import BillImportRequest, extract_report

    load_dotenv('.env.local', override=False)
    if not os.environ.get('OPENAI_API_KEY') or not os.environ.get('OPENAI_MODEL'):
        raise ValueError('Configure the existing server-side OpenAI key and model')
    data = (documents / case['file']).read_bytes()
    body = BillImportRequest(media_type=case['media_type'], share_with_ai=True,
        data_base64=base64.b64encode(data).decode())
    body.checked_data()
    results.mkdir(parents=True, exist_ok=True)
    target = results / f"{case['id']}.json"
    if target.exists():
        raise FileExistsError('Existing result; refusing a paid replay')
    (results / f"{case['id']}.started").open('x').close()
    record = {'case': case['id'], 'model': os.environ['OPENAI_MODEL'], 'paid_attempts': 1,
              'automatic_retries': 0, 'status': 'failed',
              'input_sha256': hashlib.sha256(data).hexdigest(),
              'source_sha256': hashlib.sha256((Path(__file__).resolve().parents[1] /
                  'ml/aquamind_ml/bill_import.py').read_bytes()).hexdigest()}
    started = time.monotonic()
    try:
        async with AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'], max_retries=0, timeout=30) as client:
            output = await extract_report(client, AgentConfig(model=os.environ['OPENAI_MODEL']), body)
            record.update(status='completed', extraction=output.model_dump())
    except Exception as error:
        # Never persist provider exception messages or arbitrary document text.
        record['error_type'] = type(error).__name__
    finally:
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        target.write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path, help='Write only synthetic PDF/image fixtures to this directory')
    parser.add_argument('--score', type=Path, help='Read case-id.json trial results from this directory')
    parser.add_argument('--run-live', choices=[case['id'] for case in load_cases()], help='Make one paid extraction call')
    parser.add_argument('--documents', type=Path, help='Directory holding the explicitly selected input file')
    parser.add_argument('--results', type=Path, help='Directory for result and no-replay marker')
    parser.add_argument('--share-with-ai', action='store_true', help='Explicitly consent to sending the selected file to OpenAI')
    args = parser.parse_args()
    if args.run_live and (not args.share_with_ai or not args.documents or not args.results):
        parser.error('--run-live needs --share-with-ai, --documents and --results')
    if args.run_live:
        case = next(row for row in load_cases() if row['id'] == args.run_live)
        record = asyncio.run(run_trial(case, args.documents, args.results))
        print(json.dumps({'case': case['id'], 'status': record['status'], 'issues': score(case, record)}))
        if score(case, record):
            raise SystemExit(1)
    if args.prepare:
        prepare(args.prepare)
    if args.score:
        outcomes = []
        for case in load_cases():
            path = args.score / f"{case['id']}.json"
            if not path.exists():
                outcomes.append({'id': case['id'], 'status': 'not_run'})
                continue
            issues = score(case, json.loads(path.read_text()))
            outcomes.append({'id': case['id'], 'status': 'failed' if issues else 'passed', 'issues': issues})
        print(json.dumps({'scope': 'Development checks, not population accuracy', 'cases': outcomes}, indent=2))
        if any(row['status'] != 'passed' for row in outcomes):
            raise SystemExit(1)
    elif not args.prepare and not args.run_live:
        print(json.dumps([{key: case[key] for key in ('id', 'name', 'synthetic', 'file', 'media_type')}
                          for case in load_cases()], indent=2))


if __name__ == '__main__':
    main()
