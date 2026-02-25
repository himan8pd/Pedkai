import asyncio
from backend.app.events.bus import initialize_event_bus, get_event_bus
from backend.app.events.schemas import AlarmIngestedEvent
from backend.app.workers.handlers import handle_event, flush_buffer

async def run_test():
    initialize_event_bus()

    a1 = AlarmIngestedEvent(
        tenant_id='test-tenant',
        entity_id='entity-1',
        entity_external_id='ext-1',
        alarm_type='LINK_DOWN',
        severity='major',
        raised_at='2026-02-23T19:30:00Z',
        source_system='snmp'
    )
    a2 = AlarmIngestedEvent(
        tenant_id='test-tenant',
        entity_id='entity-1',
        entity_external_id='ext-1',
        alarm_type='LINK_DOWN',
        severity='major',
        raised_at='2026-02-23T19:31:00Z',
        source_system='snmp'
    )

    await handle_event(a1)
    await handle_event(a2)

    # Force flush (tests should use this helper instead of waiting 5 minutes)
    await flush_buffer('test-tenant')

    q = get_event_bus()
    out = []
    while not q.empty():
        ev = q.get_nowait()
        out.append((type(ev).__name__, ev.event_type, getattr(ev,'alarm_count',None)))
        q.task_done()
    print('PUBLISHED', out)

if __name__ == '__main__':
    asyncio.run(run_test())
