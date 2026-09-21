# TCP broker

Dependency-free Python 3.10+ server that pairs two authenticated TCP connections
and relays bytes in both directions. It does not execute commands or create a shell.

## Run

```sh
python server.py
```

The server listens on all IPv4 interfaces on TCP port 4444 and prints a randomly
generated access token. The token changes whenever the process restarts.

Connect each endpoint using `nc SERVER_ADDRESS 4444`, then enter the printed token
followed by Enter. The first endpoint waits up to 120 seconds for the second.
After both receive the connection banner, their subsequent bytes are relayed.
Only one pair is supported at a time. When either endpoint disconnects, both
connections close and the broker becomes available for another pair.

## Hosting and limitations

- Run on a publicly reachable host and allow incoming TCP port 4444, or expose
  internal port 4444 through a hosting provider's TCP proxy. Both endpoints connect
  to the host's public address and external port.
- Keep one server process/replica running so both endpoints reach the same broker.
- Traffic, including the token, is plaintext. Use an encrypted tunnel or trusted
  network; this version does not implement TLS.
- Authentication prompts and status banners are part of this protocol. This is
  not a drop-in transparent relay for a shell attached directly to netcat: an
  endpoint must handle authentication and consume banners before attaching a shell.
- No persistence, automatic startup, or hosted deployment is included.

Local checks exercised invalid-token rejection, pairing, bidirectional binary
relay, busy rejection, disconnect cleanup, and reuse. Public internet connectivity
has not been tested.
