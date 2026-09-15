"""自动串口选择和模块自检规则测试。"""

import unittest
from types import SimpleNamespace

from smartcane_host.diagnostics import (
    CheckState,
    DiagnosticsEngine,
    best_serial_port,
    serial_port_score,
)


class DiagnosticsTests(unittest.TestCase):
    def test_bluetooth_port_is_never_auto_selected(self):
        bluetooth = SimpleNamespace(
            device="COM5", description="蓝牙链接上的标准串行", manufacturer="",
            hwid="BTHENUM", vid=None, pid=None,
        )
        self.assertLess(serial_port_score(bluetooth), 0)
        self.assertIsNone(best_serial_port([bluetooth]))

    def test_usb_ttl_is_preferred(self):
        bluetooth = SimpleNamespace(
            device="COM5", description="Bluetooth Serial", manufacturer="",
            hwid="BTHENUM", vid=None, pid=None,
        )
        ch340 = SimpleNamespace(
            device="COM8", description="USB-SERIAL CH340", manufacturer="wch.cn",
            hwid="USB VID:PID=1A86:7523", vid=0x1A86, pid=0x7523,
        )
        self.assertEqual(best_serial_port([bluetooth, ch340]).device, "COM8")

    def test_boot_logs_update_module_checks(self):
        engine = DiagnosticsEngine()
        engine.set_serial(True, "COM8")
        engine.consume_log("[I2C] devices: 0x23 0x3C 0x57")
        engine.consume_log("[BH1750] online")
        engine.consume_log("[Sonar] online at 0x57")
        engine.consume_log("[OLED] online")
        engine.consume_log("[FreeRTOS] Sensor/Decision/Actuator=Core1, Network/Telemetry=Core0")
        states = {result.key: result.state for result in engine.results()}
        self.assertEqual(states["i2c"], CheckState.OK)
        self.assertEqual(states["light"], CheckState.OK)
        self.assertEqual(states["sonar"], CheckState.OK)
        self.assertEqual(states["oled"], CheckState.OK)
        self.assertEqual(states["freertos"], CheckState.OK)

    def test_telemetry_marks_core_chain_ok(self):
        engine = DiagnosticsEngine()
        engine.set_serial(True, "COM8")
        engine.consume_log("[I2C] devices: 0x23 0x3C 0x57")
        engine.consume_log("[OLED] online")
        engine.consume_telemetry({
            "protocol": "smartcane.telemetry",
            "version": 1,
            "distance_cm": 81.2,
            "lux": 35.0,
            "camera": True,
            "imu": {"valid": True},
            "gps": {"valid": False, "satellites": 0},
            "vitals": {"online": True, "finger": False},
            "mqtt": {"enabled": True, "connected": True, "state": "ONLINE"},
        })
        state, text = engine.overall()
        self.assertEqual(state, CheckState.OK)
        self.assertIn("正常", text)

    def test_stale_telemetry_fails_core_chain(self):
        engine = DiagnosticsEngine()
        engine.set_serial(True, "COM8")
        engine.consume_protocol("telemetry")
        engine.mark_telemetry_stale(3.2)
        state, _ = engine.overall()
        self.assertEqual(state, CheckState.FAIL)


if __name__ == "__main__":
    unittest.main()
