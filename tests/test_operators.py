import unittest
from clinforge.operators import find_phi,mask_phi,parse_labs,extract_complaint,similarity,pseudo_id,deduplicate,process_record

class OperatorsTest(unittest.TestCase):
    def test_phi_chinese(self):
        text='姓名：李若青；电话：13800001234；病历号：SYNHOSP-000003。'
        spans=find_phi(text)
        self.assertEqual([s.label for s in spans],['NAME','PHONE','MRN'])
        masked=mask_phi(text,spans)
        for val in ('李若青','13800001234','SYNHOSP-000003'):
            self.assertNotIn(val,masked)
        self.assertIn('[NAME]',masked)
        self.assertIn('[PHONE]',masked)
    def test_phi_english(self):
        text='Patient: Alex Taylor | Tel: 138-0000-1234 | MRN: EDTEST-000014'
        self.assertEqual({s.label for s in find_phi(text)},{'NAME','PHONE','MRN'})
    def test_phi_conservative_scope(self):
        self.assertEqual(find_phi('Name=Alex Taylor | Contact=138.0000.1234 | ChartNo=EDTEST-42'),[])
    def test_norm_temp_f(self):
        labs,issues=parse_labs('T=98.6°F; GLU=180.182mg/dL; Hb=12.3g/dL; ALT=52U/L')
        self.assertAlmostEqual(labs['temp_c'],37,places=3)
        self.assertAlmostEqual(labs['glucose_mmol_l'],10,places=3)
        self.assertAlmostEqual(labs['hemoglobin_g_l'],123,places=3)
        self.assertEqual(labs['alt_u_l'],52)
        self.assertEqual(issues,[])
    def test_ranges_quarantine(self):
        labs,issues=parse_labs('体温：280℃；血糖：9.5mmol/L')
        self.assertNotIn('temp_c',labs)
        self.assertIn('OUT_OF_BROAD_RANGE_TEMP_C',issues)
    def test_multiple_same_lab_quarantine(self):
        labs,issues=parse_labs('血糖：6.0mmol/L; GLU=12mg/dL')
        self.assertNotIn('glucose_mmol_l',labs)
        self.assertIn('AMBIGUOUS_MULTIPLE_GLUCOSE_MMOL_L',issues)
    def test_lab_alias_substrings_not_fields(self):
        labs,issues=parse_labs('SALT=42U/L; nonGLU=5mmol/L; notT=37℃; noHb=120g/L')
        self.assertEqual(labs,{})
        self.assertEqual(issues,[])
    def test_complaint(self):
        self.assertEqual(extract_complaint('主诉：胸闷三天；体温：37℃'),'胸闷三天')
    def test_doc_same_punctuation(self):
        a='姓名：李若青；主诉：腹痛一天。'
        b='姓名:李若青;主诉:腹痛一天'
        self.assertGreater(similarity(a,b),.95)
    def test_doc_different(self):
        self.assertLess(similarity('腹痛三天 胸闷','皮肤瘙痒 药物过敏'),.5)
    def test_hmac_not_raw(self):
        a=pseudo_id('record01','not-secret-demo-456')
        self.assertEqual(a,pseudo_id('record01','not-secret-demo-456'))
        self.assertNotIn('record01',a)
        self.assertNotEqual(a,pseudo_id('record02','not-secret-demo-456'))
    def test_hmac_short_key_refused(self):
        with self.assertRaises(ValueError):pseudo_id('r','short')
    def test_cross_patient_not_merged(self):
        a={'record_id':'1','patient_group':'p1','encounter_group':'e1','text':'姓名：张若安；电话：13800001111；主诉：头痛；体温：37℃'}
        b=dict(a,record_id='2',patient_group='p2',encounter_group='e1')
        rows=[process_record(x,'not-secret-demo-456') for x in [a,b]]
        deduplicate(rows)
        self.assertIsNone(rows[1]['duplicate_of'])
    def test_same_patient_different_encounter_not_merged(self):
        a={'record_id':'1','patient_group':'p1','encounter_group':'enc1','text':'姓名：张若安；电话：13800001111；主诉：头痛；体温：37℃'}
        b=dict(a,record_id='2',encounter_group='enc2')
        rows=[process_record(x,'not-secret-demo-456') for x in (a,b)]
        deduplicate(rows)
        self.assertIsNone(rows[1]['duplicate_of'])
    def test_same_patient_merged(self):
        a={'record_id':'1','patient_group':'p1','encounter_group':'e1','text':'姓名：张若安；电话：13800001111；主诉：头痛；体温：37℃'}
        b=dict(a,record_id='2')
        rows=[process_record(x,'not-secret-demo-456') for x in [a,b]]
        deduplicate(rows)
        self.assertEqual(rows[1]['duplicate_of'],rows[0]['record_key'])
    def test_lab_updates_not_duplicates(self):
        a={'record_id':'1','patient_group':'p1','encounter_group':'e1',
           'text':'Complaint: headache for three days | T=37°C; GLU=5.0mmol/L; Hb=120g/L; ALT=50U/L'}
        b=dict(a,record_id='2',text=a['text'].replace('5.0mmol/L','25.0mmol/L'))
        rows=[process_record(x,'not-secret-demo-456') for x in (a,b)]
        self.assertGreater(similarity(rows[0]['masked_text'],rows[1]['masked_text']),.82)
        deduplicate(rows)
        self.assertIsNone(rows[1]['duplicate_of'])
        self.assertEqual(rows[1]['status'],'accepted')
    def test_changed_complaint_not_duplicate(self):
        a={'record_id':'1','patient_group':'p1','encounter_group':'e1',
           'text':'Complaint: headache for three days | T=37°C; GLU=5.0mmol/L; Hb=120g/L; ALT=50U/L'}
        b=dict(a,record_id='2',text=a['text'].replace('headache','chest pain'))
        rows=[process_record(x,'not-secret-demo-456') for x in (a,b)]
        deduplicate(rows)
        self.assertIsNone(rows[1]['duplicate_of'])
    def test_process_record_requires_object_and_nonempty_ids(self):
        for row in ([],None,{}, {'record_id':' ', 'patient_group':'p','encounter_group':'e','text':'text'}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                process_record(row,'not-secret-demo-456')
    def test_score_nonclinical(self):
        record=process_record({'record_id':'1','patient_group':'p','encounter_group':'e','text':'姓名：张若安；主诉：头痛；体温：37℃'},'not-secret-demo-456')
        self.assertTrue(0<=record['quality_score']<=1)

if __name__=='__main__':unittest.main()
