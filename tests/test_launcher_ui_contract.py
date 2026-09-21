from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherUiContractTests(unittest.TestCase):
    def test_launcher_updates_safely_and_starts_local_ui(self) -> None:
        source = (ROOT / "install_and_start.ps1").read_text(encoding="utf-8-sig").lower()

        self.assertIn('"desktop\\local_main.py"', source)
        self.assertIn("function update-mica", source)
        self.assertIn("fetch --quiet --prune", source)
        self.assertIn("status --porcelain", source)
        self.assertIn("pull --ff-only", source)
        self.assertIn("uvpath pip sync", source.replace("$", ""))
        self.assertIn("function test-newui", source)
        self.assertIn("mica_ui_generation", source)
        self.assertIn("mica-orb-v2.png", source)

    def test_only_generation_two_ui_is_a_supported_entrypoint(self) -> None:
        ui_source = (ROOT / "desktop" / "ui.py").read_text(encoding="utf-8")
        local_source = (ROOT / "desktop" / "local_main.py").read_text(encoding="utf-8")
        cloud_source = (ROOT / "desktop" / "main.py").read_text(encoding="utf-8")

        self.assertIn("MICA_UI_GENERATION = 2", ui_source)
        self.assertIn("if MICA_UI_GENERATION < 2", local_source)
        self.assertIn('JarvisUI("assets/mica-orb-v2.png")', local_source)
        self.assertIn('JarvisUI("assets/mica-orb-v2.png")', cloud_source)
        self.assertNotIn('JarvisUI("face.png")', cloud_source)
        self.assertFalse((ROOT / "design_preview.html").exists())

    def test_double_click_wrapper_targets_the_canonical_launcher(self) -> None:
        wrapper = (ROOT / "Start MICA.cmd").read_text(encoding="utf-8").lower()
        self.assertIn("install_and_start.ps1", wrapper)
        self.assertIn('cd /d "%~dp0"', wrapper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
