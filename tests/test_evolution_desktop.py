import os
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from desktop.evolution_page import EvolutionPage
from desktop.control_center import ControlCenter

APP = QApplication.instance() or QApplication([])


def test_native_evolution_tab_renders_provenance_gaps_and_quality_report():
    center = ControlCenter()
    page = center.evolution_page
    center.resize(1200, 850)
    center.show()
    APP.processEvents()
    page._received('state', {
        'preferences': [{'id': 'rule', 'preference_key': 'format', 'value': 'Stichpunkte', 'scope': 'technical', 'source': 'turn-42'}],
        'gaps': [{'id': 'gap', 'action': 'double', 'category': 'missing_tool'}],
        'suites': [{'id': 'suite', 'goal': 'Verdopple n'}],
        'workshop': [{'id': 'job', 'improvement_id': 'revision', 'patch': 'small patch',
                     'quality': {'candidate': {'correct': 3}, 'reproduced': True},
                     'improvement': {'name': 'double', 'status': 'validated'}}],
    }, '')
    assert center.tabs.tabText(center.tabs.indexOf(page)) == 'Weiterentwicklung'
    assert 'turn-42' in page.preference_detail.toPlainText()
    assert 'Werkzeug fehlt' in page.gaps.currentText()
    assert '3 richtige Ergebnisse' in page.report.toPlainText()
    with patch.object(page, 'change') as change:
        page.evaluate()
        change.assert_called_once_with('POST', '/v1/improvements/revision/evaluate', {'auto_promote': False})
    center.close()
    center.deleteLater()
    APP.processEvents()


def test_native_actions_resubmit_exact_approval_and_never_apply_it_to_changed_input():
    page = EvolutionPage()
    body = {'auto_promote': False}
    import json
    key = '/v1/improvements/revision/evaluate' + json.dumps(body, sort_keys=True)
    page._received('change', {'key': key, 'approval': {'approval_id': 'approved-id'}}, '')
    calls = []
    class Client:
        def evolution_change(self, method, path, payload):
            calls.append(payload)
            return {'validated': True}
    with patch.object(page, '_run', side_effect=lambda kind, action: action(Client())):
        page.change('POST', '/v1/improvements/revision/evaluate', body)
        page.change('POST', '/v1/improvements/revision/evaluate', {'auto_promote': False, 'changed': True})
    assert calls[0]['approval_id'] == 'approved-id'
    assert 'approval_id' not in calls[1]
    page.close()
    page.deleteLater()
    APP.processEvents()
