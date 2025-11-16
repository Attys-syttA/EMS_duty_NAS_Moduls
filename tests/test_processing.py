import datetime as dt
from EMS_Duty_Moduls.processing import process_duty_message, deduplicate_log, make_person_key, get_time_for_period
from EMS_Duty_Moduls import state

def test_process_felvette(tmp_path):
    # Create a simple embed-like dict
    embed = {"title": "John Doe (JD) felvette a szolgálatot", "description": "Mentő - Orvos"}
    msg = {"embed": embed, "id": 111, "created_at": dt.datetime(2025, 11, 14, 10, 0)}
    initial = len(state.duty_log)
    ok = process_duty_message(msg)
    assert ok is True
    assert len(state.duty_log) >= initial
    rec = [r for r in state.duty_log if r.get('message_id') == 111][0]
    assert rec['type'] == 'felvette'
    assert rec['position'].startswith('Mentő')
    assert rec['person_key'] == make_person_key(rec['name_norm'], rec['fivem_name'])


def test_process_leadta(tmp_path):
    embed = {"title": "John Doe (JD) leadta a szolgálatot", "description": "Mentő - Orvos\nszolgálatban töltött idő: 120 perc"}
    msg = {"embed": embed, "id": 222, "created_at": dt.datetime(2025, 11, 14, 12, 0)}
    ok = process_duty_message(msg)
    assert ok is True
    rec = [r for r in state.duty_log if r.get('message_id') == 222][0]
    assert rec['type'] == 'leadta'
    assert rec['duration'] == 120


def test_get_time_for_period(tmp_path):
    # Use existing state entries
    start = dt.datetime(2025, 11, 14, 0, 0)
    end = dt.datetime(2025, 11, 15, 0, 0)
    results = get_time_for_period(start, end)
    # results should be a list (even empty)
    assert isinstance(results, list)
