import pytest

from healthtech_qa import Appointment, notification


def test_cancelled_notice_excludes_old_schedule_and_patient_details():
    appointment = Appointment(appointment_id="visit-42", status="cancelled",
                              starts_at="2026-09-22 10:00", portal_url="https://portal.example/visits")
    message = notification(appointment)
    assert "cancelled" in message
    assert "2026-09-22" not in message
    assert "https://portal.example/visits" in message


def test_rescheduled_notice_requires_new_time():
    appointment = Appointment(appointment_id="visit-42", status="rescheduled",
                              portal_url="https://portal.example/visits")
    with pytest.raises(ValueError, match="starts_at"):
        notification(appointment)
