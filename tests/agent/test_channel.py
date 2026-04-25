from src.agent.channel import ChannelMessage, ChannelResponse


def test_channel_message_stores_fields():
    msg = ChannelMessage(user_id="wa:917845952289", channel="whatsapp", text="check out ravi")
    assert msg.user_id == "wa:917845952289"
    assert msg.channel == "whatsapp"
    assert msg.text == "check out ravi"
    assert msg.media_id is None


def test_channel_response_defaults():
    resp = ChannelResponse(text="Done.", intent="CHECKOUT", role="admin")
    assert resp.interactive_payload is None
