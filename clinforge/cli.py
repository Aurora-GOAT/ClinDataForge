import argparse
import json
import os
from .artifacts import write_json_no_overwrite
from .pipeline import run_pipeline
from .mimic_audit import audit_public_structured

def main(argv=None):
    p=argparse.ArgumentParser(description='ClinDataForge | experimental medical data quality pipeline')
    sub=p.add_subparsers(dest='cmd',required=True)
    run=sub.add_parser('run', help='Synthetic research batch; metadata only, all text and SFT exports withheld')
    run.add_argument('--input',required=True)
    run.add_argument('--output',required=True)
    run.add_argument('--synthetic',action='store_true',help='Only when input is demonstrably generated synthetic data')
    ra=sub.add_parser('audit-public-demo')
    ra.add_argument('--input',required=True)
    ra.add_argument('--output',required=True)
    args=p.parse_args(argv)
    if args.cmd=='run':
        key=os.environ.get('CLINFORGE_HMAC_KEY','')
        if args.synthetic and not key:
            key='synthetic-only-demo-key-2026'
        result=run_pipeline(args.input,args.output,key,synthetic=args.synthetic)
    else:
        result=audit_public_structured(args.input)
        write_json_no_overwrite(args.output, result)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':
    main()
