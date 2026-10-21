"""Sequence adapter regression: reject a label-only sequence change."""
import tempfile
from pathlib import Path
import unittest

from run_effective_collection import sequence_inputs


class SequenceInputs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'source'
        self.source.mkdir()
        self.data=self.root/'V1_02_medium'
        self.data.mkdir()
        gt=self.data/'mav0/state_groundtruth_estimate0'
        gt.mkdir(parents=True)
        (gt/'data.csv').write_text('#timestamp\n100,0\n101,0\n102,0\n103,0\n104,0\n')
        (self.source/'times.txt').write_text('101\n102\n103\n')
        (self.source/'settings.yaml').write_text('test')
        for cam in ('cam0','cam1'):
            folder=self.data/'mav0'/cam/'data'
            folder.mkdir(parents=True)
            for stamp in ('102','103'):
                (folder/(stamp+'.png')).write_bytes(b'image')
        self.cfg=dict(sequence='V1_02_medium',timestamps='times.txt',settings='settings.yaml',
                      offset=1,preload_limit=2,evaluation_frames=1,initialization_limit=1,
                      quality={'ground_truth_coverage_min':.99})

    def test_correct_segment_hashes_both_cameras(self):
        timestamps,settings,images=sequence_inputs(self.source,self.data,self.cfg)
        self.assertEqual(timestamps,self.source/'times.txt')
        self.assertEqual(settings,self.source/'settings.yaml')
        self.assertEqual(len(images),4)

    def test_label_without_corresponding_timestamps_rejected(self):
        self.cfg.pop('timestamps')
        with self.assertRaisesRegex(ValueError,'explicit timestamps'):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_wrong_sequence_directory_rejected(self):
        self.cfg['sequence']='V1_01_easy'
        with self.assertRaisesRegex(ValueError,'directory'):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_truncated_segment_rejected(self):
        self.cfg['offset']=2
        with self.assertRaisesRegex(ValueError,'exceeds'):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_missing_stereo_partner_rejected(self):
        (self.data/'mav0/cam1/data/103.png').unlink()
        with self.assertRaises(FileNotFoundError):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_initialization_reserve_required(self):
        self.cfg['initialization_limit']=2
        with self.assertRaisesRegex(ValueError,'initialization'):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_missing_ground_truth_rejected_before_replay(self):
        (self.data/'mav0/state_groundtruth_estimate0/data.csv').write_text('104,0\n105,0\n')
        with self.assertRaisesRegex(ValueError,'ground truth'):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_interval_cannot_exclude_every_frame(self):
        self.cfg['quality_interval']={'start_k':1,'end_k':1}
        with self.assertRaisesRegex(ValueError,'scoring interval'):
            sequence_inputs(self.source,self.data,self.cfg)

    def test_default_and_explicit_full_interval_match(self):
        before=sequence_inputs(self.source,self.data,self.cfg)
        self.cfg['quality_interval']={'start_k':0,'end_k':1}
        self.assertEqual(before,sequence_inputs(self.source,self.data,self.cfg))


if __name__=='__main__':
    unittest.main()
