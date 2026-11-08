import tempfile
import unittest
from pathlib import Path
from recognition_markers import build_markers, director_report, export_report

class RecognitionTests(unittest.TestCase):
    def test_audio_peak_is_not_a_gunshot(self):
        markers=build_markers([], [{'time':3.0,'event':'gunshot','strength':.8}])
        self.assertEqual(markers[0]['event'],'audio_transient')
        self.assertFalse(markers[0]['verified'])
    def test_correlation_does_not_invent_kills(self):
        markers=build_markers([{'time':5,'event':'combat','confidence':.75}], [{'time':6,'strength':.9}])
        self.assertTrue(markers[0]['audio_correlated'])
        self.assertFalse(any(m['event']=='kill' for m in markers))
    def test_report_and_export(self):
        markers=build_markers([{'time':12,'event':'looting','confidence':.8}],[])
        self.assertIn('00:00:12',director_report(markers))
        with tempfile.TemporaryDirectory() as d:
            dest=export_report(Path(d)/'markers.json','example.mp4','qwen3-vl:2b',markers)
            self.assertTrue(dest.exists())
            self.assertIn('"training_applied": false',dest.read_text())

if __name__=='__main__':unittest.main()
