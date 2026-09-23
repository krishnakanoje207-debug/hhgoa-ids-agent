"""tg.load_file separator per file type (REST calls mocked)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hhg import tg


class LoadFileTest(unittest.TestCase):
    def test_sep_by_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            csv_p, txt_p = Path(d) / "a.csv", Path(d) / "b.txt"
            csv_p.write_bytes(b"id,x\n1,a\n2,b\n")
            txt_p.write_bytes(b"1|a\n2|b\n")
            with mock.patch.object(tg, "_send") as send:
                send.return_value.json.return_value = {"ok": True}
                self.assertEqual(tg.load_file("job", "f", csv_p), [{"ok": True}])
                tg.load_file("job", "f", txt_p)
        (_, kw_csv), (_, kw_txt) = [(c.args, c.kwargs) for c in send.call_args_list]
        self.assertEqual(kw_csv["params"]["sep"], ",")
        self.assertEqual(kw_txt["params"]["sep"], "|")
        self.assertEqual(kw_csv["data"], b"id,x\n1,a\n2,b\n")  # header kept on the csv piece
        self.assertEqual((kw_csv["params"]["tag"], kw_csv["params"]["filename"]), ("job", "f"))


if __name__ == "__main__":
    unittest.main()
