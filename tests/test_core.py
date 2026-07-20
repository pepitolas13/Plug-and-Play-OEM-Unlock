#!/usr/bin/env python3
"""
Tests de la logica pura de Plug-and-Play OEM Unlock.

No requieren telefono ni red: se simula (mock) la salida de adb/fastboot
sustituyendo `platform_tools.run`. Ejecuta con:

    python3 tests/test_core.py            (o)   python3 -m unittest -v

Cubren: emparejamiento de marca, parseo de `adb devices` / `fastboot getvar`
(incluido el prefijo '(bootloader)'), y la construccion de planes de flasheo.
"""

import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

import platform_tools as pt  # noqa: E402
import device_db as db       # noqa: E402
import flasher               # noqa: E402
import oem_unlock            # noqa: E402


class FakeRun:
    """Sustituto de platform_tools.run que devuelve salidas fijas por comando."""

    def __init__(self, props=None, fbvars=None, adb_list=None, fb_list=None, fb_prefix=False):
        self.props = props or {}
        self.fbvars = fbvars or {}
        self.adb_list = adb_list
        self.fb_list = fb_list
        self.fb_prefix = fb_prefix  # emula el prefijo '(bootloader) ' de algunos dispositivos

    def __call__(self, tool, args, timeout=60, cwd=None):
        if tool == "adb":
            if args[:1] == ["devices"]:
                return 0, self.adb_list if self.adb_list is not None else "List of devices attached", ""
            if args[:2] == ["shell", "getprop"]:
                return 0, self.props.get(args[2], ""), ""
            return 0, "", ""
        if tool == "fastboot":
            if args[:1] == ["devices"]:
                return (0, self.fb_list, "") if self.fb_list is not None else (0, "", "")
            if args[:1] == ["getvar"]:
                var = args[1]
                if var not in self.fbvars:
                    # fastboot responde asi cuando la variable no existe
                    return 0, "", f"{var}: \nFinished."
                prefix = "(bootloader) " if self.fb_prefix else ""
                # fastboot escribe la respuesta de getvar en stderr
                return 0, "", f"{prefix}{var}: {self.fbvars[var]}"
            return 0, "", ""
        return -1, "", "tool desconocido"


class VendorMatchTests(unittest.TestCase):
    def test_known_brands(self):
        cases = {
            ("Google", "Google"): "google",
            ("Redmi", "Xiaomi"): "xiaomi",
            ("samsung", "samsung"): "samsung",
            ("HUAWEI", "HUAWEI"): "huawei",
            ("realme", "realme"): "realme",
            ("Nothing", "Nothing"): "nothing",
        }
        for (brand, manu), expected in cases.items():
            key, _ = db.match_vendor(brand, manu)
            self.assertEqual(key, expected, f"{brand}/{manu}")

    def test_new_brands(self):
        cases = {
            ("BQ", "bq"): "bq",
            ("Aquaris", "bq"): "bq",
            ("Essential", "Essential"): "essential",
            ("Razer", "Razer"): "razer",
            ("Sharp", "Sharp"): "sharp",
            ("Teracube", "Teracube"): "teracube",
            ("Micromax", "Micromax"): "micromax",
            ("Lava", "Lava"): "lava",
            ("Vsmart", "Vsmart"): "vsmart",
            ("OSCAL", "OSCAL"): "oscal",
            ("OSCAL", "OSCAL Pilot 1"): "oscal",
        }
        for (brand, manu), expected in cases.items():
            key, _ = db.match_vendor(brand, manu)
            self.assertEqual(key, expected, f"{brand}/{manu} -> {key}")

    def test_oscal_is_automatic_fastboot(self):
        # OSCAL Pilot 1 debe caer en el metodo automatico (fastboot).
        key, prof = db.match_vendor("OSCAL", "OSCAL Pilot 1")
        self.assertEqual(key, "oscal")
        self.assertEqual(prof["method"], "fastboot")

    def test_word_boundary_no_false_positive(self):
        # 'itel' NO debe emparejar dentro de 'oukitel' (rugged_mtk).
        key, _ = db.match_vendor("OUKITEL", "OUKITEL")
        self.assertEqual(key, "rugged_mtk")

    def test_unknown_falls_back_to_default(self):
        key, prof = db.match_vendor("MarcaRaraXYZ", "MarcaRaraXYZ")
        self.assertEqual(key, "_default")
        self.assertEqual(prof["method"], "fastboot")

    def test_unofficial_routes_present(self):
        vendors = db.load_vendors()
        for brand in ("huawei", "honor", "vivo", "iqoo", "nokia", "tcl", "wiko"):
            self.assertEqual(vendors[brand]["method"], "locked", brand)
            self.assertIn("unofficial_method", vendors[brand], brand)


