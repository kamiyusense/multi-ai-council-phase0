def summarize_budget_slots(slots):
    cap = 10

    if len(slots) > cap:
        raise ValueError("budget ledger exceeds the cap")

    # Sort slots to process them in slot order
    slots = sorted(slots, key=lambda s: s['slot'])

    expected_slot = 1
    command_ids = []

    for slot_data in slots:
        slot = slot_data['slot']
        command_id = slot_data['command_id']

        if isinstance(slot, bool) or not isinstance(slot, int):
            raise ValueError("invalid budget slot")

        if slot != expected_slot:
            raise ValueError("budget ledger slots are not contiguous")

        if command_id in command_ids:
            raise ValueError("one command consumed two budget slots")

        command_ids.append(command_id)
        expected_slot += 1

    used = len(slots)
    remaining = cap - used

    return {
        'used': used,
        'cap': cap,
        'remaining': remaining,
        'command_ids': command_ids
    }
