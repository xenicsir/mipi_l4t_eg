#!/usr/bin/env python3
"""Contract checks for release scope, physical constraints and artifact identity."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from generate_deployment_matrix import DeploymentMatrixGenerator
from plan_release_validation import generate
from check_release_scope import identity_issue, package_targets
from test_matrix import generate_matrix
import test_matrix

class ReleaseTests(unittest.TestCase):
 def setUp(self):
  self.matrix=DeploymentMatrixGenerator(ROOT/'tools/deployment_matrix_data.yaml')
  self.inventory=yaml.safe_load((ROOT/'test/hardware/release_inventory.yaml').read_text())
 def test_plan_covers_inventory_and_ports_with_declared_versions_only(self):
  plan=generate(self.matrix,self.inventory)
  self.assertEqual(plan['coverage']['camera_models'],9);self.assertEqual(plan['coverage']['physical_ports'],14)
  self.assertLessEqual(plan['costs']['nominal_days'],3)
  self.assertTrue(all(v['l4t'] in self.matrix.camera_db['versions'] for v in plan['visits']))
 def test_disabled_camera_is_explicitly_excluded_from_release_schedule(self):
  self.matrix.camera_db['cameras'].pop('microlynx')
  plan=generate(self.matrix,self.inventory)
  self.assertIn('microlynx',plan['coverage']['excluded_inventory_models'])
  self.assertFalse(any(c['id']=='microlynx' for v in plan['visits'] for c in v['cameras']))
 def test_shared_supply_conflict_is_rejected(self):
  self.inventory['visits'].append(dict(wave=1,board='orin',track='base',cameras={0:'microlynx'}))
  with self.assertRaisesRegex(ValueError,'power conflict'):generate(self.matrix,self.inventory)
 def test_missing_camera_and_out_of_range_port_cannot_be_hidden(self):
  self.inventory['visits'][0]['cameras'][2]='microcube'
  with self.assertRaisesRegex(ValueError,'Port outside'):generate(self.matrix,self.inventory)
 def test_latest_track_follows_newly_declared_support(self):
  cfg=copy.deepcopy(self.matrix.camera_db['versions']['39.2']);self.matrix.camera_db['versions']['40.1']=cfg
  plan=generate(self.matrix,self.inventory)
  self.assertEqual({v['l4t'] for v in plan['visits'] if v['board']=='orin' and v['wave']>=3},{'40.1'})
 def test_hadron_vendor_kernel_has_explicit_limits(self):
  self.assertEqual(self.matrix.get_versions_for_platform(self.matrix.platforms_by_id['cti_hadron_dm']),['36.5.0'])
  self.assertEqual(self.matrix.get_status('cti_hadron_dm_pristine','ilumos','36.5.0')[0],'not_supported')
  self.assertIsNone(self.matrix.get_status('cti_hadron_dm','dione_ir','39.2')[0])
 def test_vendor_packages_are_not_tested_on_unrelated_nvidia_fixtures(self):
  entries=list(generate_matrix());self.assertTrue(entries)
  self.assertTrue(all(e.vendor=='forecr' if e.is_forecr else e.vendor=='generic' for e in entries))
  self.assertTrue(all('Linux_for_Tegra_forecr_dsboard_ornxs' in e.dtbo_boot_dir for e in entries if e.is_forecr))
 def test_new_supported_bsp_without_test_mapping_is_not_silently_skipped(self):
  with patch.object(test_matrix,'_load_yaml',side_effect=[{'versions':{'99.1':{}}},{'platforms':{},'mode_fallback':{}}]):
   with self.assertRaisesRegex(ValueError,'No test mode'):list(generate_matrix())
 def test_artifact_revision_architecture_and_name_are_verified(self):
  config=yaml.safe_load((ROOT/'eg_config.yaml').read_text());targets=list(package_targets(config))
  self.assertEqual(len(targets),len({t['package'] for t in targets}));t=targets[0]
  self.assertIsNone(identity_issue(t,[t['package'],'0~develop+g1234567','arm64'],'123456789abcdef'))
  self.assertIsNotNone(identity_issue(t,[t['package'],'0~develop+gabcdef0','arm64'],'123456789abcdef'))
  self.assertIsNotNone(identity_issue(t,[t['package'],'0~develop+g1234567','amd64'],'123456789abcdef'))
 def test_qemu_cannot_be_silently_skipped_in_release_mode(self):
  with tempfile.TemporaryDirectory() as tmp:
   docker=Path(tmp)/'docker';docker.write_text('#!/bin/sh\nexit 1\n');docker.chmod(0o755)
   import os
   env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],EG_RELEASE_TESTS='1')
   p=subprocess.run(['bash',str(ROOT/'test/qemu_install/run_all.sh'),'--no-build'],env=env,capture_output=True,text=True)
   self.assertNotEqual(p.returncode,0);self.assertIn('Release validation requires Phase 3',p.stdout)
 def test_empty_package_directory_fails(self):
  spec=importlib.util.spec_from_file_location('packages',ROOT/'test/integration/check_packages.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  with tempfile.TemporaryDirectory() as tmp,patch.object(mod,'REPO_ROOT',Path(tmp)),patch.object(mod,'get_commit_order',return_value=[]):
   self.assertEqual(mod.main(),1)
if __name__=='__main__':unittest.main()