class DetectionParsingTests(unittest.TestCase):
    def test_adb_devices_states(self):
        pt.run = FakeRun(adb_list="List of devices attached\nAAA\tdevice\nBBB\tunauthorized")
        devs = db.detect_adb_devices()
        self.assertEqual(devs, [
            {"serial": "AAA", "state": "device"},
            {"serial": "BBB", "state": "unauthorized"},
        ])

    def test_adb_devices_crlf_and_blank(self):
        pt.run = FakeRun(adb_list="List of devices attached\r\nAAA\tdevice\r\n\r\n")
        devs = db.detect_adb_devices()
        self.assertEqual([d["serial"] for d in devs], ["AAA"])
        self.assertEqual(devs[0]["state"], "device")

    def test_fastboot_devices(self):
        pt.run = FakeRun(fb_list="FB123\tfastboot")
        devs = db.detect_fastboot_devices()
        self.assertEqual(devs, [{"serial": "FB123", "state": "fastboot"}])

    def test_describe_fastboot_plain_getvar(self):
        pt.run = FakeRun(fbvars={"product": "raven", "unlocked": "yes"})
        info = db.describe_fastboot_device()
        self.assertEqual(info["unlocked"], "yes")

    def test_describe_fastboot_bootloader_prefix(self):
        # Muchos dispositivos prefijan la variable con '(bootloader) '.
        pt.run = FakeRun(fbvars={"product": "star2lte", "unlocked": "no"}, fb_prefix=True)
        info = db.describe_fastboot_device()
        self.assertEqual(info["unlocked"], "no")
        self.assertEqual(info["brand"], "star2lte")


class VerifyUnlockedTests(unittest.TestCase):
    def test_plain(self):
        pt.run = FakeRun(fbvars={"unlocked": "yes"})
        self.assertIs(oem_unlock.verify_unlocked(), True)

    def test_bootloader_prefix(self):
        pt.run = FakeRun(fbvars={"unlocked": "yes"}, fb_prefix=True)
        self.assertIs(oem_unlock.verify_unlocked(), True)

    def test_locked_reported(self):
        pt.run = FakeRun(fbvars={"unlocked": "no"})
        self.assertIs(oem_unlock.verify_unlocked(), False)


class FlashPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = flasher.ROMS_DIR
        flasher.ROMS_DIR = self.tmp

    def tearDown(self):
        flasher.ROMS_DIR = self._orig

    def _mkdir(self, name, files):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        for f in files:
            open(os.path.join(d, f), "w").close()
        return d

    def test_find_rom_dir_case_insensitive(self):
        d = self._mkdir("oriole", ["boot.img"])
        self.assertEqual(flasher.find_rom_dir("ORIOLE", ""), d)
        self.assertEqual(flasher.find_rom_dir("nope", ""), None)

    def test_infer_order(self):
        d = self._mkdir("x", ["system.img", "boot.img", "vbmeta.img"])
        kind, steps, _ = flasher.build_plan(d)
        self.assertEqual(kind, "infer")
        # Orden seguro: vbmeta -> boot -> system
        i_vbmeta = steps.index("flash vbmeta vbmeta.img --disable-verity --disable-verification")
        i_boot = steps.index("flash boot boot.img")
        i_system = steps.index("flash system system.img")
        self.assertLess(i_vbmeta, i_boot)
        self.assertLess(i_boot, i_system)

    def test_recipe(self):
        d = self._mkdir("y", [])
        json.dump({"description": "t", "steps": ["flash boot boot.img"]},
                  open(os.path.join(d, "recipe.json"), "w"))
        kind, steps, desc = flasher.build_plan(d)
        self.assertEqual(kind, "recipe")
        self.assertEqual(steps, ["flash boot boot.img"])

    def test_single_zip(self):
        d = self._mkdir("z", ["ota.zip"])
        kind, steps, _ = flasher.build_plan(d)
        self.assertEqual((kind, steps), ("infer", ["update ota.zip"]))

    def test_empty(self):
        d = self._mkdir("e", ["readme.txt"])
        kind, _, _ = flasher.build_plan(d)
        self.assertEqual(kind, "empty")

    def test_samsung_auto_map(self):
        d = self._mkdir("beyond1lte", ["boot.img", "recovery.img"])
        work, steps, _ = flasher.build_samsung_plan(d)
        self.assertEqual(len(steps), 1)
        joined = " ".join(steps[0])
        self.assertIn("--BOOT", joined)
        self.assertIn("--RECOVERY", joined)


