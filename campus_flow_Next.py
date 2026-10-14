#!/usr/bin/env python3
"""
CampusFlow Next - Campus Support Ticket Management System
A reliable Python CLI with validation, structured follow-up notes, 
multi-filter search, trustworthy reports, and safe JSON persistence.
"""

import json
import os
import sys
from typing import Dict, List, Any, Optional, Tuple


# =====================================================================
# CONSTANTS & VALIDATION HELPERS
# =====================================================================

CATEGORIES = {"Network", "Hardware", "Software", "Other"}
URGENCIES = {"low", "medium", "high"}
STATUSES = {"open", "in_progress", "resolved"}
PRIORITIES = {"low", "medium", "high", "critical"}


def normalize_category(raw: str) -> Optional[str]:
    """Normalize and validate category input."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().capitalize()
    return cleaned if cleaned in CATEGORIES else None


def normalize_urgency(raw: str) -> Optional[str]:
    """Normalize and validate urgency input."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().lower()
    return cleaned if cleaned in URGENCIES else None


def validate_title(title: Any) -> Optional[str]:
    """Title must be a non-blank string after trimming."""
    if not isinstance(title, str):
        return None
    cleaned = title.strip()
    return cleaned if cleaned else None


def validate_affected_users(val: Any) -> Optional[int]:
    """Must be a strictly positive integer. Reject floats, bools, and strings."""
    # In Python, isinstance(True, int) is True, so check bool explicitly first!
    if isinstance(val, bool) or not isinstance(val, int):
        return None
    return val if val > 0 else None


def calculate_priority(urgency: str, affected_users: int) -> str:
    """
    Preserve priority rule order:
    - critical when high urgency AND affected_users >= 10
    - otherwise high when high urgency OR affected_users >= 10
    - otherwise medium when medium urgency OR affected_users >= 3
    - otherwise low
    """
    u = urgency.lower()
    if u == "high" and affected_users >= 10:
        return "critical"
    elif u == "high" or affected_users >= 10:
        return "high"
    elif u == "medium" or affected_users >= 3:
        return "medium"
    else:
        return "low"


def validate_ticket_id(tid: Any, existing_ids: Optional[set] = None) -> Optional[str]:
    """Validate ticket ID format (e.g., T001) and optional uniqueness."""
    if not isinstance(tid, str):
        return None
    tid = tid.strip().upper()
    if not (tid.startswith("T") and tid[1:].isdigit() and len(tid) > 1):
        return None
    if existing_ids is not None and tid in existing_ids:
        return None
    return tid


# =====================================================================
# TICKET MANAGER & BUSINESS LOGIC
# =====================================================================

