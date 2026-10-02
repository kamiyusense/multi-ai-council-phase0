def summarize_budget_slots(slots: list[dict[str, str | int]]) -> dict[str, int | list[str]]:
    if not isinstance(slots, list):
        raise ValueError("slots must be a list")

    if len(slots) > 10:
        raise ValueError("more than 10 slots given")

    command_ids = set()
    for s in slots:
        if not isinstance(s, dict):
            raise ValueError("slot must be a dict")
        slot_val = s.get('slot')
        if type(slot_val) is not int:
            raise ValueError("slot number must be an int")
        cmd_id = s.get('command_id')
        if cmd_id in command_ids:
            raise ValueError("repeated command id")
        command_ids.add(cmd_id)

    sorted_slots = sorted(slots, key=lambda x: x['slot'])

    if [s['slot'] for s in sorted_slots] != list(range(1, len(sorted_slots) + 1)):
        raise ValueError("slot numbers are not exactly 1..len(slots)")

    return {
        'used': len(slots),
        'cap': 10,
        'remaining': 10 - len(slots),
        'command_ids': [s['command_id'] for s in sorted_slots]
    }