class AliasBoundaryTests(unittest.TestCase):
    def test_mi_space_no_false_positive(self):
        # 'mi ' (alias de xiaomi) NO debe casar dentro de 'nomi' -> _default.
        key, _ = db.match_vendor("Nomi", "Nomi")
        self.assertEqual(key, "_default")

    def test_mi_space_real_xiaomi(self):
        key, _ = db.match_vendor("Mi", "Xiaomi")
        self.assertEqual(key, "xiaomi")


class ZipSpacesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = flasher.ROMS_DIR
        flasher.ROMS_DIR = self.tmp

    def tearDown(self):
        flasher.ROMS_DIR = self._orig

    def test_zip_with_spaces_roundtrips(self):
        d = os.path.join(self.tmp, "dev")
        os.makedirs(d)
        open(os.path.join(d, "My Rom v2.zip"), "w").close()
        kind, steps, _ = flasher.build_plan(d)
        self.assertEqual(kind, "infer")
        # El paso debe reconstruirse con el nombre completo (con espacios).
        self.assertEqual(shlex.split(steps[0]), ["update", "My Rom v2.zip"])


class RecipeErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_malformed_recipe_no_crash(self):
        d = os.path.join(self.tmp, "dev")
        os.makedirs(d)
        with open(os.path.join(d, "recipe.json"), "w") as f:
            f.write('{ "steps": [ "flash boot boot.img", ] }')  # coma de mas -> invalido
        # No debe lanzar: se degrada a 'empty' con un mensaje controlado.
        kind, steps, _ = flasher.build_plan(d)
        self.assertEqual(kind, "empty")


class MtkclientTests(unittest.TestCase):
    def test_tool_absent_in_env(self):
        self.assertIsNone(oem_unlock._mtk_tool())

    def test_handle_returns_none_without_tool(self):
        # Sin mtkclient instalado: informa y devuelve None (no ejecuta nada).
        self.assertIsNone(oem_unlock.handle_mtkclient({"unofficial_tool": "x"}))

    def test_run_unlock_dispatches_to_mtkclient(self):
        orig = oem_unlock.handle_mtkclient
        seen = {}

        def fake(profile):
            seen["hit"] = True
            return "SENT"

        oem_unlock.handle_mtkclient = fake
        try:
            out = oem_unlock.run_unlock({"method": "mtkclient"}, True)
        finally:
            oem_unlock.handle_mtkclient = orig
        self.assertEqual(out, "SENT")
        self.assertTrue(seen.get("hit"))


