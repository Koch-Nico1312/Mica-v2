"""Real Windows UIA evidence plus rendered disposable planning and file-check windows."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.name != 'nt':
        raise RuntimeError('Diese Prüfung benötigt Windows.')
    from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QLineEdit, QCheckBox
    from desktop.core.outcome_verification import verify_window, window_snapshot, file_snapshot, verify_file
    from desktop.core.offline_tasks import OfflineTasks
    from desktop.task_planning_dialog import TaskPlanningDialog
    from desktop.outcome_dialog import OutcomeDialog
    from desktop.core.project_export import project_markdown, write_export
    from desktop.core.workspace import ProjectWorkspaceStore
    app = QApplication.instance() or QApplication([])
    proof = QDialog()
    proof.setWindowTitle('MICA Ergebnisprüfung · eigenes Testfenster')
    layout = QVBoxLayout(proof)
    layout.addWidget(QLabel('Einstellung gespeichert · MICA Prüfbeleg'))
    toggle = QCheckBox('MICA Testeinstellung')
    layout.addWidget(toggle)
    password = QLineEdit('MICA_PASSWORD_MUST_NOT_APPEAR')
    password.setEchoMode(QLineEdit.EchoMode.Password)
    layout.addWidget(password)
    proof.show()
    app.processEvents()
    try:
        target = {'hwnd': int(proof.winId()), 'pid': os.getpid(), 'title': proof.windowTitle()}
        with ThreadPoolExecutor(max_workers=1) as pool:
            baseline_future = pool.submit(window_snapshot, target)
            while not baseline_future.done():
                app.processEvents()
                time.sleep(.01)
            window_baseline = baseline_future.result()
            assert 'MICA Testeinstellung (ausgeschaltet)' in window_baseline['text']
            toggle.setChecked(True)
            app.processEvents()
            future = pool.submit(verify_window, target, 'Einstellung gespeichert')
            while not future.done():
                app.processEvents()
                time.sleep(.01)
            result = future.result()
            changed_future = pool.submit(verify_window, target, 'MICA Testeinstellung (eingeschaltet)',
                baseline=window_baseline, require_changed=True)
            while not changed_future.done():
                app.processEvents()
                time.sleep(.01)
            changed_result = changed_future.result()
            assert changed_result['status'] == 'confirmed', changed_result
        assert result['status'] == 'confirmed', result
        assert 'MICA_PASSWORD_MUST_NOT_APPEAR' not in result['evidence']['text']
    finally:
        proof.close()
    output = ROOT / 'artifacts' / 'planning-results'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mica-plan-results-') as directory:
        directory = Path(directory)
        path = directory / 'file.md'
        path.write_text('Ausgangsfassung', encoding='utf-8')
        baseline = file_snapshot(path)
        path.write_text('Gespeicherte neue Fassung', encoding='utf-8')
        file_result = verify_file(path, baseline=baseline, require_changed=True, expected_text='neue Fassung')
        assert file_result['status'] == 'confirmed'
        store = OfflineTasks(directory / 'tasks.json')
        store.stage({'id': 'a' * 32, 'title': 'Mathematik üben', 'description': '', 'status': 'open', 'priority': 'normal', 'due_at': None}, minutes=60)
        planning = TaskPlanningDialog(None, lambda *args: None, store=store, page='plan')
        planning.preview_plan()
        assert planning.plan and planning.accept_plan.isEnabled()
        planning.show()
        app.processEvents()
        assert planning.grab().save(str(output / 'planning.png'))
        planning.close()
        checks = OutcomeDialog(None)
        checks.path.setText(str(path))
        checks.finished_check('file', file_result)
        checks.show()
        app.processEvents()
        assert checks.grab().save(str(output / 'file-result.png'))
        checks.close()
        project = ProjectWorkspaceStore(directory / 'projects.json', directory / 'absent')
        checkpoint = project.save([{'id': 'b' * 32, 'title': 'Quelle.md', 'body': 'Mathematik · Quellenbeleg', 'source': 'text'}],
            None, 'Ergebnisse kontrollieren', last_step='Formel gelesen', name='schule')
        export = project_markdown('schule', checkpoint, store.view())
        write_export(directory / 'schule.md', export)
        assert 'Formel gelesen' in (directory / 'schule.md').read_text(encoding='utf-8')
    result = {'windows_uia_read': True, 'expected_label_confirmed': True, 'password_excluded': True,
        'real_toggle_change_confirmed_against_baseline': True,
        'real_file_changed_and_text_confirmed': True, 'planning_rendered': True, 'markdown_roundtrip': True,
        'user_data_modified': False}
    (output / 'windows-runtime.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
