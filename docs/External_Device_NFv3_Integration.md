# External Device NFv3 Integration

An external client must implement the same NFv3 session and schema flow as NeuroFlap Monitor.

1. Open a UDP socket and send `CONNECT_REQ` to the firmware export port.
2. Wait for `CONNECT_ACK`; handle `BUSY_ACK` as an occupied single-client session.
3. Send `SCHEMA_REQ` and collect all chunks for one `schema_generation`.
4. Build an `endpoint_no -> descriptor` map.
5. Decode DATA only when its generation matches that map.
6. Reconstruct publish/capture timestamps from the packet `build_us` and item ages.
7. Send `LINK_PING` periodically and expect `LINK_PONG`.
8. Request schema again whenever a new generation appears.

See [NFv3 Dataflow Export Protocol](NFv3_Dataflow_Export_Protocol.md) for binary layouts.
