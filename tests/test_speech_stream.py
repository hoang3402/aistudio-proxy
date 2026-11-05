import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from browser_utils.speech import extract_audio_chunks  # noqa: E402


class ExtractAudioChunksTest(unittest.TestCase):
    def test_extracts_multiple_pairs_and_keeps_incomplete_tail(self) -> None:
        first = base64.b64encode(b"first").decode()
        second = base64.b64encode(b"second").decode()
        text = f'prefix["audio/l16; rate=24000; channels=1","{first}"]middle["audio/l16; rate=24000; channels=1","{second}'
        chunks, rest = extract_audio_chunks(text)
        self.assertEqual(chunks, [("audio/l16; rate=24000; channels=1", b"first")])
        self.assertIn('["audio/', rest)

    def test_recovers_pair_across_every_possible_split(self) -> None:
        pcm = b"\x00\x01\x02\xff" * 20
        encoded = base64.b64encode(pcm).decode()
        pair = f'[["audio/l16; rate=24000; channels=1","{encoded}"]]'
        for split in range(len(pair) + 1):
            chunks, rest = extract_audio_chunks(pair[:split])
            more, _ = extract_audio_chunks(rest + pair[split:])
            self.assertEqual(chunks + more, [("audio/l16; rate=24000; channels=1", pcm)], split)


if __name__ == "__main__":
    unittest.main()
