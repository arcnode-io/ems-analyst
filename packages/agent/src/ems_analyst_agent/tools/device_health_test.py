"""Unit tests for device_health — pure per-family severity derivation."""

from .device_health import FAMILY_RULES, RawValues, device_family


class TestDeviceFamily:
    def test_strips_trailing_instance_number(self) -> None:
        assert device_family("gpu_node_42") == "gpu_node"

    def test_multi_digit_suffix(self) -> None:
        assert device_family("compute_module_14") == "compute_module"

    def test_no_suffix_is_its_own_family(self) -> None:
        assert device_family("operating_envelope") == "operating_envelope"

    def test_number_not_at_the_end_is_kept(self) -> None:
        assert device_family("relay_1_backup") == "relay_1_backup"


class TestProtectiveRelayRule:
    def setup_method(self) -> None:
        self.derive = FAMILY_RULES["protective_relay"].derive

    def test_trip_true_is_alarm(self) -> None:
        severity, display = self.derive({"trip_status": True, "ground_fault": False})
        assert severity == "alarm"
        assert display == "tripped"

    def test_ground_fault_true_is_alarm(self) -> None:
        severity, display = self.derive({"trip_status": False, "ground_fault": True})
        assert severity == "alarm"
        assert display == "ground fault"

    def test_both_false_is_ok(self) -> None:
        severity, _ = self.derive({"trip_status": False, "ground_fault": False})
        assert severity == "ok"

    def test_no_data_is_ungraded(self) -> None:
        severity, display = self.derive({})
        assert severity is None
        assert display == "unknown"


class TestCoolerRule:
    def setup_method(self) -> None:
        self.derive = FAMILY_RULES["cooler"].derive

    def test_zero_fault_word_is_ok(self) -> None:
        severity, display = self.derive({"fault_word": 0.0})
        assert severity == "ok"
        assert display == "normal"

    def test_nonzero_fault_word_is_alarm(self) -> None:
        severity, display = self.derive({"fault_word": 5.0})
        assert severity == "alarm"
        assert "5" in display

    def test_no_data_is_ungraded(self) -> None:
        severity, _ = self.derive({})
        assert severity is None


class TestNetworkSwitchRule:
    def setup_method(self) -> None:
        self.derive = FAMILY_RULES["network_switch"].derive

    def test_up_is_ok(self) -> None:
        severity, display = self.derive({"port_link_status": "UP"})
        assert severity == "ok"
        assert display == "UP"

    def test_down_is_alarm(self) -> None:
        severity, display = self.derive({"port_link_status": "DOWN"})
        assert severity == "alarm"
        assert display == "DOWN"

    def test_no_data_is_ungraded(self) -> None:
        severity, _ = self.derive({})
        assert severity is None


class TestGpuNodeRule:
    def setup_method(self) -> None:
        self.derive = FAMILY_RULES["gpu_node"].derive

    def test_all_na_is_ok(self) -> None:
        values: RawValues = {f"gpu_{i}_throttle_reason": "NA" for i in range(1, 9)}
        severity, display = self.derive(values)
        assert severity == "ok"
        assert display == "normal"

    def test_one_throttled_is_warn_not_alarm(self) -> None:
        values: RawValues = {f"gpu_{i}_throttle_reason": "NA" for i in range(1, 9)}
        values["gpu_3_throttle_reason"] = "SW_POWER_CAP"
        severity, display = self.derive(values)
        assert severity == "warn"
        assert display == "SW_POWER_CAP"

    def test_multiple_distinct_reasons_deduplicated_and_sorted(self) -> None:
        values: RawValues = {f"gpu_{i}_throttle_reason": "NA" for i in range(1, 9)}
        values["gpu_1_throttle_reason"] = "SW_POWER_CAP"
        values["gpu_2_throttle_reason"] = "SW_POWER_CAP"
        values["gpu_5_throttle_reason"] = "HW_SLOWDOWN"
        severity, display = self.derive(values)
        assert severity == "warn"
        assert display == "HW_SLOWDOWN, SW_POWER_CAP"

    def test_no_data_is_ungraded(self) -> None:
        severity, _ = self.derive({})
        assert severity is None
