#!/usr/bin/env python3
"""Fail release qualification on stale artifacts or unrepresented carrier coverage."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import yaml
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from generate_deployment_matrix import DeploymentMatrixGenerator
from test_matrix import generate_matrix

def package_targets(config):
    for version,cfg in config['versions'].items():
        for vendor in cfg.get('vendors',['generic']):
            for carrier in config['vendors'][vendor]['carriers']:
                for som in cfg.get('vendor_soms',{}).get(vendor,['']):
                    suffix=('-'+som) if som else ''
                    if vendor!='generic':suffix+='-'+vendor+'-'+carrier
                    name=('jetson-l4t-'+version+'-jp'+cfg['jetpack']+suffix+'-eg-cams').replace('_','-')
                    yield dict(version=version,vendor=vendor,carrier=carrier,som=som,package=name)

def identity_issue(target, fields, revision, package_version=None):
    name,version,arch=fields
    if name!=target['package'] or arch!='arm64':return 'package identity/architecture mismatch'
    if package_version is not None:
        return None if version==package_version else 'package version mismatch'
    match=re.search(r'\+g([0-9a-f]{7,40})(?:$|[.+~])',version)
    return None if match and revision.startswith(match[1]) else 'package not traceable to requested revision'

def waiver_ids(path):
    if path is None:return set()
    data=json.loads(path.read_text());ids=set();today=datetime.date.today()
    for w in data:
        if not w.get('reason') or not w.get('owner') or not w.get('compensating_test'):
            raise ValueError('Waiver requires reason, owner and compensating_test')
        if datetime.date.fromisoformat(w['expires'])<today:raise ValueError('Expired waiver: '+w['id'])
        ids.add(w['id'])
    return ids

def audit(root, revision, package_version=None):
    config=yaml.safe_load((root/'eg_config.yaml').read_text());issues=[];artifacts=[]
    entries=list(generate_matrix());matrix=DeploymentMatrixGenerator(root/'tools/deployment_matrix_data.yaml')
    for target in package_targets(config):
        candidates=sorted((root/target['version']).glob(target['package']+'_*.deb'))
        good=[]
        for path in candidates:
            p=subprocess.run(['dpkg-deb','-f',str(path),'Package','Version','Architecture'],capture_output=True,text=True)
            if p.returncode:continue
            # dpkg-deb uses labelled output when several fields are requested.
            fields={line.split(': ',1)[0]:line.split(': ',1)[1] for line in p.stdout.splitlines() if ': ' in line}
            error=identity_issue(target,[fields.get(k,'') for k in ('Package','Version','Architecture')],revision,package_version)
            if not error:good.append(str(path))
        if len(good)!=1:
            issues.append(dict(id='artifact:'+target['package'],detail=f'Expected exactly one candidate artifact for revision {revision}; found {len(good)}',waivable=False))
        else:artifacts.append(dict(**target,path=good[0]))
    for platform in matrix.data['platforms']:
        binding=platform.get('support_source')
        if binding:
            for version in matrix.camera_db['versions']:
                if matrix.platform_available(platform['id'],version) and not any(e.version==version and e.platform_id==platform['id'] and e.vendor==binding['vendor'] for e in entries):
                    issues.append(dict(id='host-fixture:'+platform['id']+':'+version,
                                       detail='No carrier-specific P1/P2/P3 fixture; generic NVIDIA DTB tests do not cover this carrier',waivable=True))
    for version,cfg in config['versions'].items():
        for platform in cfg.get('platform_ids',[]):
            if platform not in matrix.platforms_by_id:
                issues.append(dict(id='matrix-platform:'+platform,detail='Supported platform absent from deployment matrix',waivable=False))
    return issues,artifacts

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--revision',default='HEAD');p.add_argument('--package-version',default=os.environ.get('EG_RELEASE_PACKAGE_VERSION'))
    p.add_argument('--waivers',type=Path,default=Path(os.environ['EG_RELEASE_WAIVERS']) if os.environ.get('EG_RELEASE_WAIVERS') else None);p.add_argument('--output',type=Path)
    args=p.parse_args();revision=subprocess.check_output(['git','rev-parse',args.revision],cwd=ROOT,text=True).strip()
    issues,artifacts=audit(ROOT,revision,args.package_version)
    dirty=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip()
    if dirty:issues.append(dict(id='dirty-tracked-source',detail='Tracked source modifications must be resolved before freezing a release candidate',waivable=False))
    untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','--','sources','test','tools','docs'],cwd=ROOT,text=True).strip()
    if untracked:issues.append(dict(id='untracked-source',detail='Untracked source/test/documentation files must be resolved before freezing the candidate',waivable=False))
    waivers=waiver_ids(args.waivers)
    for item in issues:item['waived']=item['waivable'] and item['id'] in waivers
    result=dict(revision=revision,status='blocked' if any(not x['waived'] for x in issues) else 'ready-for-host-tests',issues=issues,artifacts=artifacts)
    if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
    for item in issues:print(('WAIVED ' if item['waived'] else 'BLOCK ')+item['id']+': '+item['detail'])
    print(f"{len(artifacts)} candidate packages; {result['status']}")
    return int(result['status']=='blocked')
if __name__=='__main__':sys.exit(main())
