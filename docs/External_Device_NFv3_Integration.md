# External Device NFv3 Integration

An external client follows the same NFv3 session and schema flow as NeuroFlap Monitor.

1. Open a UDP socket and send `CONNECT_REQ` to the firmware export port.
2. Wait for `CONNECT_ACK`; handle `BUSY_ACK` as an occupied single-client session.
3. Send `SCHEMA_REQ` and collect all chunks for one `schema_generation`.
4. Install the Task layout, map TaskPorts by `(task_id, direction, slot)`, and map DataNodes by `node_no`.
5. Decode DATA only when its generation matches the installed schema.
6. Parse each TaskFrame using the counts in its Task schema; parse fixed 11-byte DataNodeFrames afterward.
7. Reconstruct event timestamps as `packet_time_us - age_us`.
8. Send `LINK_PING` periodically and expect `LINK_PONG`.
9. Request schema again whenever an unknown generation appears.

See [NFv3 TaskIO/DataNode Export Protocol](NFv3_Dataflow_Export_Protocol.md) for exact binary layouts.