class IntegrationSmokeTests(unittest.TestCase):
    """Recorre process_device end-to-end con hardware simulado (sin telefono)."""

    def setUp(self):
        self._run = pt.run
        self._adb = db.detect_adb_devices
        self._fb = db.detect_fastboot_devices
        self._auto = oem_unlock.AUTO

    def tearDown(self):
        pt.run = self._run
        db.detect_adb_devices = self._adb
        db.detect_fastboot_devices = self._fb
        oem_unlock.AUTO = self._auto

    def test_locked_mediatek_brand_flow_no_crash(self):
        # Wiko (locked + unofficial mtkclient) en modo ADB, en --auto.
        oem_unlock.AUTO = True
        db.detect_adb_devices = lambda: [{"serial": "X", "state": "device"}]
        db.detect_fastboot_devices = lambda: []
        pt.run = FakeRun(props={
            "ro.product.brand": "Wiko", "ro.product.manufacturer": "Wiko",
            "ro.product.model": "View5", "ro.product.device": "w-v5",
            "ro.build.version.release": "11", "sys.oem_unlock_allowed": "1",
        })
        # locked -> handle_locked (auto no ejecuta ruta no oficial) -> False
        self.assertIs(oem_unlock.process_device(True), False)

    def test_fastboot_already_unlocked_flow_no_crash(self):
        oem_unlock.AUTO = True
        db.detect_adb_devices = lambda: []
        db.detect_fastboot_devices = lambda: [{"serial": "FB", "state": "fastboot"}]
        pt.run = FakeRun(fbvars={"product": "raven", "unlocked": "yes"})
        # bootloader ya desbloqueado -> True, sin excepciones
        self.assertIs(oem_unlock.process_device(True), True)

    def test_declined_on_phone_reports_locked(self):
        # fastboot devuelve OKAY (run_unlock True) pero verify dice unlocked=no
        # (el usuario eligio 'No' en el telefono) -> process_device debe devolver
        # False y NO mostrar el resumen 'DESBLOQUEADO'.
        oem_unlock.AUTO = True
        db.detect_adb_devices = lambda: []
        db.detect_fastboot_devices = lambda: [{"serial": "FB", "state": "fastboot"}]
        pt.run = FakeRun(fbvars={"product": "raven", "unlocked": "no"})
        orig_ru, orig_vu, orig_sum = (oem_unlock.run_unlock,
                                      oem_unlock.verify_unlocked,
                                      oem_unlock._completion_summary)
        seen = {"summary": False}
        oem_unlock.run_unlock = lambda p, y: True
        oem_unlock.verify_unlocked = lambda: False
        oem_unlock._completion_summary = lambda *a, **k: seen.__setitem__("summary", True)
        try:
            res = oem_unlock.process_device(True)
        finally:
            oem_unlock.run_unlock = orig_ru
            oem_unlock.verify_unlocked = orig_vu
            oem_unlock._completion_summary = orig_sum
        self.assertIs(res, False)
        self.assertFalse(seen["summary"], "no debe mostrar resumen si sigue bloqueado")


class WinDriversTests(unittest.TestCase):
    """Fuera de Windows todo es no-op seguro; la logica pura (seleccion de
    candidato) y el invariante de firma se comprueban en cualquier plataforma."""

    def setUp(self):
        import windrivers
        self.wd = windrivers

    def test_noop_off_windows(self):
        if self.wd.is_windows():
            self.skipTest("solo se comprueba el no-op fuera de Windows")
        self.assertFalse(self.wd.is_windows())
        self.assertIs(self.wd.ensure_fastboot_driver(), False)
        self.assertIs(self.wd.setup_fastboot_windows(), False)
        self.assertIs(self.wd.ensure_usbdk(), False)
        self.assertIs(self.wd.force_bind("USB\\X", "C:\\x.inf"), False)
        self.assertIs(self.wd._run_elevated_ps("exit 0"), False)
        self.assertEqual(self.wd.find_problem_usb_devices(), [])

    def test_pick_candidate_prefers_mediatek_error28(self):
        devices = [
            {"instance_id": "USB\\VID_1234&PID_5678\\aa", "name": "USB Hub",
             "class": "USB", "error_code": 0, "vid": "1234", "pid": "5678"},
            {"instance_id": "USB\\VID_0E8D&PID_201C\\6&x", "name": "Android",
             "class": "", "error_code": 28, "vid": "0E8D", "pid": "201C"},
        ]
        cand = self.wd.pick_fastboot_candidate(devices)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["vid"], "0E8D")

    def test_pick_candidate_empty_or_zero_score(self):
        self.assertIsNone(self.wd.pick_fastboot_candidate([]))
        # Un dispositivo sin senales de Android y sin problema -> no se toca.
        neutral = [{"instance_id": "USB\\VID_9999&PID_0001\\z", "name": "Mouse",
                    "class": "Mouse", "error_code": 0, "vid": "9999", "pid": "0001"}]
        self.assertIsNone(self.wd.pick_fastboot_candidate(neutral))

    def test_vid_pid_extraction(self):
        self.assertEqual(self.wd._vid_pid("USB\\VID_0E8D&PID_201C\\6&abc"),
                         ("0E8D", "201C"))
        self.assertEqual(self.wd._vid_pid("nonsense"), (None, None))

    def test_forcebind_signature_invariant(self):
        # INVARIANTE CRITICO: el force-bind NO debe editar el android_winusb.inf
        # (romperia la firma del catalogo y exigiria test-signing). Debe usar el
        # enfoque por CLASE (DiInstallDevice), no bypass de firma.
        ps = self.wd._FORCE_BIND_PS
        self.assertIn("DiInstallDevice", ps)
        self.assertIn("SPDIT_CLASSDRIVER", ps)
        for forbidden in ("Set-Content", "Out-File", "Add-Content",
                          "bcdedit", "TESTSIGNING", "nointegritychecks"):
            self.assertNotIn(forbidden, ps, f"no debe aparecer: {forbidden}")


