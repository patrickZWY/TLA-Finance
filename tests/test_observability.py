import json
import logging
import os
import unittest
from unittest.mock import patch

import observability


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class ObservabilityTests(unittest.TestCase):
    def test_config_loads_from_environment(self):
        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_ENABLED": "0",
                "OBSERVE_PAYLOADS": "1",
                "LOG_FORMAT": "json",
                "LOG_LEVEL": "WARNING",
            },
            clear=False,
        ):
            config = observability.ObservabilityConfig.from_env()

        self.assertFalse(config.enabled)
        self.assertTrue(config.observe_payloads)
        self.assertEqual(config.log_format, "json")
        self.assertEqual(config.log_level, logging.WARNING)

    def test_correlation_id_creation_and_propagation(self):
        request_id = observability.new_id("req")
        with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "1"}, clear=False):
            with observability.scoped_context(request_id=request_id):
                record = observability.log_event("tests.observability", "example")
        self.assertTrue(request_id.startswith("req_"))
        self.assertEqual(record["request_id"], request_id)

    def test_disabled_mode_emits_no_records(self):
        logger = logging.getLogger("tests.observability.disabled")
        handler = CaptureHandler()
        logger.addHandler(handler)
        try:
            with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "0"}, clear=False):
                record = observability.log_event(logger.name, "disabled")
        finally:
            logger.removeHandler(handler)
        self.assertIsNone(record)
        self.assertEqual(handler.messages, [])

    def test_json_log_mode_produces_parseable_records(self):
        logger = logging.getLogger("tests.observability.json")
        logger.setLevel(logging.INFO)
        handler = CaptureHandler()
        logger.addHandler(handler)
        try:
            with patch.dict(
                os.environ,
                {"OBSERVABILITY_ENABLED": "1", "LOG_FORMAT": "json"},
                clear=False,
            ):
                observability.log_event(logger.name, "json_event", status="ok")
        finally:
            logger.removeHandler(handler)
        parsed = json.loads(handler.messages[-1])
        self.assertEqual(parsed["event"], "json_event")
        self.assertEqual(parsed["status"], "ok")

    def test_log_event_does_not_configure_root_logging(self):
        with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "1"}, clear=False):
            with patch("logging.basicConfig") as basic_config:
                observability.log_event("tests.observability.no_basic_config", "event")
        basic_config.assert_not_called()

    def test_payload_redaction_is_default(self):
        with patch.dict(
            os.environ,
            {"OBSERVABILITY_ENABLED": "1", "OBSERVE_PAYLOADS": "0"},
            clear=False,
        ):
            record = observability.log_event(
                "tests.observability.redaction",
                "payload_event",
                message="user finance text",
                args={"amount": 500},
            )
        self.assertEqual(record["message"], "[redacted]")
        self.assertEqual(record["args"], "[redacted]")

    def test_operation_logs_success_and_exception(self):
        logger = logging.getLogger("tests.observability.operation")
        logger.setLevel(logging.INFO)
        handler = CaptureHandler()
        logger.addHandler(handler)
        try:
            with patch.dict(
                os.environ,
                {"OBSERVABILITY_ENABLED": "1", "LOG_FORMAT": "json"},
                clear=False,
            ):
                with observability.operation(logger, "operation.success", component="test") as event:
                    event.add_fields(result_count=2)

                with self.assertRaises(ValueError):
                    with observability.operation(logger, "operation.error"):
                        raise ValueError("boom")
        finally:
            logger.removeHandler(handler)

        records = [json.loads(message) for message in handler.messages]
        success = next(record for record in records if record["event"] == "operation.success")
        error = next(record for record in records if record["event"] == "operation.error")
        self.assertEqual(success["status"], "ok")
        self.assertEqual(success["component"], "test")
        self.assertEqual(success["result_count"], 2)
        self.assertIsInstance(success["duration_ms"], int)
        self.assertEqual(error["status"], "error")
        self.assertEqual(error["error_type"], "ValueError")

    def test_event_sink_can_be_replaced(self):
        class CaptureSink:
            def __init__(self):
                self.records = []

            def emit(self, logger, level, record, config):
                self.records.append((logger.name, level, record, config.log_format))

        sink = CaptureSink()
        observability.set_event_sink(sink)
        try:
            with patch.dict(os.environ, {"OBSERVABILITY_ENABLED": "1", "LOG_FORMAT": "json"}, clear=False):
                record = observability.log_event("tests.observability.sink", "sink_event", status="ok")
        finally:
            observability.set_event_sink(observability.LoggingEventSink())

        self.assertEqual(record["event"], "sink_event")
        self.assertEqual(sink.records[0][0], "tests.observability.sink")
        self.assertEqual(sink.records[0][2]["status"], "ok")
        self.assertEqual(sink.records[0][3], "json")


if __name__ == "__main__":
    unittest.main()
