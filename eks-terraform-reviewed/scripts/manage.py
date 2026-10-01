#!/usr/bin/env python3
"""Noninteractive orchestration. Uses only Python's standard library and AWS CLI."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_AZ_IDS = {'use1-az3', 'usw1-az2', 'cac1-az3'}
ENV = dict(os.environ, TF_INPUT='0', TF_IN_AUTOMATION='1', AWS_PAGER='', AWS_CLI_AUTO_PROMPT='off')

class Failure(RuntimeError):
    pass

def execute(args, cwd=ROOT, capture=False):
    p = subprocess.run(args, cwd=cwd, env=ENV, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        detail = (p.stderr or p.stdout or '').strip()
        raise Failure(f"Command failed: {' '.join(map(str, args))}\n{detail}")
    return p.stdout if capture else ''

def tf(folder, *args, capture=False):
    return execute(['terraform', f'-chdir={folder}', *args], capture=capture)

def aws(*args, region=None, optional_codes=()):
    cmd = ['aws', *args, '--output', 'json', '--no-cli-pager']
    if region:
        cmd += ['--region', region]
    p = subprocess.run(cmd, env=ENV, text=True, capture_output=True)
    if p.returncode:
        code = re.search(r'\(([^)]+)\)', p.stderr)
        if code and code.group(1) in optional_codes:
            return None
        raise Failure(f"AWS {' '.join(args[:2])} failed: {p.stderr.strip()}")
    return json.loads(p.stdout or '{}')

def write_json(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)

def principal(identity, supplied='auto'):
    arn = identity['Arn'] if supplied == 'auto' else supplied
    if ':root' in arn or not arn.startswith('arn:aws:'):
        raise Failure('Use an IAM user/role in commercial AWS; root/federated/other partitions are not supported.')
    if ':assumed-role/' in arn and supplied == 'auto':
        # STS omits the IAM path. GetRole returns the real ARN, including SSO paths.
        name = arn.split(':assumed-role/', 1)[1].split('/', 1)[0]
        arn = aws('iam', 'get-role', '--role-name', name)['Role']['Arn']
    match = re.fullmatch(r'arn:aws:iam::([0-9]{12}):(role|user)/(.+)', arn)
    if not match or match.group(1) != identity['Account']:
        raise Failure('Administrator must be a permanent IAM role/user ARN in this account, not an STS session ARN.')
    if match.group(2) == 'role' and match.group(3).startswith('aws-service-role/'):
        raise Failure('EKS access entries cannot use an AWS service-linked role. Choose a human administrator IAM role/user.')
    name = match.group(3).rsplit('/', 1)[-1]
    kind = match.group(2)
    actual = aws('iam', 'get-' + kind, '--' + kind + '-name', name)[kind.title()]['Arn']
    if actual != arn:
        raise Failure('IAM ARN/path does not match the existing identity.')
    return arn

def public_cidr(value):
    if value == 'auto':
        try:
            # Force IPv4 through curl, to avoid IPv6 responses at dual-stack hosts.
            value = execute(['curl', '-4', '-fsS', '--connect-timeout', '5',
                             '--max-time', '15', 'https://checkip.amazonaws.com'], capture=True).strip() + '/32'
        except Failure as e:
            raise Failure('Could not detect public IPv4. Set admin_cidr in settings.json explicitly. ' + str(e))
    try:
        network = ipaddress.ip_network(value, strict=True)
        if network.version != 4 or network.prefixlen != 32 or not network.network_address.is_global:
            raise ValueError()
    except ValueError:
        raise Failure('admin_cidr must be a real public IPv4/32 address, not a private or documentation address.')
    return str(network)

def select_zones(zones, offerings):
    offered = {o['Location'] for o in offerings}
    eligible = sorted(z['ZoneName'] for z in zones
                      if z.get('State') == 'available'
                      and z.get('ZoneType') == 'availability-zone'
                      and z['ZoneId'] not in BLOCKED_AZ_IDS and z['ZoneName'] in offered)
    if len(eligible) < 2:
        raise Failure('Fewer than two EKS-eligible zones offer this instance type in the selected region.')
    return eligible

def preflight():
    for tool in ['terraform', 'aws', 'curl']:
        if not shutil.which(tool):
            raise Failure(f'Install {tool} and make it available in PATH first.')
    version = json.loads(execute(['terraform', 'version', '-json'], capture=True))['terraform_version']
    if not re.fullmatch(r'1\.(1[0-6])\.[0-9]+', version):
        raise Failure('Use a stable Terraform version >= 1.10 and < 1.17 for this DynamoDB-compatible project.')
    settings = json.loads((ROOT / 'settings.json').read_text())
    required = {'aws_region', 'cluster_name', 'kubernetes_version', 'node_instance_type', 'admin_cidr', 'admin_principal_arn'}
    if set(settings) != required or not all(isinstance(v, str) for v in settings.values()):
        raise Failure('settings.json must contain exactly the six documented string settings.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,49}', settings['cluster_name']):
        raise Failure('Invalid cluster name: use 1-50 letters/digits/underscores/hyphens, starting with a letter/digit.')
    identity = aws('sts', 'get-caller-identity', region=settings['aws_region'])
    meta_path = ROOT / '.setup.json'
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    if meta and meta['account'] != identity['Account']:
        raise Failure('AWS account changed. Restore the original profile; do not reuse this directory for another account.')
    if meta and (meta['region'] != settings['aws_region'] or meta['cluster_name'] != settings['cluster_name']):
        raise Failure('Region/cluster name changed after setup. Use a deliberate migration or a separate new project.')
    values = dict(settings)
    values['expected_account_id'] = identity['Account']
    values['admin_principal_arn'] = principal(identity, settings['admin_principal_arn'])
    values['admin_cidr'] = public_cidr(settings['admin_cidr'])
    region = settings['aws_region']
    versions = aws('eks', 'describe-cluster-versions', region=region)['clusterVersions']
    candidate = next((v for v in versions if v['clusterVersion'] == settings['kubernetes_version']), None)
    status = (candidate.get('versionStatus') or candidate.get('status', '')) if candidate else ''
    if status.upper().replace('-', '_') != 'STANDARD_SUPPORT':
        raise Failure('Chosen Kubernetes version is unavailable or outside standard support. Update settings.json after checking AWS.')
    types = aws('ec2', 'describe-instance-types', '--instance-types', settings['node_instance_type'], region=region)
    if not types['InstanceTypes'] or 'x86_64' not in types['InstanceTypes'][0]['ProcessorInfo']['SupportedArchitectures']:
        raise Failure('This project uses AL2023 x86_64; select a compatible x86_64 instance type.')
    zones = aws('ec2', 'describe-availability-zones', '--filters', 'Name=zone-type,Values=availability-zone', region=region)['AvailabilityZones']
    offered = aws('ec2', 'describe-instance-type-offerings', '--location-type', 'availability-zone',
                  '--filters', 'Name=instance-type,Values=' + settings['node_instance_type'], region=region)['InstanceTypeOfferings']
    eligible = select_zones(zones, offered)
    values['availability_zones'] = eligible[:2]
    prior = ROOT / 'generated.auto.tfvars.json'
    if meta and prior.exists():
        previous = json.loads(prior.read_text())
        old_zones = previous['availability_zones']
        if len(old_zones) != 2 or len(set(old_zones)) != 2 or not set(old_zones).issubset(eligible):
            raise Failure('Existing zone selection is no longer eligible. Stop and review; do not silently replace subnets.')
        values['availability_zones'] = old_zones
    return values, meta, eligible

def parse_backend(path):
    fields = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        m = re.fullmatch(r'(bucket|key|region|dynamodb_table|encrypt)\s*=\s*("[^"\n]+"|true|false)\s*(?:#.*)?', line)
        if not m or m.group(1) in fields:
            raise Failure('Reuse requires the original simple backend.hcl file, with bucket/key/region/encrypt/dynamodb_table only.')
        fields[m.group(1)] = json.loads(m.group(2))
    if set(fields) != {'bucket', 'key', 'region', 'dynamodb_table', 'encrypt'} or fields['encrypt'] is not True:
        raise Failure('Backend file is incomplete or encryption is disabled.')
    if fields['key'] != 'eks-lab/infra/terraform.tfstate':
        raise Failure('Unexpected state key. This reuse helper accepts only the original eks-lab/infra/terraform.tfstate key.')
    return fields

def backend_text(meta, key):
    fields = {'bucket': meta['bucket'], 'key': key, 'region': meta['region'],
              'encrypt': True, 'dynamodb_table': meta['table'], 'allowed_account_ids': [meta['account']]}
    lines = ['# Generated by run.sh setup. Contains no AWS credentials.', 'terraform {', '  backend "s3" {']
    lines += [f'    {k} = {json.dumps(v)}' for k, v in fields.items()]
    return '\n'.join(lines + ['  }', '}', ''])

def verify_backend(meta):
    aws('s3api', 'head-bucket', '--bucket', meta['bucket'], '--expected-bucket-owner', meta['account'], region=meta['region'])
    loc = aws('s3api', 'get-bucket-location', '--bucket', meta['bucket'], '--expected-bucket-owner', meta['account'], region=meta['region'])
    actual_region = loc.get('LocationConstraint') or 'us-east-1'
    actual_region = 'eu-west-1' if actual_region == 'EU' else actual_region
    if actual_region != meta['region']:
        raise Failure('S3 bucket region differs from the backend region.')
    table = aws('dynamodb', 'describe-table', '--table-name', meta['table'], region=meta['region'])['Table']
    if table['TableStatus'] != 'ACTIVE' or table['KeySchema'] != [{'AttributeName': 'LockID', 'KeyType': 'HASH'}]:
        raise Failure('Locking table must be ACTIVE with only the LockID partition key.')
    if {'AttributeName': 'LockID', 'AttributeType': 'S'} not in table['AttributeDefinitions']:
        raise Failure('LockID must have DynamoDB type S (String).')

def object_exists(meta, key):
    return aws('s3api', 'head-object', '--bucket', meta['bucket'], '--key', key,
               '--expected-bucket-owner', meta['account'], region=meta['region'],
               optional_codes=('404', 'NoSuchKey', 'NotFound')) is not None

def inspect_reused_state(meta, existing, eligible):
    """Read state without logging it; reject an unrelated state and retain subnet order."""
    if not object_exists(meta, meta['key']):
        if existing:
            raise Failure('Cluster exists but this backend key has no state. Recover the original state.')
        return None
    with tempfile.TemporaryDirectory(prefix='eks-state-check-') as directory:
        target = Path(directory) / 'state.json'
        target.touch(mode=0o600)
        aws('s3api', 'get-object', '--bucket', meta['bucket'], '--key', meta['key'],
            '--expected-bucket-owner', meta['account'], str(target), region=meta['region'])
        state = json.loads(target.read_text())
    expected_arn = f"arn:aws:eks:{meta['region']}:{meta['account']}:cluster/{meta['cluster_name']}"
    cluster_found = False
    subnet_zones = {}
    for resource in state.get('resources', []):
        if resource.get('mode') != 'managed':
            continue
        module = resource.get('module', '')
        if not any(module == prefix or module.startswith(prefix + '.') for prefix in ['module.vpc', 'module.eks']):
            raise Failure('This state has resources outside the original VPC/EKS modules. Review migration manually.')
        if resource['type'] == 'aws_eks_cluster':
            for instance in resource.get('instances', []):
                if instance['attributes'].get('arn') != expected_arn:
                    raise Failure('The backend state belongs to a different cluster/account/region.')
                cluster_found = True
        if module == 'module.vpc' and resource['type'] == 'aws_subnet' and resource['name'] in ['private', 'public']:
            for instance in resource.get('instances', []):
                index = instance.get('index_key')
                zone = instance['attributes'].get('availability_zone')
                if index not in [0, 1] or (index in subnet_zones and subnet_zones[index] != zone):
                    raise Failure('Existing subnet layout differs from this two-zone template. Review migration manually.')
                subnet_zones[index] = zone
    if existing and not cluster_found:
        raise Failure('The existing cluster is not recorded in this state. Do not apply against an unrelated state.')
    if subnet_zones:
        if set(subnet_zones) != {0, 1}:
            raise Failure('State has a partially created subnet layout. Recover it with the original configuration first.')
        ordered = [subnet_zones[0], subnet_zones[1]]
        if len(set(ordered)) != 2 or not set(ordered).issubset(eligible):
            raise Failure('Existing subnet zones are not eligible for this EKS/instance configuration. Review manually.')
        return ordered
    return None

def setup(reuse=None):
    values, meta, eligible = preflight()
    if meta and reuse:
        raise Failure('Backend selection is already recorded; rerun setup without --reuse-backend.')
    if not meta:
        if any((ROOT / p).exists() for p in ['terraform.tfstate', 'bootstrap/terraform.tfstate', 'generated.auto.tfvars.json']):
            raise Failure('Found earlier local setup artifacts without .setup.json. Recover them instead of creating a new backend.')
        if reuse:
            old = parse_backend(Path(reuse).expanduser().resolve())
            if old['region'] != values['aws_region']:
                raise Failure('Set settings.json aws_region to match the existing backend before setup.')
            meta = {'mode': 'reuse', 'bucket': old['bucket'], 'table': old['dynamodb_table'],
                    'key': old['key'], 'bootstrap_remote': True}
        else:
            name = f"eks-lab-tfstate-{values['expected_account_id']}-{values['aws_region']}-{secrets.token_hex(3)}"
            meta = {'mode': 'new', 'bucket': name, 'table': name + '-locks',
                    'key': 'eks-lab/infra/terraform.tfstate', 'bootstrap_remote': False}
        meta.update(account=values['expected_account_id'], region=values['aws_region'], cluster_name=values['cluster_name'])
        # Prevent a second unmanaged cluster/state from masquerading as the old one.
        existing = aws('eks', 'describe-cluster', '--name', values['cluster_name'], region=meta['region'],
                       optional_codes=('ResourceNotFoundException',))
        if existing and meta['mode'] == 'new':
            raise Failure('This cluster already exists. Reuse its original backend; do not create a new empty state for it.')
        if meta['mode'] == 'reuse':
            verify_backend(meta)
            old_zones = inspect_reused_state(meta, existing, eligible)
            if old_zones:
                values['availability_zones'] = old_zones
        write_json(ROOT / '.setup.json', meta)  # Save chosen names before any provisioning.
    print(f"Account: {meta['account']} | Region: {meta['region']} | Cluster: {values['cluster_name']}", flush=True)
    print(f"Administrator: {values['admin_principal_arn']} | API source: {values['admin_cidr']}", flush=True)
    write_json(ROOT / 'generated.auto.tfvars.json', values)
    if meta['mode'] == 'new':
        boot = ROOT / 'bootstrap'
        write_json(boot / 'generated.auto.tfvars.json', {
            'aws_region': meta['region'], 'expected_account_id': meta['account'],
            'state_bucket_name': meta['bucket'], 'lock_table_name': meta['table']})
        if not meta['bootstrap_remote']:
            if (boot / 'backend.tf').exists():
                raise Failure('An earlier migration did not finish. See docs/RECOVERY.md; no state will be overwritten.')
            tf(boot, 'init', '-input=false')
            tf(boot, 'validate')
            tf(boot, 'plan', '-input=false', '-lock-timeout=60s', '-out=bootstrap.tfplan')
            print('Creating the backend resources from the displayed saved plan; no EKS cluster is created by setup.', flush=True)
            tf(boot, 'apply', '-input=false', 'bootstrap.tfplan')
            verify_backend(meta)
            bootstrap_key = 'eks-lab/bootstrap/terraform.tfstate'
            if object_exists(meta, bootstrap_key):
                raise Failure('Destination bootstrap state already exists. Refusing automatic overwrite.')
            (boot / 'backend.tf').write_text(backend_text(meta, bootstrap_key))
            tf(boot, 'init', '-input=false', '-migrate-state', '-force-copy')
            meta['bootstrap_remote'] = True
            write_json(ROOT / '.setup.json', meta)
            (boot / 'bootstrap.tfplan').unlink(missing_ok=True)
        else:
            verify_backend(meta)
    else:
        verify_backend(meta)
    (ROOT / 'backend.tf').write_text(backend_text(meta, meta['key']))
    tf(ROOT, 'fmt', '-recursive')
    tf(ROOT, 'init', '-input=false')
    tf(ROOT, 'validate')
    (ROOT / '.setup-complete').write_text('Setup completed successfully.\n')
    print('Ready. From this folder run: bash run.sh plan, review the plan, then bash run.sh apply.', flush=True)

def ready():
    if not (ROOT / '.setup-complete').exists():
        raise Failure('Run bash run.sh setup first (or setup --reuse-backend PATH for the original backend).')
    meta = json.loads((ROOT / '.setup.json').read_text())
    identity = aws('sts', 'get-caller-identity', region=meta['region'])
    if identity['Account'] != meta['account']:
        raise Failure('Wrong AWS account. Restore the profile used during setup.')
    normalize = lambda text: re.sub(r'\s+', '', re.sub(r'#[^\n]*', '', text))
    if normalize((ROOT / 'backend.tf').read_text()) != normalize(backend_text(meta, meta['key'])):
        raise Failure('backend.tf changed since setup. Restore the recorded backend; do not switch state accidentally.')
    # Editing settings must regenerate inputs explicitly; never silently deploy stale inputs.
    settings = json.loads((ROOT / 'settings.json').read_text())
    current = json.loads((ROOT / 'generated.auto.tfvars.json').read_text())
    for name, value in settings.items():
        if value != 'auto' and current.get(name) != value:
            raise Failure('settings.json changed. Rerun setup to validate and regenerate values, then create a fresh plan.')
    return meta

def config_fingerprint():
    paths = {ROOT / 'settings.json', ROOT / '.terraform.lock.hcl'}
    for pattern in ['*.tf', '*.tf.json', '*.tfvars', '*.tfvars.json']:
        paths.update(ROOT.glob(pattern))
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.exists()}

def ensure_default_workspace():
    if ENV.get('TF_WORKSPACE', 'default') != 'default':
        raise Failure('This helper supports the default Terraform workspace only. Unset TF_WORKSPACE.')
    for folder in [ROOT, ROOT / 'bootstrap']:
        path = folder / '.terraform/environment'
        if path.exists() and path.read_text().strip() != 'default':
            raise Failure('A non-default Terraform workspace is selected. Stop and review state before continuing.')

def plan_has_deletes(plan):
    return any('delete' in r.get('change', {}).get('actions', []) for r in plan.get('resource_changes', []))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'init', 'plan', 'apply', 'validate', 'destroy-plan', 'destroy-apply'])
    parser.add_argument('--reuse-backend', metavar='PATH', help='Original infra/backend.hcl; only for the first setup.')
    parser.add_argument('--allow-replacements', action='store_true', help='Permit deletes/replacements in a reviewed normal apply plan.')
    args = parser.parse_args()
    if args.reuse_backend and args.action != 'setup':
        raise Failure('--reuse-backend is only for setup.')
    if args.allow_replacements and args.action != 'apply':
        raise Failure('--allow-replacements is only for a normal apply.')
    ensure_default_workspace()
    lock_path = ROOT / '.setup.lock'
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Failure('Another run.sh command is using this folder. Wait for it to finish.')
        if args.action == 'setup':
            setup(args.reuse_backend)
            return
        ready()
        if args.action == 'init':
            tf(ROOT, 'init', '-input=false')
        elif args.action == 'validate':
            tf(ROOT, 'validate')
        elif args.action in ['plan', 'destroy-plan']:
            filename = 'destroy.tfplan' if args.action == 'destroy-plan' else 'eks.tfplan'
            (ROOT / filename).unlink(missing_ok=True)  # A failed plan must not leave a stale executable plan.
            (ROOT / (filename + '.config.json')).unlink(missing_ok=True)
            flags = ['-destroy'] if args.action == 'destroy-plan' else []
            tf(ROOT, 'plan', '-input=false', '-lock-timeout=60s', *flags, '-out=' + filename)
            write_json(ROOT / (filename + '.config.json'), config_fingerprint())
        elif args.action in ['apply', 'destroy-apply']:
            filename = 'destroy.tfplan' if args.action == 'destroy-apply' else 'eks.tfplan'
            path = ROOT / filename
            if not path.exists():
                raise Failure('No saved plan. Run plan (or destroy-plan) and review it first.')
            stamp = ROOT / (filename + '.config.json')
            if not stamp.exists() or json.loads(stamp.read_text()) != config_fingerprint():
                raise Failure('Configuration changed or this plan was not made by run.sh. Create and review a fresh plan.')
            plan = json.loads(tf(ROOT, 'show', '-json', filename, capture=True))
            if args.action == 'apply' and plan_has_deletes(plan) and not args.allow_replacements:
                raise Failure('Plan includes a deletion/replacement. Review it; use apply --allow-replacements only if intended.')
            tf(ROOT, 'apply', '-input=false', '-lock-timeout=60s', filename)
            path.unlink()
            stamp.unlink()

if __name__ == '__main__':
    try:
        main()
    except (Failure, OSError, ValueError, KeyError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('Interrupted. Keep state and inspect a fresh plan before continuing.', file=sys.stderr)
        sys.exit(130)
