"""Opt-in packaged acceptance, isolated fixtures only; never scans a network."""
import os
import time
from pathlib import Path

from main import Atlas


def run(app, root, output):
    checks = {}
    folder = Path(root) / 'workflow'
    window = Atlas(folder)
    try:
        window.show()
        app.processEvents()
        for index in range(5):
            window.left_tabs.setCurrentIndex(index)
            app.processEvents()
            assert window.player.isVisible() == (index == 1)
        window.prompt.setPlainText('Unsent acceptance question')
        window.chrome.focus.trigger()
        assert window.network_dock.isHidden() and window.assistant_dock.isHidden()
        window.chrome.focus.trigger()
        assert not window.network_dock.isHidden()
        assert window.prompt.toPlainText() == 'Unsent acceptance question'
        checks['workspace_navigation'] = True

        panel = window.open_equipment('192.0.2.45')
        panel.fields['name'].setText('Приёмочный кодек')
        panel.fields['manufacturer'].setText('Test only')
        panel.fields['management_url'].setText('http://192.0.2.45:7777/status')
        panel.fields['notes'].setPlainText('Синтетическая карточка; подключаться нельзя.')
        panel.save_button.click()
        assert panel.revision == 1

        scenario = window.open_scenarios()
        scenario.name.setText('Приёмочная проверка резерва')
        scenario.steps = [dict(ip='192.0.2.45', output=1, primary=12345, backup=12346)]
        scenario.render()
        scenario.save()
        assert len(scenario.store.plans()) == 1
        assert not scenario.execute.isEnabled() and scenario.job is None

        sources = [dict(slot=1, channel=12345, name='Acceptance source',
                        multicast='239.192.48.57', enabled=True),
                   dict(slot=2, channel=12346, name='Disabled',
                        multicast='239.192.48.58', enabled=False),
                   dict(slot=3, channel=0, name='No number',
                        multicast='239.192.0.0', enabled=True)]
        audio = window.audio_sources
        audio.update_device(dict(ip='192.0.2.45', sources=sources))
        assert audio.tree.topLevelItemCount() == 1
        audio.tree.setCurrentItem(audio.tree.topLevelItem(0))
        audio.favorite_button.click()
        assert len(audio.favorites) == 1
        assert window.player.receiver is None
        checks['audio_selection_without_playback'] = True
        window.set_appearance('macos')
        window.settings.setValue('interface_language', 'en')
        window.settings.sync()
        window.grab().save(str(Path(output) / 'workflow-ru.png'))
    finally:
        window.close()
        app.processEvents()

    window = Atlas(folder)
    try:
        window.show()
        app.processEvents()
        assert window.left_tabs.tabText(0) == 'Network'
        assert window.property('atlasSkin') == 'macos'
        assert len(window.audio_sources.favorites) == 1
        panel = window.open_equipment('192.0.2.45')
        assert panel.fields['name'].text() == 'Приёмочный кодек'
        assert panel.fields['management_url'].text() == 'http://192.0.2.45:7777/status'
        assert panel.revision == 1
        scenario = window.open_scenarios()
        assert scenario.name.text() == 'Приёмочная проверка резерва'
        assert len(scenario.store.plans()) == 1
        assert not scenario.execute.isEnabled() and scenario.job is None
        assert not window.discovery_active and window.player.receiver is None
        checks['restart_preserves_cards_scenarios_favorites_language_skin'] = True
        window.settings.setValue('interface_language', 'ru')
        window.settings.sync()
    finally:
        window.close()
        app.processEvents()

    # Optional local speech fixture. Nothing is downloaded by acceptance.
    model = os.environ.get('ATLAS_ACCEPTANCE_MODEL')
    audio_file = os.environ.get('ATLAS_ACCEPTANCE_AUDIO')
    window = Atlas(folder)
    try:
        assert window.left_tabs.tabText(0) == 'Сеть'
        if model and audio_file:
            panel = window.open_transcription()
            panel.model_dir = Path(model)
            panel.file.setText(audio_file)
            panel.language.setCurrentIndex(panel.language.findData('ru'))
            panel.update_controls()
            assert panel.run_button.isEnabled()
            panel.run_button.click()
            deadline = time.monotonic() + 90
            while panel.process is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            assert panel.process is None, 'Speech recognition did not finish'
            assert panel.complete, panel.status.text()
            assert panel.save_button.isEnabled()
            text = panel.text.toPlainText()
            assert 'резервный источник звука' in text.casefold(), text
            (Path(output) / 'recognized-ru.txt').write_text(text, encoding='utf-8')
            checks['transcription_button_to_text'] = True
    finally:
        window.close()
        app.processEvents()
    return checks
