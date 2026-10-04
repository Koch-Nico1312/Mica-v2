from __future__ import annotations

import os
from unittest.mock import Mock, patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QMessageBox

from desktop.control_center import ControlCenter, task_presentation, task_timestamp
from desktop.core.local_core_client import LocalCoreClient

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def view():
    widget = ControlCenter()
    widget.timer.stop()
    widget.resize(880, 700)
    widget.show()
    APP.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    APP.processEvents()


def plan(identifier='plan-one', **updates):
    return {'id': identifier, 'goal': 'Dateien sortieren', 'status': 'ready',
            'plan_hash': 'a' * 64, 'risk': 'read', 'budget': {'max_tool_calls': 5},
            'dry_run_at': '2026-10-04T10:00:00+00:00', 'last_error': None,
            'steps': [{'position': 1, 'action': 'files.list', 'params': {}, 'status': 'pending'}],
            'updated_at': '2026-10-04T10:00:00+00:00', **updates}


def activity(view, *, plans=(), tasks=(), executions=(), emergency=False):
    view._received('activity', {'plans': list(plans), 'tasks': list(tasks),
                               'executions': list(executions),
                               'presence': {'state': 'idle', 'emergency_stopped': emergency}}, '')


def test_filtering_and_refresh_keep_selection_bound_to_identity(view):
    activity(view, plans=[plan('one'), plan('two', goal='Server prüfen')])
    view.table.selectRow(1)
    activity(view, plans=[plan('two', goal='Server erneut prüfen'), plan('one')])
    assert view.selected()['id'] == 'two'
    assert view.table.currentRow() == 0
    assert 'Server erneut prüfen' in view.detail.toPlainText()
    view.task_search.setText('DATEIEN')
    assert len(view._items) == 1
    assert view.selected() is None
    assert view.resume_button.isHidden()
    view.table.selectRow(0)
    assert view.selected()['id'] == 'one'


def test_completed_filter_hides_running_and_attention_items(view):
    activity(view, plans=[plan('ready'), plan('finished', status='completed')],
             tasks=[{'id': 'task', 'title': 'Notizen', 'status': 'in_progress'}])
    view.task_filter.setCurrentIndex(view.task_filter.findData('done'))
    assert [item['id'] for item in view._items] == ['finished']
    view.task_filter.setCurrentIndex(view.task_filter.findData('attention'))
    assert [item['id'] for item in view._items] == ['ready']
    view.task_search.setText('nicht vorhanden')
    assert view.table.rowCount() == 0
    assert not view.task_empty.isHidden()


def test_uncertain_execution_never_offers_retry_even_with_inconsistent_flag(view):
    execution = {'key': 'claimed', 'action': 'file_controller', 'status': 'uncertain',
                 'params': {'path': 'notes.txt'}, 'can_retry': True, 'needs_reconciliation': True}
    activity(view, executions=[execution])
    view.table.selectRow(0)
    assert view.retry_button.isHidden()
    assert view.reconcile_button.isEnabled()
    assert view.table.item(0, 2).text() == 'Ergebnis unklar'
    with patch.object(view, '_run') as run:
        view.retry_execution()
        view.resume()
    run.assert_not_called()


def test_paused_plan_with_dispatched_step_requires_result_check(view):
    item = plan(status='paused', last_error='uncertain_outcome', steps=[
        {'position': 1, 'action': 'files.write', 'params': {}, 'status': 'blocked',
         'dispatch_started_at': '2026-10-04T10:00:00+00:00'}])
    activity(view, plans=[item])
    view.table.selectRow(0)
    assert view.resume_button.isHidden()
    assert view.reconcile_button.isEnabled()
    assert view.table.item(0, 2).text() == 'Ergebnis unklar'


def test_approval_wait_and_step_progress_are_visible(view):
    item = plan(status='paused', last_error='A saved user approval is required', steps=[
        {'position': 1, 'action': 'files.list', 'params': {}, 'status': 'completed'},
        {'position': 2, 'action': 'files.write', 'params': {}, 'status': 'blocked', 'dispatch_started_at': None}])
    activity(view, plans=[item])
    view.table.selectRow(0)
    assert view.table.item(0, 2).text() == 'Wartet auf Freigabe'
    assert view.table.item(0, 3).text() == '1 / 2'
    assert view.approvals_button.isEnabled()
    assert view.resume_button.isEnabled()


def test_failed_refresh_disables_changes_until_next_success(view):
    activity(view, plans=[plan()])
    view.table.selectRow(0)
    assert view.resume_button.isEnabled()
    view._received('activity', None, 'Connection lost')
    assert not view.resume_button.isEnabled()
    assert 'nicht aktuell' in view.task_hint.text()
    with patch.object(view, '_run') as run:
        view.resume()
    run.assert_not_called()
    activity(view, plans=[plan()])
    assert view.selected()['id'] == 'plan-one'
    assert view.resume_button.isEnabled()


