import tempfile
import unittest
from pathlib import Path
from ncs_import import import_track
from music_intelligence import scan_library, choose_track

class NCSImportTest(unittest.TestCase):
    def test_import_and_selection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            sample=root/'sample.ogg'
            sample.write_bytes(b'fake-test-audio')
            dest=import_track(sample,'On & On','Cartoon & Jéja','Test credits',root/'collection')
            tracks=scan_library(root/'collection',limit=20)
            self.assertEqual(len(tracks),1)
            self.assertEqual(tracks[0]['title'],'On & On')
            self.assertEqual(tracks[0]['credit'],'Test credits')
            self.assertEqual(choose_track(tracks,'please add On & On')['path'],dest)
            self.assertEqual(choose_track(tracks,'add ncs music')['path'],dest)
if __name__=='__main__': unittest.main()
