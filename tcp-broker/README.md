# TCP broker

Dependency-free Python 3.10+ relay. It does not execute commands or create shells.
Only server.py is needed. Start it with: python3 server.py

| Role | Port | Authentication |
|---|---|---|
| Sender (controller) | 4444 | Enter the printed access token followed by Enter |
| Receiver | 4445 | No token, prompts, or status banners |

Sender: nc SERVER_ADDRESS 4444
Enter the token, then wait for the Connected banner before sending data.
Receiver: nc SERVER_ADDRESS 4445

Either side can connect first. Unmatched connections wait up to 120 seconds.
Data is relayed in both directions. Only one pair is supported at a time.
Extra connections of the same role are rejected; receivers close silently.
When either paired endpoint disconnects, both close and another pair can connect.
The token changes whenever the broker restarts.

## Hosting

- Allow the sender to reach TCP 4444. Restrict TCP 4445 to your receiving machine's public IP in your firewall. Anyone who can reach 4445 can claim the receiver slot, receive the sender's data, and send replies. The sender token does not verify the receiver.
- Traffic, including the token, is plaintext. Use an encrypted tunnel for sensitive traffic. TLS is not implemented.
- Both ports must reach the same server process.
- No automatic startup or persistence is included. Configure a service to run after SSH disconnects and reboots.
- Public internet connectivity is unverified.

## Development checks

Run: python3 -m unittest -v test_server.py
Local socket tests cover invalid tokens, connection order, transparent receiver data, binary relay, busy rejection, disconnect cleanup, and reuse.