class CampusFlowManager:
    def __init__(self):
        self.tickets: Dict[str, Dict[str, Any]] = {}
        self._next_ticket_num: int = 1

    def generate_ticket_id(self) -> str:
        """Generate the next unique ticket ID like T001, T002, etc."""
        while True:
            tid = f"T{self._next_ticket_num:03d}"
            self._next_ticket_num += 1
            if tid not in self.tickets:
                return tid

    def create_ticket(self, title: str, category: str, urgency: str, 
                      affected_users: int, assigned_to: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
        """
        Create a new ticket with centralized validation.
        Invalid actions leave the ticket collection unchanged.
        """
        clean_title = validate_title(title)
        if not clean_title:
            return False, "Invalid title: must not be blank.", None

        norm_cat = normalize_category(category)
        if not norm_cat:
            return False, f"Invalid category. Must be one of {sorted(CATEGORIES)}.", None

        norm_urg = normalize_urgency(urgency)
        if not norm_urg:
            return False, f"Invalid urgency. Must be one of {sorted(URGENCIES)}.", None

        valid_users = validate_affected_users(affected_users)
        if valid_users is None:
            return False, "Invalid affected_users: must be a strictly positive integer.", None

        clean_assign = assigned_to.strip() if assigned_to else ""

        tid = self.generate_ticket_id()
        priority = calculate_priority(norm_urg, valid_users)

        ticket = {
            "id": tid,
            "title": clean_title,
            "category": norm_cat,
            "urgency": norm_urg,
            "affected_users": valid_users,
            "priority": priority,
            "status": "open",
            "assigned_to": clean_assign,
            "notes": []
        }

        self.tickets[tid] = ticket
        return True, f"Ticket {tid} created successfully.", tid

    def update_assignment(self, tid: str, assigned_to: str) -> Tuple[bool, str]:
        """Assign or reassign a staff member. Resolved tickets cannot change assignment."""
        tid = tid.strip().upper()
        if tid not in self.tickets:
            return False, f"Ticket {tid} not found."

        ticket = self.tickets[tid]
        if ticket["status"] == "resolved":
            return False, "Cannot change assignment on a resolved ticket."

        clean_assign = assigned_to.strip() if assigned_to else ""
        if not clean_assign:
            return False, "Assignment requires a nonempty staff label."

        ticket["assigned_to"] = clean_assign
        return True, f"Ticket {tid} assigned to {clean_assign}."

    def transition_status(self, tid: str, new_status: str) -> Tuple[bool, str]:
        """
        Handle valid status transitions:
        - open -> in_progress (requires assigned_to to be nonempty)
        - in_progress -> resolved
        - resolved -> open (reopening)
        - open -> resolved (allowed directly or via workflow)
        """
        tid = tid.strip().upper()
        if tid not in self.tickets:
            return False, f"Ticket {tid} not found."

        current_status = self.tickets[tid]["status"]
        new_status = new_status.strip().lower()

        if new_status not in STATUSES:
            return False, f"Invalid status: {new_status}."

        if current_status == new_status:
            return False, f"Ticket is already in status '{new_status}'."

        # Rule: Do not let an unassigned open ticket move to in_progress
        if current_status == "open" and new_status == "in_progress":
            if not self.tickets[tid]["assigned_to"]:
                return False, "Cannot move unassigned open ticket to in_progress. Assign staff first."

        # Valid paths: open <-> in_progress <-> resolved, and resolved -> open
        valid_transitions = {
            "open": {"in_progress", "resolved"},
            "in_progress": {"open", "resolved"},
            "resolved": {"open"}
        }

        if new_status not in valid_transitions.get(current_status, set()):
            return False, f"Invalid status transition from '{current_status}' to '{new_status}'."

        self.tickets[tid]["status"] = new_status
        return True, f"Ticket {tid} status changed from {current_status} to {new_status}."

    def add_note(self, tid: str, author: str, message: str) -> Tuple[bool, str]:
        """
        Add a structured follow-up note.
        Only open or in_progress tickets accept a new note.
        Author cannot be blank. Message length must be 5-300 characters after trimming.
        A rejected note must not consume a note ID.
        """
        tid = tid.strip().upper()
        if tid not in self.tickets:
            return False, f"Ticket {tid} not found."

        ticket = self.tickets[tid]
        if ticket["status"] == "resolved":
            return False, "Resolved tickets cannot accept new notes."

        clean_author = author.strip() if author else ""
        if not clean_author:
            return False, "Author label cannot be blank."

        clean_msg = message.strip() if message else ""
        if not (5 <= len(clean_msg) <= 300):
            return False, "Message length must be between 5 and 300 characters after trimming."

        # Compute next note ID for this ticket (e.g., N001, N002)
        notes = ticket["notes"]
        next_note_num = len(notes) + 1
        note_id = f"N{next_note_num:03d}"

        new_note = {
            "note_id": note_id,
            "author": clean_author,
            "message": clean_msg
        }

        notes.append(new_note)
        return True, f"Note {note_id} added successfully to {tid}."

    def search_tickets(self, query: str = "", category: Optional[str] = None, 
                       status: Optional[str] = None, priority: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search titles with case-insensitive substring matching and optional filters.
        Filters work together: ALL must match. Empty filters mean 'do not filter'.
        """
        results = []
        q_lower = query.strip().lower()
        cat_norm = normalize_category(category) if category and category.strip() else None
        stat_norm = status.strip().lower() if status and status.strip() else None
        pri_norm = priority.strip().lower() if priority and priority.strip() else None

        for tid, t in self.tickets.items():
            # Substring match on title
            if q_lower and q_lower not in t["title"].lower():
                continue
            # Category filter
            if cat_norm and t["category"] != cat_norm:
                continue
            # Status filter
            if stat_norm and t["status"] != stat_norm:
                continue
            # Priority filter
            if pri_norm and t["priority"] != pri_norm:
                continue
            results.append(t)

        return results

    def get_open_work_queue(self) -> List[Dict[str, Any]]:
        """
        Original Open Work Queue:
        Shows only OPEN tickets, priority order critical > high > medium > low,
        with earlier numeric ticket IDs first for ties.
        """
        open_tickets = [t for t in self.tickets.values() if t["status"] == "open"]
        
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

        def sort_key(ticket):
            p_rank = priority_rank.get(ticket["priority"], 4)
            # Extract numeric part of ID for tie-breaking
            num_part = int(ticket["id"][1:]) if ticket["id"][1:].isdigit() else 0
            return (p_rank, num_part)

        return sorted(open_tickets, key=sort_key)

    def get_reports(self) -> Dict[str, Any]:
        """
        Trustworthy quality insights:
        total tickets, counts by status, counts by priority, counts by category,
        unresolved count (open + in_progress), resolved count, and resolution percentage.
        """
        total = len(self.tickets)
        status_counts = {"open": 0, "in_progress": 0, "resolved": 0}
        priority_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        category_counts = {cat: 0 for cat in CATEGORIES}

        for t in self.tickets.values():
            st = t["status"]
            if st in status_counts:
                status_counts[st] += 1
            
            pr = t["priority"]
            if pr in priority_counts:
                priority_counts[pr] += 1

            cat = t["category"]
            if cat in category_counts:
                category_counts[cat] += 1

        resolved_count = status_counts["resolved"]
        unresolved_count = status_counts["open"] + status_counts["in_progress"]

        resolution_pct = (resolved_count / total * 100.0) if total > 0 else 0.0

        return {
            "total_tickets": total,
            "status_counts": status_counts,
            "priority_counts": priority_counts,
            "category_counts": category_counts,
            "unresolved_count": unresolved_count,
            "resolved_count": resolved_count,
            "resolution_percentage": round(resolution_pct, 2)
        }

    # =====================================================================
    # PERSISTENCE & FULL VALIDATION ON LOAD
    # =====================================================================

    def save_to_file(self, filepath: str) -> Tuple[bool, str]:
        """Save all tickets and notes to JSON."""
        data = {
            "version": "1.0",
            "next_ticket_num": self._next_ticket_num,
            "tickets": list(self.tickets.values())
        }
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True, f"Successfully saved data to {filepath}."
        except Exception as e:
            return False, f"Failed to save file: {e}"

    def load_from_file(self, filepath: str) -> Tuple[bool, str]:
        """
        Safely load JSON data with thorough upfront validation:
        structure, required keys, ID uniqueness, category/urgency/priority consistency,
        legal statuses, note shapes, and note uniqueness per ticket.
        If invalid, reject load and keep current memory unchanged.
        """
        if not os.path.exists(filepath):
            return False, f"File {filepath} does not exist."

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = json.load(f)
        except Exception as e:
            return False, f"Invalid JSON format: {e}"

        if not isinstance(content, dict):
            return False, "Invalid root structure: expected a JSON object."

        tickets_list = content.get("tickets")
        if not isinstance(tickets_list, list):
            return False, "Invalid schema: 'tickets' key must be a list."

        next_num = content.get("next_ticket_num", 1)
        if not isinstance(next_num, int) or next_num < 1:
            next_num = 1

        validated_tickets = {}
        seen_ids = set()

        required_keys = {"id", "title", "category", "urgency", "affected_users", "priority", "status", "assigned_to", "notes"}

        for idx, t in enumerate(tickets_list):
            if not isinstance(t, dict):
                return False, f"Ticket at index {idx} is not a dictionary."

            if not required_keys.issubset(t.keys()):
                missing = required_keys - t.keys()
                return False, f"Ticket at index {idx} missing required keys: {missing}."

            # Validate ID
            tid = validate_ticket_id(t["id"], seen_ids)
            if not tid:
                return False, f"Invalid or duplicate ticket ID at index {idx}: {t.get('id')}"
            seen_ids.add(tid)

            # Validate Title
            title = validate_title(t["title"])
            if not title:
                return False, f"Invalid title in ticket {tid}."

            # Validate Category
            cat = normalize_category(t["category"])
            if not cat:
                return False, f"Invalid category '{t.get('category')}' in ticket {tid}."

            # Validate Urgency
            urg = normalize_urgency(t["urgency"])
            if not urg:
                return False, f"Invalid urgency '{t.get('urgency')}' in ticket {tid}."

            # Validate Affected Users
            aff = validate_affected_users(t["affected_users"])
            if aff is None:
                return False, f"Invalid affected_users '{t.get('affected_users')}' in ticket {tid}."

            # Verify Priority consistency
            expected_priority = calculate_priority(urg, aff)
            if t["priority"] != expected_priority:
                return False, f"Priority mismatch in ticket {tid}: got '{t["priority"]}', expected '{expected_priority}'."

            # Validate Status
            status = t["status"]
            if status not in STATUSES:
                return False, f"Invalid status '{status}' in ticket {tid}."

            # Validate Assigned To
            assigned = t["assigned_to"]
            if not isinstance(assigned, str):
                return False, f"Invalid assigned_to type in ticket {tid}."

            # Validate Notes
            notes = t["notes"]
            if not isinstance(notes, list):
                return False, f"Invalid notes structure in ticket {tid}: must be a list."

            seen_note_ids = set()
            validated_notes = []
            for n_idx, note in enumerate(notes):
                if not isinstance(note, dict):
                    return False, f"Note at index {n_idx} in ticket {tid} is not a dictionary."
                if not {"note_id", "author", "message"}.issubset(note.keys()):
                    return False, f"Note at index {n_idx} in ticket {tid} missing required keys."

                n_id = note["note_id"]
                if not isinstance(n_id, str) or not n_id.startswith("N"):
                    return False, f"Invalid note ID format '{n_id}' in ticket {tid}."
                if n_id in seen_note_ids:
                    return False, f"Duplicate note ID '{n_id}' in ticket {tid}."
                seen_note_ids.add(n_id)

                author = note["author"]
                if not isinstance(author, str) or not author.strip():
                    return False, f"Invalid author in note {n_id} for ticket {tid}."

                msg = note["message"]
                if not isinstance(msg, str) or not (5 <= len(msg.strip()) <= 300):
                    return False, f"Invalid message length in note {n_id} for ticket {tid}."

                validated_notes.append({
                    "note_id": n_id,
                    "author": author.strip(),
                    "message": msg.strip()
                })

            validated_tickets[tid] = {
                "id": tid,
                "title": title,
                "category": cat,
                "urgency": urg,
                "affected_users": aff,
                "priority": expected_priority,
                "status": status,
                "assigned_to": assigned.strip(),
                "notes": validated_notes
            }

        # If all valid, update state safely
        self.tickets = validated_tickets
        self._next_ticket_num = max(next_num, len(self.tickets) + 1)
        return True, f"Successfully loaded {len(self.tickets)} tickets from {filepath}."


# =====================================================================
# INTERACTIVE CLI USER INTERFACE
# =====================================================================

def print_banner():
    print("=" * 60)
    print("       CAMPUSFLOW NEXT — Campus Support Management       ")
    print("=" * 60)


def print_ticket_row(t: Dict[str, Any]):
    print(f"[{t['id']}] {t['title'][:35]:<35} | Cat: {t['category']:<10} | Pri: {t['priority']:<8} | Stat: {t['status']:<11} | Assign: {t['assigned_to'] or 'Unassigned'}")


def interactive_cli():
    manager = CampusFlowManager()
    data_file = "campusflow_data.json"

    # Auto-load if file exists
    if os.path.exists(data_file):
        success, msg = manager.load_from_file(data_file)
        print(f"[Auto-load] {msg}")

    while True:
        print_banner()
        print("1. Create New Ticket")
        print("2. Open Work Queue")
        print("3. View / Search Tickets (Multi-filter)")
        print("4. Update Assignment")
        print("5. Change Ticket Status (Open / In Progress / Resolved / Reopen)")
        print("6. Add Follow-up Note")
        print("7. View Ticket Notes")
        print("8. View Reports & Analytics")
        print("9. Save Data to JSON")
        print("10. Load Data from JSON")
        print("0. Exit")
        print("-" * 60)

        choice = input("Select an option (0-10): ").strip()

        if choice == "1":
            print("\n--- Create New Ticket ---")
            title = input("Title: ")
            print(f"Categories available: {sorted(CATEGORIES)}")
            category = input("Category: ")
            print(f"Urgency levels available: {sorted(URGENCIES)}")
            urgency = input("Urgency: ")
            try:
                affected_users = int(input("Affected Users (integer): "))
            except ValueError:
                print("Error: Affected users must be an integer.")
                continue
            assigned_to = input("Assign to staff (optional, press Enter to leave blank): ").strip()

            success, msg, tid = manager.create_ticket(title, category, urgency, affected_users, assigned_to if assigned_to else None)
            print(f"\n{msg}")

        elif choice == "2":
            print("\n--- Open Work Queue (Priority Order) ---")
            queue = manager.get_open_work_queue()
            if not queue:
                print("No open tickets in the work queue.")
            else:
                for t in queue:
                    print_ticket_row(t)

        elif choice == "3":
            print("\n--- Search & Multi-filter Tickets ---")
            query = input("Search title substring (leave blank for all): ")
            print(f"Categories: {sorted(CATEGORIES)} (Leave blank to skip)")
            cat_filt = input("Category filter: ")
            print(f"Statuses: {sorted(STATUSES)} (Leave blank to skip)")
            stat_filt = input("Status filter: ")
            print(f"Priorities: {sorted(PRIORITIES)} (Leave blank to skip)")
            pri_filt = input("Priority filter: ")

            results = manager.search_tickets(query, cat_filt, stat_filt, pri_filt)
            print(f"\nFound {len(results)} matching ticket(s):")
            for t in results:
                print_ticket_row(t)

        elif choice == "4":
            print("\n--- Update Assignment ---")
            tid = input("Ticket ID (e.g. T001): ")
            assigned_to = input("New staff label: ")
            success, msg = manager.update_assignment(tid, assigned_to)
            print(f"\n{msg}")

        elif choice == "5":
            print("\n--- Change Ticket Status ---")
            tid = input("Ticket ID (e.g. T001): ")
            if tid.upper() in manager.tickets:
                curr = manager.tickets[tid.upper()]['status']
                print(f"Current status for {tid.upper()} is '{curr}'.")
            print(f"Available statuses: {sorted(STATUSES)}")
            new_stat = input("New status: ")
            success, msg = manager.transition_status(tid, new_stat)
            print(f"\n{msg}")

        elif choice == "6":
            print("\n--- Add Follow-up Note ---")
            tid = input("Ticket ID (e.g. T001): ")
            author = input("Author label: ")
            message = input("Note message (5-300 characters): ")
            success, msg = manager.add_note(tid, author, message)
            print(f"\n{msg}")

        elif choice == "7":
            print("\n--- View Ticket Notes ---")
            tid = input("Ticket ID (e.g. T001): ").strip().upper()
            if tid not in manager.tickets:
                print(f"Ticket {tid} not found.")
            else:
                t = manager.tickets[tid]
                print(f"\nNotes for {tid}: {t['title']}")
                if not t["notes"]:
                    print("No notes recorded yet.")
                else:
                    for n in t["notes"]:
                        print(f"  [{n['note_id']}] By {n['author']}: {n['message']}")

        elif choice == "8":
            print("\n--- Reports & Quality Insights ---")
            rep = manager.get_reports()
            print(f"Total Tickets          : {rep['total_tickets']}")
            print(f"Unresolved Count       : {rep['unresolved_count']}")
            print(f"Resolved Count         : {rep['resolved_count']}")
            print(f"Resolution Percentage  : {rep['resolution_percentage']}%")
            print("\nStatus Breakdown:")
            for st, count in rep['status_counts'].items():
                print(f"  - {st:<12}: {count}")
            print("\nPriority Breakdown:")
            for pr, count in rep['priority_counts'].items():
                print(f"  - {pr:<12}: {count}")
            print("\nCategory Breakdown:")
            for cat, count in rep['category_counts'].items():
                print(f"  - {cat:<12}: {count}")

        elif choice == "9":
            success, msg = manager.save_to_file(data_file)
            print(f"\n{msg}")

        elif choice == "10":
            success, msg = manager.load_from_file(data_file)
            print(f"\n{msg}")

        elif choice == "0":
            print("\nThank you for using CampusFlow Next. Goodbye!")
            sys.exit(0)
        else:
            print("\nInvalid choice. Please enter a number between 0 and 10.")

        input("\nPress Enter to continue...")


if __name__ == "__main__":
    interactive_cli()