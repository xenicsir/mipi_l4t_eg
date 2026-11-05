#!/usr/bin/env python3
"""HW availability must not advertise experiments, hidden modes or untested boards."""
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from generate_deployment_matrix import DeploymentMatrixGenerator
class HardwareMatrixTests(unittest.TestCase):
 def setUp(self):self.g=DeploymentMatrixGenerator(ROOT/'tools/deployment_matrix_data.yaml')
 def test_only_integrated_version_is_enabled(self):
  for version in self.g.camera_db['versions']:
   value=self.g.get_hardware_pipeline('orin_nx_nano_devkit','microcube',version)
   self.assertEqual(value['available'],int(version.split('.')[0]) >= 35 and version != '35.1')
  self.assertTrue(self.g.get_hardware_pipeline('xavier_nx','smartir640','35.1')['available'])
  self.assertNotIn('Y14',self.g.get_hardware_pipeline('xavier_nx','ilumos','35.1')['formats'])
  self.assertFalse(self.g.get_hardware_pipeline('nano_t210','microcube','32.7.6')['available'])
 def test_formats_are_camera_specific_and_hidden_modes_stay_hidden(self):
  self.assertEqual(set(self.g.get_hardware_pipeline('orin_nx_nano_devkit','microcube','36.4.4')['formats']),{'RGB888','Y16','YUYV'})
  il=self.g.get_hardware_pipeline('orin_nx_nano_devkit','ilumos','36.4.4')
  self.assertEqual(set(il['formats']),{'Y16 -BE','Y14'})
  self.assertEqual(set(il['validations'][0]['formats']),{'Y16 -BE','Y14'})
  for resolution in self.g.camera_db['cameras']['ilumos']['resolutions']:
   for mode in resolution['modes']:
    if mode['pixel_format']=='Y14':mode['enabled']=False
  self.g._apply_enabled_flags()
  il=self.g.get_hardware_pipeline('orin_nx_nano_devkit','ilumos','36.4.4')
  self.assertEqual(il['formats'],['Y16 -BE'])
  self.assertEqual(il['validations'][0]['formats'],['Y16 -BE'])
 def test_camera_format_support_is_visible_without_hw_pipeline(self):
  self.g.camera_db['hardware_pipeline']['versions'].pop('35.6.1')
  value=self.g.get_hardware_pipeline('forecr_ornxs','ilumos','35.6.1')
  self.assertFalse(value['available'])
  self.assertEqual(set(value['camera_formats']),{'Y16 -BE','Y14'})
  text=self.g._hardware_cell_html('forecr_ornxs','ilumos','35.6.1')
  self.assertIn('Formats:',text);self.assertIn('Y14',text);self.assertIn('HW: No',text)
 def test_xavier_y14_keeps_camera_support_without_claiming_hw_preview(self):
  value=self.g.get_hardware_pipeline('xavier_nx','ilumos','35.6.0')
  self.assertIn('Y14',value['camera_formats'])
  self.assertNotIn('Y14',value['formats'])
  self.assertIn('Y16 -BE',value['formats'])
 def test_availability_is_not_target_qualification(self):
  value=self.g.get_hardware_pipeline('forecr_ornxs','microcube','36.4.4')
  self.assertTrue(value['available']);self.assertEqual(value['validations'],[])
  dione=self.g.get_hardware_pipeline('orin_nx_nano_devkit','dione_ir','36.4.4')
  self.assertTrue(dione['available']);self.assertEqual(dione['validations'][0]['result'],'issues')
  self.assertEqual(dione['validations'][0]['resolution'],'1280x1024')
 def test_pristine_restrictions_apply_even_when_feature_is_declared(self):
  self.g.camera_db['hardware_pipeline']['versions']['36.5.0']={'formats':['RGB888','YUYV','Y16','Y14','Y16 -BE']}
  value=self.g.get_hardware_pipeline('cti_hadron_dm_pristine','microcube','36.5.0')
  self.assertEqual(set(value['formats']),{'RGB888','YUYV'})
  self.assertFalse(self.g.get_hardware_pipeline('cti_hadron_dm_pristine','ilumos','36.5.0')['available'])
 def test_disabled_model_has_no_hw_or_validation_rows(self):
  self.g.camera_db['cameras'].pop('microcube');self.g.cameras_by_id.pop('microcube')
  self.assertFalse(self.g.get_hardware_pipeline('orin_nx_nano_devkit','microcube','36.4.4')['available'])
  self.assertFalse(any(r[2]=='MicroCube' for r in self.g.hardware_validation_rows()))
 def test_source_declaration_drift_is_rejected(self):
  self.g.camera_db['hardware_pipeline']['versions'].pop('35.6.1')
  self.assertTrue(any('35.6.1' in e and 'disagree' in e for e in self.g.validate()))
 def test_all_declared_nonlegacy_bsps_have_sources_without_new_hw_claims(self):
  expected={v for v in self.g.camera_db['versions'] if int(v.split('.')[0])>=35}
  self.assertEqual(set(self.g.camera_db['hardware_pipeline']['versions']),expected)
  for version in ('35.3.1','35.5.0','35.6.1','35.6.2','36.4','36.4.3','36.5.0','36.5.2','39.2.1'):
   value=self.g.get_hardware_pipeline('orin_nx_nano_devkit','microcube',version)
   self.assertTrue(value['available']);self.assertEqual(value['validations'],[])
  for version in expected:
   if version.startswith('35.'):
    self.assertEqual(self.g.camera_db['hardware_pipeline']['versions'][version]['unsupported_formats']['xavier_nx'],['Y14'])
 def test_all_renderers_include_explicit_hw_and_qualification(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);self.g.generate_markdown(p/'matrix.md');self.g.generate_html(p/'matrix.html')
   outputs=[(p/'matrix.md').read_text(),(p/'matrix.html').read_text(),self.g._generate_pdf_html()]
   for text in outputs:
    self.assertIn('HW: Yes',text);self.assertIn('HW: No',text)
    self.assertIn('HW formats checked',text);self.assertIn('Issues observed',text)
    self.assertIn('Orin Nano / NVIDIA P3768',text)
if __name__=='__main__':unittest.main()
