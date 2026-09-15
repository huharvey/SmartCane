"""SC1 串口协议解析、日志兼容和命令白名单单元测试。"""

import json
import unittest

from smartcane_host.protocol import ProtocolError, command_line, parse_line


class ProtocolTests(unittest.TestCase):
    """保证上位机不会误解析启动日志，也不会发送任意命令。"""

    def test_telemetry_json(self):
        payload = {"protocol": "smartcane.telemetry", "version": 1, "distance_cm": 88.2}
        parsed = parse_line("SC1 TEL " + json.dumps(payload))
        self.assertEqual(parsed.kind, "telemetry")
        self.assertEqual(parsed.payload["distance_cm"], 88.2)

    def test_boot_log_is_not_protocol_error(self):
        parsed = parse_line(b"[SmartCane] ready\r\n")
        self.assertEqual(parsed.kind, "log")

    def test_command_whitelist(self):
        self.assertEqual(command_line("light_auto"), b"SC1 CMD LIGHT AUTO\n")
        self.assertEqual(command_line("imu_stream_on"), b"SC1 CMD IMU STREAM ON\n")
        self.assertEqual(command_line("imu_stream_off"), b"SC1 CMD IMU STREAM OFF\n")
        self.assertEqual(command_line("ppg_stream_on"), b"SC1 CMD PPG STREAM ON\n")
        self.assertEqual(command_line("ppg_stream_off"), b"SC1 CMD PPG STREAM OFF\n")
        with self.assertRaises(ProtocolError):
            command_line("arbitrary text")

    def test_imu_csv(self):
        parsed = parse_line(
            "SC1 IMU 12,3456,0.0100,-0.0200,0.9990,1.00,2.00,3.00,"
            "4.00,5.00,6.00,0.9993,3.74,5.00,CANDIDATE,0,1,0,"
            "NORMAL,0,0"
        )
        self.assertEqual(parsed.kind, "imu")
        self.assertEqual(parsed.payload["seq"], 12)
        self.assertAlmostEqual(parsed.payload["a_g"], 0.9993)
        self.assertTrue(parsed.payload["impact"])
        self.assertFalse(parsed.payload["fall_latched"])

    def test_imu_csv_rejects_wrong_field_count(self):
        with self.assertRaises(ProtocolError):
            parse_line("SC1 IMU 1,2,3")

    def test_ppg_header_and_csv(self):
        header = (
            "SC1 PPG HEADER seq,t_ms,red,ir,red_dc,ir_dc,red_ac,ir_ac,"
            "filtered_ir,envelope,peak_candidate,beat_accepted,ibi_ms,finger,"
            "sqi,hr_bpm,spo2_pct,valid,fifo_overflow"
        )
        parsed_header = parse_line(header)
        self.assertEqual(parsed_header.kind, "ppg_header")
        parsed = parse_line(
            "SC1 PPG 8,2040,112000,128000,111900.0,127800.0,100.0,200.0,"
            "160.0,90.0,1,1,833.0,1,0.88,72.0,98.0,1,0"
        )
        self.assertEqual(parsed.kind, "ppg")
        self.assertEqual(parsed.payload["seq"], 8)
        self.assertTrue(parsed.payload["beat_accepted"])
        self.assertAlmostEqual(parsed.payload["sqi"], 0.88)

    def test_ppg_csv_rejects_wrong_field_count(self):
        with self.assertRaises(ProtocolError):
            parse_line("SC1 PPG 1,2,3")

    def test_malformed_json(self):
        with self.assertRaises(ProtocolError):
            parse_line("SC1 TEL {bad}")


if __name__ == "__main__":
    unittest.main()
