#!/usr/bin/env python3
import shutil
import tempfile
import os
import unittest
import pytest
import requests

from parameterized import parameterized
from unittest import mock

from openpilot.tools.lib.logreader import LogIterable, LogReader, comma_api_source, parse_indirect, ReadMode
from openpilot.tools.lib.route import SegmentRange

NUM_SEGS = 17  # number of segments in the test route
ALL_SEGS = list(range(NUM_SEGS))
TEST_ROUTE = "344c5c15b34f2d8a/2024-01-03--09-37-12"
QLOG_FILE = "https://commadataci.blob.core.windows.net/openpilotci/0375fdf7b1ce594d/2019-06-13--08-32-25/3/qlog.bz2"


def noop(segment: LogIterable):
  return segment


class TestLogReader(unittest.TestCase):
  @parameterized.expand([
    (f"{TEST_ROUTE}", ALL_SEGS),
    (f"{TEST_ROUTE.replace('/', '|')}", ALL_SEGS),
    (f"{TEST_ROUTE}--0", [0]),
    (f"{TEST_ROUTE}--5", [5]),
    (f"{TEST_ROUTE}/0", [0]),
    (f"{TEST_ROUTE}/5", [5]),
    (f"{TEST_ROUTE}/0:10", ALL_SEGS[0:10]),
    (f"{TEST_ROUTE}/0:0", []),
    (f"{TEST_ROUTE}/4:6", ALL_SEGS[4:6]),
    (f"{TEST_ROUTE}/0:-1", ALL_SEGS[0:-1]),
    (f"{TEST_ROUTE}/:5", ALL_SEGS[:5]),
    (f"{TEST_ROUTE}/2:", ALL_SEGS[2:]),
    (f"{TEST_ROUTE}/2:-1", ALL_SEGS[2:-1]),
    (f"{TEST_ROUTE}/-1", [ALL_SEGS[-1]]),
    (f"{TEST_ROUTE}/-2", [ALL_SEGS[-2]]),
    (f"{TEST_ROUTE}/-2:-1", ALL_SEGS[-2:-1]),
    (f"{TEST_ROUTE}/-4:-2", ALL_SEGS[-4:-2]),
    (f"{TEST_ROUTE}/:10:2", ALL_SEGS[:10:2]),
    (f"{TEST_ROUTE}/5::2", ALL_SEGS[5::2]),
    (f"https://useradmin.comma.ai/?onebox={TEST_ROUTE}", ALL_SEGS),
    (f"https://useradmin.comma.ai/?onebox={TEST_ROUTE.replace('/', '|')}", ALL_SEGS),
    (f"https://useradmin.comma.ai/?onebox={TEST_ROUTE.replace('/', '%7C')}", ALL_SEGS),
    (f"https://cabana.comma.ai/?route={TEST_ROUTE}", ALL_SEGS),
  ])
  def test_indirect_parsing(self, identifier, expected):
    parsed, _, _ = parse_indirect(identifier)
    sr = SegmentRange(parsed)
    self.assertListEqual(list(sr.seg_idxs), expected, identifier)

  @parameterized.expand([
    (f"{TEST_ROUTE}", f"{TEST_ROUTE}"),
    (f"{TEST_ROUTE.replace('/', '|')}", f"{TEST_ROUTE}"),
    (f"{TEST_ROUTE}--5", f"{TEST_ROUTE}/5"),
    (f"{TEST_ROUTE}/0/q", f"{TEST_ROUTE}/0/q"),
    (f"{TEST_ROUTE}/5:6/r", f"{TEST_ROUTE}/5:6/r"),
    (f"{TEST_ROUTE}/5", f"{TEST_ROUTE}/5"),
  ])
  def test_canonical_name(self, identifier, expected):
    sr = SegmentRange(identifier)
    self.assertEqual(str(sr), expected)

  def test_direct_parsing(self):
    qlog = tempfile.NamedTemporaryFile(mode='wb', delete=False)

    with requests.get(QLOG_FILE, stream=True) as r:
      with qlog as f:
        shutil.copyfileobj(r.raw, f)

    for f in [QLOG_FILE, qlog.name]:
      l = len(list(LogReader(f)))
      self.assertGreater(l, 100)

  @parameterized.expand([
    (f"{TEST_ROUTE}///",),
    (f"{TEST_ROUTE}---",),
    (f"{TEST_ROUTE}/-4:--2",),
    (f"{TEST_ROUTE}/-a",),
    (f"{TEST_ROUTE}/j",),
    (f"{TEST_ROUTE}/0:1:2:3",),
    (f"{TEST_ROUTE}/:::3",),
    (f"{TEST_ROUTE}3",),
    (f"{TEST_ROUTE}-3",),
    (f"{TEST_ROUTE}--3a",),
  ])
  def test_bad_ranges(self, segment_range):
    with self.assertRaises(AssertionError):
      _ = SegmentRange(segment_range).seg_idxs

  @parameterized.expand([
    (f"{TEST_ROUTE}/0", False),
    (f"{TEST_ROUTE}/:2", False),
    (f"{TEST_ROUTE}/0:", True),
    (f"{TEST_ROUTE}/-1", True),
    (f"{TEST_ROUTE}", True),
  ])
  def test_slicing_api_call(self, segment_range, api_call):
    with mock.patch("openpilot.tools.lib.route.get_max_seg_number_cached") as max_seg_mock:
      max_seg_mock.return_value = NUM_SEGS
      _ = SegmentRange(segment_range).seg_idxs
      self.assertEqual(api_call, max_seg_mock.called)

  @pytest.mark.slow
  def test_modes(self):
    qlog_len = len(list(LogReader(f"{TEST_ROUTE}/0", ReadMode.QLOG)))
    rlog_len = len(list(LogReader(f"{TEST_ROUTE}/0", ReadMode.RLOG)))

    self.assertLess(qlog_len * 6, rlog_len)

  @pytest.mark.slow
  def test_modes_from_name(self):
    qlog_len = len(list(LogReader(f"{TEST_ROUTE}/0/q")))
    rlog_len = len(list(LogReader(f"{TEST_ROUTE}/0/r")))

    self.assertLess(qlog_len * 6, rlog_len)

  @pytest.mark.slow
  def test_list(self):
    qlog_len = len(list(LogReader(f"{TEST_ROUTE}/0/q")))
    qlog_len_2 = len(list(LogReader([f"{TEST_ROUTE}/0/q", f"{TEST_ROUTE}/0/q"])))

    self.assertEqual(qlog_len * 2, qlog_len_2)

  @pytest.mark.slow
  @mock.patch("openpilot.tools.lib.logreader._LogFileReader")
  def test_multiple_iterations(self, init_mock):
    lr = LogReader(f"{TEST_ROUTE}/0/q")
    qlog_len1 = len(list(lr))
    qlog_len2 = len(list(lr))

    # ensure we don't create multiple instances of _LogFileReader, which means downloading the files twice
    self.assertEqual(init_mock.call_count, 1)

    self.assertEqual(qlog_len1, qlog_len2)

  @pytest.mark.slow
  def test_helpers(self):
    lr = LogReader(f"{TEST_ROUTE}/0/q")
    self.assertEqual(lr.first("carParams").carFingerprint, "SUBARU OUTBACK 6TH GEN")
    self.assertTrue(0 < len(list(lr.filter("carParams"))) < len(list(lr)))

  @parameterized.expand([(True,), (False,)])
  @pytest.mark.slow
  def test_run_across_segments(self, cache_enabled):
    os.environ["FILEREADER_CACHE"] = "1" if cache_enabled else "0"
    lr = LogReader(f"{TEST_ROUTE}/0:4")
    self.assertEqual(len(lr.run_across_segments(4, noop)), len(list(lr)))

  @pytest.mark.slow
  def test_auto_mode(self):
    lr = LogReader(f"{TEST_ROUTE}/0/q")
    qlog_len = len(list(lr))
    with mock.patch("openpilot.tools.lib.route.Route.log_paths") as log_paths_mock:
      log_paths_mock.return_value = [None] * NUM_SEGS
      # Should fall back to qlogs since rlogs are not available
      lr = LogReader(f"{TEST_ROUTE}/0/a", default_source=comma_api_source)
      log_len = len(list(lr))

    self.assertEqual(qlog_len, log_len)


if __name__ == "__main__":
  unittest.main()
