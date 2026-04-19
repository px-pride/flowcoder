"""Engine refactor Phase 2 smoke test."""
import asyncio
from src.services.service_factory import ServiceFactory
from src.utils.sdk_message_parser import parse_sdk_message


async def main():
    svc = ServiceFactory.create_service('claude', cwd='/tmp', model='haiku')
    await svc.start_session()
    print(f"Session active: {svc.is_active()}")

    chunks = 0
    text = ""
    type_counts = {}
    async for chunk in svc.stream_prompt("Say only the word READY"):
        chunks += 1
        t, _, mt = parse_sdk_message(chunk)
        type_counts[mt] = type_counts.get(mt, 0) + 1
        if t and mt in ("assistant", "assistant_plain"):
            text += t

    print(f"chunks={chunks}, type_counts={type_counts}")
    print(f"text={text!r}")

    # Second prompt to verify session reuse
    text2 = ""
    async for chunk in svc.stream_prompt("Now say the word DONE"):
        t, _, mt = parse_sdk_message(chunk)
        if t and mt in ("assistant", "assistant_plain"):
            text2 += t
    print(f"text2={text2!r}")

    await svc.end_session()
    print("Session ended cleanly")


async def walker_smoke():
    """Verify GUISessionAdapter wraps the engine service correctly."""
    from src.adapters.gui_session import GUISessionAdapter

    svc = ServiceFactory.create_service('claude', cwd='/tmp', model='haiku')
    adapter = GUISessionAdapter(svc, name="walker-test")
    await adapter.start()
    print(f"\n[walker] running={adapter.is_running}")

    qr = await adapter.query("Reply with the single word PASS")
    print(f"[walker] response={qr.response_text!r}")
    print(f"[walker] duration_ms={qr.duration_ms}")

    await adapter.stop()
    print(f"[walker] stopped, running={adapter.is_running}")


asyncio.run(main())
asyncio.run(walker_smoke())
