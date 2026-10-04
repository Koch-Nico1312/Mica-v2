from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication

from desktop.control_center import ControlCenter
from desktop.core.local_core_client import LocalCoreClient, LocalCoreError
from desktop.core.response_timing import TimingHistory


def test_voice_phases_exclude_recording_and_playback_from_response_wait():
    now = [10.0]
    history = TimingHistory(clock=lambda: now[0])
    timing = history.begin('voice')
    now[0] = 11.0
    timing.mark('connected')
    now[0] = 20.0
    timing.mark('submitted')
    now[0] = 21.0
    timing.mark('transcript')
    now[0] = 23.0
    timing.mark('reply')
    now[0] = 24.0
    timing.mark('audio')
    now[0] = 29.0
    timing.finish('success')
    record = history.snapshot()[0]
    assert {key: record[key] for key in ('connect_ms', 'transcript_ms', 'reply_ms', 'audio_ms', 'total_ms')} == {
        'connect_ms': 1000, 'transcript_ms': 1000, 'reply_ms': 3000, 'audio_ms': 4000, 'total_ms': 19000}
    assert set(record) == {'kind', 'outcome', 'created_at', 'connect_ms', 'transcript_ms', 'reply_ms', 'audio_ms', 'total_ms'}


def test_first_mark_and_terminal_result_win_even_after_cleanup():
    now = [0.0]
    history = TimingHistory(clock=lambda: now[0])
    timing = history.begin('text')
    now[0] = 1.0
    timing.mark('reply')
    now[0] = 2.0
    timing.mark('reply')
    timing.finish('failed')
    now[0] = 3.0
    timing.finish('cancelled')
    timing.mark('audio')
    assert len(history.snapshot()) == 1
    assert history.snapshot()[0]['outcome'] == 'failed'
    assert history.snapshot()[0]['reply_ms'] == 1000
    assert 'audio_ms' not in history.snapshot()[0]


def test_voice_without_submission_has_no_response_wait():
    history = TimingHistory()
    timing = history.begin('voice')
    timing.mark('reply')
    timing.finish('cancelled')
    assert 'reply_ms' not in history.snapshot()[0]


def test_history_is_bounded_thread_safe_and_returns_copies():
    history = TimingHistory(limit=10)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: history.begin('text').finish('success'), range(80)))
    assert len(history.snapshot()) == 10
    history.snapshot()[0]['kind'] = 'private content'
    assert history.snapshot()[0]['kind'] == 'text'
    history.clear()
    assert history.snapshot() == []


@pytest.mark.parametrize('failed', [False, True])
def test_text_client_records_outcome_without_content(failed):
    history = TimingHistory()
    client = LocalCoreClient('https://localhost', api_token='secret-token')
    error = LocalCoreError('private error detail') if failed else None
    with patch('desktop.core.local_core_client.RESPONSE_TIMINGS', history), \
            patch.object(client, '_request', return_value={'reply': 'private answer'}, side_effect=error):
        if failed:
            with pytest.raises(LocalCoreError):
                client.turn('private message', remember=False)
        else:
            assert client.turn('private message', remember=False)['reply'] == 'private answer'
    record = history.snapshot()[0]
    assert record['outcome'] == ('failed' if failed else 'success')
    assert all(word not in str(record) for word in ('private', 'secret-token', 'message'))
    client.session.close()


def test_diagnostics_shows_separate_success_medians_and_all_outcomes():
    app = QApplication.instance() or QApplication([])
    history = TimingHistory()
    for kind, outcome, ms in [('text', 'success', 1000), ('text', 'success', 3000),
                              ('text', 'failed', 99000), ('voice', 'success', 5000), ('voice', 'cancelled', 8000)]:
        history._append({'kind': kind, 'outcome': outcome, 'reply_ms': ms, 'total_ms': ms,
                         'created_at': '2026-10-04T10:00:00+00:00'})
    with patch('desktop.control_center.RESPONSE_TIMINGS', history):
        page = ControlCenter()
        page._timing_timer.stop()
        assert 'Text: 2.00 s Median (2)' in page.timing_summary.text()
        assert 'Sprache: 5.00 s Median (1)' in page.timing_summary.text()
        assert page.timing_table.rowCount() == 5
        assert page.timing_table.item(0, 1).text() == 'Abgebrochen'
        assert page.timing_table.item(0, 4).text() == '-'
        page.clear_response_timings()
        assert page.timing_table.rowCount() == 0
        page.close()
        page.deleteLater()
        app.processEvents()
