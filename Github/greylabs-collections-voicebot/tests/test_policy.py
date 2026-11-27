import unittest
from server.policy import classify_message, validate_outcome, Action


class PolicyTests(unittest.TestCase):
    def test_job_loss_escalates(self):
        self.assertEqual(classify_message("I lost my job").action, Action.ESCALATE)

    def test_medical_emergency_escalates(self):
        self.assertEqual(classify_message("My mother is in the hospital").action, Action.ESCALATE)

    def test_callback_time_is_captured_when_expected(self):
        self.assertEqual(
            classify_message("Tomorrow morning, 9 AM", awaiting_callback_time=True).action,
            Action.CAPTURE_CALLBACK,
        )

    def test_ptp_classification(self):
        self.assertEqual(classify_message("I will pay tomorrow").action, Action.CAPTURE_PTP)

    def test_callback_nonempty_validation_limitation(self):
        # Documents the current known weakness: non-empty text passes even if incomplete.
        ok, _ = validate_outcome({"outcome_type": "Callback-Request", "callback_time": "Tomorrow,"})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