class UxHelpersTests(unittest.TestCase):
    def test_bar_bounds(self):
        self.assertEqual(oem_unlock._bar(60, 60, width=10), "==========")
        self.assertEqual(oem_unlock._bar(0, 60, width=10), "----------")
        half = oem_unlock._bar(30, 60, width=10)
        self.assertEqual(len(half), 10)
        self.assertEqual(half.count("="), 5)
        # nunca se sale de rango aunque remaining > total o < 0
        self.assertEqual(len(oem_unlock._bar(999, 60, width=10)), 10)
        self.assertEqual(len(oem_unlock._bar(-5, 60, width=10)), 10)

    def test_fmt_mmss(self):
        self.assertEqual(oem_unlock._fmt_mmss(5), "5s")
        self.assertEqual(oem_unlock._fmt_mmss(65), "1m 05s")
        self.assertEqual(oem_unlock._fmt_mmss(600), "10m 00s")

    def test_animated_wait_returns_poll_value(self):
        import time as _t
        t0 = _t.monotonic()
        res = oem_unlock.animated_wait(
            lambda: "adb" if (_t.monotonic() - t0) > 0.3 else None,
            timeout=3, render=lambda r, i: None, poll_every=0.2)
        self.assertEqual(res, "adb")

    def test_animated_wait_timeout(self):
        res = oem_unlock.animated_wait(
            lambda: None, timeout=0.6, render=lambda r, i: None, poll_every=0.2)
        self.assertIsNone(res)

    def test_summary_status_label(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oem_unlock._completion_summary({"brand": "X", "model": "Y"}, 10, None, unlocked=True)
        self.assertIn("DESBLOQUEADO", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oem_unlock._completion_summary({"brand": "X", "model": "Y"}, 10, None, unlocked=None)
        self.assertIn("no confirmado", buf.getvalue())
        self.assertNotIn("DESBLOQUEADO", buf.getvalue())

    def test_skip_helpers_safe_without_tty(self):
        # Sin terminal: drain no lanza, skip devuelve False, y 'skippable' no
        # produce SKIP (solo agota el tiempo -> None). Evita el bug de que un
        # ENTER bufferizado auto-responda una confirmacion posterior.
        oem_unlock._drain_stdin()
        self.assertFalse(oem_unlock._skip_key_pressed())
        r = oem_unlock.animated_wait(lambda: None, 0.4, lambda a, b: None,
                                     poll_every=0.2, skippable=True)
        self.assertIsNone(r)
        self.assertIsNotNone(oem_unlock.SKIP)


@unittest.skipUnless(shutil.which("sleep"), "necesita el comando 'sleep'")
class RunStreamTimeoutTests(unittest.TestCase):
    def test_watchdog_kills_stuck_process(self):
        # 'sleep 5' no escribe nada: sin el watchdog, 'for line in stdout'
        # bloquearia 5s. El timer debe matarlo a ~1s y devolver -1.
        start = time.time()
        rc = pt.run_stream("sleep", ["5"], timeout=1)
        elapsed = time.time() - start
        self.assertEqual(rc, -1)
        self.assertLess(elapsed, 4.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