def test_busy_and_emergency_stop_block_execution_but_allow_pause(view):
    activity(view, plans=[plan()])
    view.table.selectRow(0)
    view._busy = True
    view._show_detail()
    assert not view.resume_button.isEnabled()
    with patch.object(view, '_run') as run:
        view.resume()
    run.assert_not_called()
    view._busy = False
    activity(view, plans=[plan(status='active')], emergency=True)
    assert view.pause_button.isEnabled()
    assert view.resume_button.isHidden()
    activity(view, plans=[plan()], emergency=True)
    assert view.resume_button.isHidden()


def test_cancel_confirmation_is_required_and_bound_to_selected_plan(view):
    activity(view, plans=[plan('one'), plan('two')])
    view.table.selectRow(1)
    client = Mock()
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.No), \
            patch.object(view, '_run') as run:
        view.cancel_selected()
    run.assert_not_called()
    with patch('desktop.control_center.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
            patch.object(view, '_run', side_effect=lambda kind, action: action(client)):
        view.cancel_selected()
    client.cancel_plan.assert_called_once_with('two')
    client.execute.assert_not_called()


def test_task_status_changes_do_not_dispatch_host_actions(view):
    activity(view, tasks=[{'id': 'todo', 'title': 'Notizen prüfen', 'status': 'open'}])
    view.table.selectRow(0)
    client = Mock()
    with patch.object(view, '_run', side_effect=lambda kind, action: action(client)):
        view.task_start_button.click()
    client.update_task.assert_called_once_with('todo', 'in_progress')
    client.execute.assert_not_called()


def test_draft_requires_preview_before_start(view):
    activity(view, plans=[plan(status='draft', dry_run_at=None)])
    view.table.selectRow(0)
    assert view.preview_button.isEnabled()
    assert view.resume_button.isHidden()
    client = Mock()
    with patch.object(view, '_run', side_effect=lambda kind, action: action(client)):
        view.preview_button.click()
    client.preview_plan.assert_called_once_with('plan-one')


def test_unresolved_reconciliation_is_not_reported_as_success(view):
    with patch.object(view, 'refresh') as refresh:
        view._received('reconcile', {'resolved': False, 'status': 'uncertain'}, '')
    assert 'weiterhin unklar' in view._task_notice
    refresh.assert_called_once()


def test_client_task_controls_use_existing_routes():
    client = LocalCoreClient('https://localhost:8443', api_token='test')
    with patch.object(client, '_request') as request:
        client.cancel_plan('plan')
        client.preview_plan('plan')
        client.update_task('todo', 'completed')
    assert request.call_args_list[0].args == ('PATCH', '/v1/agent-plans/plan')
    assert request.call_args_list[0].kwargs == {'json': {'status': 'cancelled'}}
    assert request.call_args_list[1].args == ('POST', '/v1/agent-plans/plan/dry-run')
    assert request.call_args_list[2].kwargs == {'json': {'status': 'completed'}}


def test_task_dates_use_vienna_timezone():
    assert task_timestamp('2026-10-04T10:00:00+00:00') == '04.10. 12:00'
    assert task_timestamp('invalid') == ''


def test_budget_exhaustion_is_separate_from_approval_wait(view):
    shown = task_presentation({'kind': 'plan', **plan(status='paused', last_error='budget_exhausted')})
    assert shown['label'] == 'Pausiert'
    assert 'Budget' not in shown['label']
    assert 'budget' in shown['hint']
    activity(view, plans=[plan(status='paused', last_error='budget_exhausted', risk='reversible')])
    view.table.selectRow(0)
    assert view.resume_button.isHidden()
    assert view.approvals_button.isHidden()


def test_cancelled_plan_keeps_unresolved_effects_visible_without_reactivation(view):
    item = plan(status='cancelled', steps=[
        {'position': 1, 'action': 'files.move', 'params': {}, 'status': 'running',
         'dispatch_started_at': '2026-10-04T10:00:00+00:00'}])
    activity(view, plans=[item])
    view.task_filter.setCurrentIndex(view.task_filter.findData('attention'))
    assert view.table.rowCount() == 1
    view.table.selectRow(0)
    assert view.history_button.isEnabled()
    assert view.resume_button.isHidden()
    assert view.reconcile_button.isHidden()
    assert 'abgebrochen' in view.task_hint.text()


def test_already_confirmed_reconciliation_is_reported_accurately(view):
    with patch.object(view, 'refresh'):
        view._received('reconcile', {'resolved': False, 'status': 'succeeded'}, '')
    assert 'Ergebnis bestätigt' in view._task_notice
