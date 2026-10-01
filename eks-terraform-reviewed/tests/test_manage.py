"""Offline checks for safeguards and orchestration; no AWS resources are created."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('manage', Path(__file__).resolve().parents[1] / 'scripts/manage.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ACCOUNT = '123456789012'
ARN = f'arn:aws:iam::{ACCOUNT}:role/team/Admin'
IDENTITY = {'Account': ACCOUNT, 'Arn': ARN}
SETTINGS = dict(aws_region='us-east-1', cluster_name='eks-lab', kubernetes_version='1.35',
                node_instance_type='t3.medium', admin_cidr='auto', admin_principal_arn='auto')
VALUES = dict(SETTINGS, expected_account_id=ACCOUNT, admin_cidr='8.8.8.8/32',
              admin_principal_arn=ARN, availability_zones=['us-east-1a', 'us-east-1b'])
META = dict(mode='reuse', account=ACCOUNT, region='us-east-1', cluster_name='eks-lab',
            bucket='example-state-bucket', table='example-locks', key='eks-lab/infra/terraform.tfstate', bootstrap_remote=True)
ZONES = [dict(ZoneName='us-east-1' + letter, ZoneId='use1-az' + str(number), State='available',
              ZoneType='availability-zone') for letter, number in [('a', 1), ('b', 2), ('c', 3), ('d', 4)]]
OFFERINGS = [{'Location': z['ZoneName']} for z in ZONES]

class ManageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'bootstrap').mkdir()
        (self.root / 'settings.json').write_text(json.dumps(SETTINGS))
        (self.root / 'main.tf').write_text('# configuration\n')
        self.root_patch = patch.object(m, 'ROOT', self.root)
        self.root_patch.start()
        self.env_patch = patch.dict(m.ENV, {'TF_WORKSPACE': 'default'})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    def test_sso_role_path_is_resolved(self):
        actual = f'arn:aws:iam::{ACCOUNT}:role/aws-reserved/sso.amazonaws.com/eu-west-1/AWSReservedSSO_Admin_test'
        identity = dict(IDENTITY, Arn=f'arn:aws:sts::{ACCOUNT}:assumed-role/AWSReservedSSO_Admin_test/person')
        with patch.object(m, 'aws', return_value={'Role': {'Arn': actual}}):
            self.assertEqual(m.principal(identity), actual)

    def test_wrong_account_arn_is_rejected(self):
        with self.assertRaises(m.Failure):
            m.principal(IDENTITY, 'arn:aws:iam::999999999999:role/Admin')

    def test_explicit_session_and_root_arns_are_rejected(self):
        for arn in [f'arn:aws:sts::{ACCOUNT}:assumed-role/Admin/session', f'arn:aws:iam::{ACCOUNT}:root']:
            with self.subTest(arn=arn), self.assertRaises(m.Failure):
                m.principal(IDENTITY, arn)

    def test_wrong_role_path_is_rejected(self):
        with patch.object(m, 'aws', return_value={'Role': {'Arn': f'arn:aws:iam::{ACCOUNT}:role/other/Admin'}}):
            with self.assertRaises(m.Failure):
                m.principal(IDENTITY)

    def test_service_linked_role_is_rejected(self):
        with self.assertRaises(m.Failure):
            m.principal(IDENTITY, f'arn:aws:iam::{ACCOUNT}:role/aws-service-role/eks.amazonaws.com/AWSServiceRoleForAmazonEKS')

    def test_invalid_endpoint_ranges_are_rejected(self):
        for cidr in ['0.0.0.0/0', '10.0.0.1/32', '203.0.113.1/32', '::1/128', '8.8.8.0/24']:
            with self.subTest(cidr=cidr), self.assertRaises(m.Failure):
                m.public_cidr(cidr)
        self.assertEqual(m.public_cidr('8.8.8.8/32'), '8.8.8.8/32')

    def test_ip_detection_has_timeout_and_ipv4(self):
        with patch.object(m, 'execute', return_value='8.8.8.8\n') as call:
            self.assertEqual(m.public_cidr('auto'), '8.8.8.8/32')
            self.assertIn('-4', call.call_args.args[0])
            self.assertIn('--max-time', call.call_args.args[0])

    def test_unsupported_az_and_missing_offering_are_excluded(self):
        offered = [o for o in OFFERINGS if o['Location'] != 'us-east-1a']
        self.assertEqual(m.select_zones(ZONES, offered), ['us-east-1b', 'us-east-1d'])

    def test_one_eligible_zone_is_rejected(self):
        with self.assertRaises(m.Failure):
            m.select_zones(ZONES, OFFERINGS[:1])

    def test_backend_parser_requires_original_key(self):
        p = self.root / 'backend.hcl'
        fields = {'bucket': META['bucket'], 'region': META['region'], 'key': META['key'],
                  'dynamodb_table': META['table'], 'encrypt': True}
        p.write_text('\n'.join(f'{k} = {json.dumps(v)}' for k, v in fields.items()))
        self.assertEqual(m.parse_backend(p)['bucket'], META['bucket'])
        fields['key'] = 'wrong/terraform.tfstate'
        p.write_text('\n'.join(f'{k} = {json.dumps(v)}' for k, v in fields.items()))
        with self.assertRaises(m.Failure):
            m.parse_backend(p)

    def test_backend_parser_rejects_duplicate_and_interpolation(self):
        p = self.root / 'backend.hcl'
        for text in ['bucket = var.bucket', 'bucket = "one"\nbucket = "two"']:
            p.write_text(text)
            with self.assertRaises(m.Failure):
                m.parse_backend(p)

    def test_backend_checks_region_and_lock_key(self):
        good_table = {'Table': {'TableStatus': 'ACTIVE', 'KeySchema': [{'AttributeName': 'LockID', 'KeyType': 'HASH'}],
                                'AttributeDefinitions': [{'AttributeName': 'LockID', 'AttributeType': 'S'}]}}
        with patch.object(m, 'aws', side_effect=[{}, {'LocationConstraint': None}, good_table]):
            m.verify_backend(META)
        with patch.object(m, 'aws', side_effect=[{}, {'LocationConstraint': 'eu-west-1'}]):
            with self.assertRaises(m.Failure):
                m.verify_backend(META)
        bad = json.loads(json.dumps(good_table))
        bad['Table']['AttributeDefinitions'][0]['AttributeType'] = 'N'
        with patch.object(m, 'aws', side_effect=[{}, {'LocationConstraint': None}, bad]):
            with self.assertRaises(m.Failure):
                m.verify_backend(META)

    def state_aws(self, state):
        def fake(*args, **kwargs):
            if args[:2] == ('s3api', 'get-object'):
                Path(args[-1]).write_text(json.dumps(state))
                return {}
            self.fail('Unexpected AWS call')
        return fake

    def test_reuse_preserves_existing_subnet_order(self):
        state = {'resources': [dict(mode='managed', module='module.vpc', type='aws_subnet', name='private', instances=[
            {'index_key': 0, 'attributes': {'availability_zone': 'us-east-1d'}},
            {'index_key': 1, 'attributes': {'availability_zone': 'us-east-1a'}}]) ]}
        with patch.object(m, 'object_exists', return_value=True), patch.object(m, 'aws', side_effect=self.state_aws(state)):
            self.assertEqual(m.inspect_reused_state(META, None, ['us-east-1a', 'us-east-1b', 'us-east-1d']),
                             ['us-east-1d', 'us-east-1a'])

    def test_unrelated_remote_cluster_is_rejected(self):
        state = {'resources': [dict(mode='managed', module='module.eks', type='aws_eks_cluster', name='this',
                                   instances=[{'attributes': {'arn': 'arn:aws:eks:us-east-1:999999999999:cluster/other'}}])]}
        with patch.object(m, 'object_exists', return_value=True), patch.object(m, 'aws', side_effect=self.state_aws(state)):
            with self.assertRaises(m.Failure):
                m.inspect_reused_state(META, {'cluster': {}}, VALUES['availability_zones'])

    def test_existing_cluster_without_state_is_rejected(self):
        with patch.object(m, 'object_exists', return_value=False):
            with self.assertRaises(m.Failure):
                m.inspect_reused_state(META, {'cluster': {}}, VALUES['availability_zones'])

    def fake_preflight_aws(self, status):
        def fake(*args, **kwargs):
            action = args[:2]
            return {
                ('sts', 'get-caller-identity'): IDENTITY,
                ('eks', 'describe-cluster-versions'): {'clusterVersions': [dict(clusterVersion='1.35', **status)]},
                ('ec2', 'describe-instance-types'): {'InstanceTypes': [{'ProcessorInfo': {'SupportedArchitectures': ['x86_64']}}]},
                ('ec2', 'describe-availability-zones'): {'AvailabilityZones': ZONES},
                ('ec2', 'describe-instance-type-offerings'): {'InstanceTypeOfferings': OFFERINGS},
            }[action]
        return fake

    def test_preflight_accepts_both_aws_support_status_formats(self):
        for status in [{'status': 'standard-support'}, {'versionStatus': 'STANDARD_SUPPORT', 'status': 'standard-support'}]:
            with self.subTest(status=status), patch.object(m.shutil, 'which', return_value='/usr/bin/tool'), \
                    patch.object(m, 'execute', return_value='{"terraform_version":"1.13.5"}'), \
                    patch.object(m, 'principal', return_value=ARN), patch.object(m, 'public_cidr', return_value='8.8.8.8/32'), \
                    patch.object(m, 'aws', side_effect=self.fake_preflight_aws(status)):
                values, meta, eligible = m.preflight()
                self.assertEqual(values['availability_zones'], ['us-east-1a', 'us-east-1b'])
                self.assertIsNone(meta)

    def test_setup_orders_bootstrap_creation_migration_then_root_init(self):
        calls = []
        with patch.object(m, 'preflight', return_value=(dict(VALUES), None, VALUES['availability_zones'])), \
                patch.object(m, 'aws', return_value=None), patch.object(m, 'verify_backend'), \
                patch.object(m, 'object_exists', return_value=False), \
                patch.object(m, 'tf', side_effect=lambda *a, **k: calls.append(a)):
            m.setup()
        apply_index = next(i for i, a in enumerate(calls) if a[1] == 'apply')
        migrate_index = next(i for i, a in enumerate(calls) if '-migrate-state' in a)
        root_init_index = next(i for i, a in enumerate(calls) if a[0] == self.root and a[1] == 'init')
        self.assertLess(apply_index, migrate_index)
        self.assertLess(migrate_index, root_init_index)
        self.assertTrue((self.root / '.setup-complete').exists())
        self.assertTrue(json.loads((self.root / '.setup.json').read_text())['bootstrap_remote'])
        self.assertFalse(any(a[0] == self.root and a[1] == 'apply' for a in calls))

    def test_new_setup_refuses_existing_cluster(self):
        with patch.object(m, 'preflight', return_value=(dict(VALUES), None, VALUES['availability_zones'])), \
                patch.object(m, 'aws', return_value={'cluster': {}}), patch.object(m, 'tf') as terraform:
            with self.assertRaises(m.Failure):
                m.setup()
            terraform.assert_not_called()

    def test_failed_migration_does_not_mark_setup_complete(self):
        def terraform(folder, *args, **kwargs):
            if '-migrate-state' in args:
                raise m.Failure('migration failed')
        with patch.object(m, 'preflight', return_value=(dict(VALUES), None, VALUES['availability_zones'])), \
                patch.object(m, 'aws', return_value=None), patch.object(m, 'verify_backend'), \
                patch.object(m, 'object_exists', return_value=False), patch.object(m, 'tf', side_effect=terraform):
            with self.assertRaises(m.Failure):
                m.setup()
        self.assertFalse((self.root / '.setup-complete').exists())
        self.assertFalse(json.loads((self.root / '.setup.json').read_text())['bootstrap_remote'])

    def test_retry_after_interrupted_migration_stops_before_apply(self):
        (self.root / 'bootstrap/backend.tf').write_text('existing migration')
        with patch.object(m, 'preflight', return_value=(dict(VALUES), dict(META, mode='new', bootstrap_remote=False), VALUES['availability_zones'])), \
                patch.object(m, 'tf') as terraform:
            with self.assertRaises(m.Failure):
                m.setup()
            terraform.assert_not_called()

    def call_main(self, action, terraform):
        with patch.object(m.sys, 'argv', ['manage.py', action]), patch.object(m, 'ready'), patch.object(m, 'tf', side_effect=terraform):
            m.main()

    def save_plan(self):
        (self.root / 'eks.tfplan').write_text('offline test plan')
        m.write_json(self.root / 'eks.tfplan.config.json', m.config_fingerprint())

    def test_changed_configuration_cannot_apply_old_plan(self):
        self.save_plan()
        (self.root / 'main.tf').write_text('changed')
        with self.assertRaises(m.Failure):
            self.call_main('apply', lambda *a, **k: self.fail('Terraform must not run'))

    def test_replacement_requires_explicit_opt_in(self):
        self.save_plan()
        changes = json.dumps({'resource_changes': [{'change': {'actions': ['delete', 'create']}}]})
        with self.assertRaises(m.Failure):
            self.call_main('apply', lambda *a, **k: changes if a[1] == 'show' else self.fail('Apply must not run'))

    def test_saved_plan_apply_does_not_prompt(self):
        self.save_plan()
        calls = []
        def terraform(*args, **kwargs):
            calls.append(args)
            return '{}' if args[1] == 'show' else ''
        self.call_main('apply', terraform)
        self.assertIn((self.root, 'apply', '-input=false', '-lock-timeout=60s', 'eks.tfplan'), calls)
        self.assertFalse((self.root / 'eks.tfplan').exists())

    def test_failed_plan_removes_previous_executable_plan(self):
        self.save_plan()
        def terraform(*args, **kwargs):
            raise m.Failure('plan failed')
        with self.assertRaises(m.Failure):
            self.call_main('plan', terraform)
        self.assertFalse((self.root / 'eks.tfplan').exists())
        self.assertFalse((self.root / 'eks.tfplan.config.json').exists())

    def test_wrong_account_blocks_commands(self):
        (self.root / '.setup-complete').touch()
        m.write_json(self.root / '.setup.json', META)
        with patch.object(m, 'aws', return_value=dict(IDENTITY, Account='999999999999')):
            with self.assertRaises(m.Failure):
                m.ready()

    def test_nondefault_workspace_is_rejected(self):
        with patch.dict(m.ENV, {'TF_WORKSPACE': 'prod'}):
            with self.assertRaises(m.Failure):
                m.ensure_default_workspace()

if __name__ == '__main__':
    unittest.main()
