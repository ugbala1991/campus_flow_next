import unittest
import os
import json
from campusflow_next import CampusFlowManager, calculate_priority


class TestCampusFlowNext(unittest.TestCase):

    def setUp(self):
        self.manager = CampusFlowManager()

    def test_priority_calculation(self):
        # critical: high urgency AND affected_users >= 10
        self.assertEqual(calculate_priority("high", 10), "critical")
        self.assertEqual(calculate_priority("high", 15), "critical")
        # high: high urgency OR affected_users >= 10
        self.assertEqual(calculate_priority("high", 5), "high")
        self.assertEqual(calculate_priority("medium", 12), "high")
        # medium: medium urgency OR affected_users >= 3
        self.assertEqual(calculate_priority("medium", 4), "medium")
        self.assertEqual(calculate_priority("low", 5), "medium")
        # low
        self.assertEqual(calculate_priority("low", 2), "low")

    def test_ticket_creation_and_validation(self):
        # Valid creation
        success, msg, tid = self.manager.create_ticket("Wi-Fi down in Library", "Network", "high", 12, "Alice")
        self.assertTrue(success)
        self.assertEqual(tid, "T001")
        t = self.manager.tickets["T001"]
        self.assertEqual(t["priority"], "critical")
        self.assertEqual(t["status"], "open")

        # Invalid affected users (float, bool, string)
        success, msg, _ = self.manager.create_ticket("Test", "Hardware", "low", 2.5, "Bob")
        self.assertFalse(success)
        success, msg, _ = self.manager.create_ticket("Test", "Hardware", "low", True, "Bob")
        self.assertFalse(success)
        success, msg, _ = self.manager.create_ticket("Test", "Hardware", "low", "5", "Bob")
        self.assertFalse(success)

    def test_status_safety_and_assignment(self):
        _, _, tid = self.manager.create_ticket("Projector broken", "Hardware", "medium", 5)
        
        # Unassigned open ticket cannot move to in_progress
        success, msg = self.manager.transition_status(tid, "in_progress")
        self.assertFalse(success)

        # Assign ticket
        success, msg = self.manager.update_assignment(tid, "Charlie")
        self.assertTrue(success)

        # Now can move to in_progress
        success, msg = self.manager.transition_status(tid, "in_progress")
        self.assertTrue(success)
        self.assertEqual(self.manager.tickets[tid]["status"], "in_progress")

        # Move to resolved
        success, msg = self.manager.transition_status(tid, "resolved")
        self.assertTrue(success)

        # Resolved tickets cannot accept notes or assignment changes
        success, msg = self.manager.update_assignment(tid, "Dave")
        self.assertFalse(success)

        # Reopen resolved ticket
        success, msg = self.manager.transition_status(tid, "open")
        self.assertTrue(success)
        self.assertEqual(self.manager.tickets[tid]["status"], "open")

    def test_structured_notes_workflow(self):
        _, _, tid = self.manager.create_ticket("Canvas LMS error", "Software", "low", 2, "Admin")
        
        # Add note successfully
        success, msg = self.manager.add_note(tid, "Mentor A", "Router reboot attempted successfully.")
        self.assertTrue(success)
        
        # Rejected note due to length (< 5 chars) must not consume note ID
        success, msg = self.manager.add_note(tid, "Mentor A", "Bad")
        self.assertFalse(success)
        
        success, msg = self.manager.add_note(tid, "Mentor B", "Investigating switch ports now.")
        self.assertTrue(success)

        notes = self.manager.tickets[tid]["notes"]
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["note_id"], "N001")
        self.assertEqual(notes[1]["note_id"], "N002")

        # Resolve ticket -> notes locked
        self.manager.transition_status(tid, "resolved")
        success, msg = self.manager.add_note(tid, "Mentor C", "Should fail.")
        self.assertFalse(success)

        # Reopen -> notes allowed again
        self.manager.transition_status(tid, "open")
        success, msg = self.manager.add_note(tid, "Mentor C", "Reopened investigation note.")
        self.assertTrue(success)
        self.assertEqual(self.manager.tickets[tid]["notes"][2]["note_id"], "N003")

    def test_search_and_filtering(self):
        self.manager.create_ticket("Wi-Fi slow in Hall A", "Network", "high", 20, "Staff 1")
        self.manager.create_ticket("Wi-Fi disconnects", "Network", "medium", 2, "Staff 2")
        self.manager.create_ticket("Printer jammed", "Hardware", "low", 1, "Staff 3")

        # Substring case-insensitive search + filters
        res = self.manager.search_tickets("wi-fi", category="Network", status="open")
        self.assertEqual(len(res), 2)

        res2 = self.manager.search_tickets("printer", category="Hardware")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["id"], "T003")

    def test_reports_and_analytics(self):
        _, _, t1 = self.manager.create_ticket("Issue 1", "Network", "high", 10)
        _, _, t2 = self.manager.create_ticket("Issue 2", "Hardware", "low", 1)
        
        self.manager.update_assignment(t1, "Alice")
        self.manager.transition_status(t1, "resolved")

        rep = self.manager.get_reports()
        self.assertEqual(rep["total_tickets"], 2)
        self.assertEqual(rep["resolved_count"], 1)
        self.assertEqual(rep["unresolved_count"], 1)
        self.assertEqual(rep["resolution_percentage"], 50.0)

    def test_json_persistence_and_safety(self):
        test_file = "test_data.json"
        self.manager.create_ticket("Test persistence", "Software", "medium", 5, "Tester")
        self.manager.add_note("T001", "Author 1", "Note message content here.")
        self.manager.save_to_file(test_file)

        new_manager = CampusFlowManager()
        success, msg = new_manager.load_from_file(test_file)
        self.assertTrue(success)
        self.assertIn("T001", new_manager.tickets)
        self.assertEqual(len(new_manager.tickets["T001"]["notes"]), 1)

        # Test corrupt JSON rejection
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("INVALID JSON")

        success, msg = new_manager.load_from_file(test_file)
        self.assertFalse(success)

        if os.path.exists(test_file):
            os.remove(test_file)


if __name__ == "__main__":
    unittest.main()