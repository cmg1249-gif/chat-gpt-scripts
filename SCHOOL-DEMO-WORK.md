# School-demo connectivity work

## Scope and current branch

This branch adds diagnostics only. It does not change routing order, authentication,
camera/screen/audio controls, terminal behavior, or the existing LAN, Cloudflare and
Pinggy connections. Do not replace deployed demo executables until the branch has
been reviewed, packaged and tested. The baseline is 3.0.3-preview.

The viewer now reports all attempted-route failures, distinguishes empty discovery
from a failed relay connection, states when LAN-only mode disables fallback, and
classifies DNS/TLS/timeout errors without echoing arbitrary exception contents.
Windows and Linux shared source copies are synchronized.

## On-site test checklist

1. Record the exact host and viewer build versions and connection mode. Use matching
   builds and Auto mode; only run hosts on computers authorized for sharing.
2. On each permitted network, complete its captive portal if required. Record a
   generic network label such as guest/staff, not credentials or private addresses.
3. Run the release's generated-media diagnostics from its extracted directory:
   Windows: `.\CheckConnection.exe --internet` and `.\CheckConnection.exe --relay`.
   Confirm the executable name in the release bundle on Linux.
4. Capture the complete viewer failure text, not just a port hint. Distinguish LAN
   discovery, ntfy discovery, Cloudflare and Pinggy results. Redact endpoint URLs,
   keys, pairing codes, cookies, proxy credentials and personal information before
   sharing logs. Do not upload raw logs to this public repository.
5. A home success does not establish school compatibility. Test the actual host and
   viewer arrangement, including different networks. Then test a presentation-length
   authorized session and interruption/reconnect. Preserve a recording as backup.

No school network has been tested by this change. Do not disable certificate checks,
override school DNS policy, change school firewall settings, or enable capture while
collecting connectivity information without appropriate authorization.

## Next decision

Use on-site evidence before adding a transport. If needed, evaluate an additive
outbound HTTPS/WSS relay on TCP 443 with a stable approved hostname and independent
rendezvous. Review proxy compatibility, end-to-end encryption, replay protection,
quotas and hosting/bandwidth costs before deployment. Keep existing routes available.
Neither HTTPS nor port 443 guarantees that a school permits the application.

## Cross-computer handoff

Use this Git branch as the source of truth. Fetch it on the next authorized computer;
do not copy private owner credentials or local profile directories into Git. Record
sanitized findings and exact test/build results here. Keep the deployed working
release separately so diagnostics development cannot disrupt a presentation.

## Validation for this checkpoint (2026-11-12 UTC)

- Windows Python 3.12: all five test modules pass when run in separate processes:
  test_combined 27, test_control 34, test_cursor 7, test_owner 19,
  test_profiles 13 (100 total, including four new diagnostic regressions).
- Aggregate unittest discovery has an existing shared-Flask setup-order error in
  HostTests. Reproduced the same error on the unchanged baseline commit 6245a50;
  it is not claimed as a full aggregate pass.
- git diff --check passed. Shared Windows/Linux listener and test sources match.
- Linux execution, packaged binaries, school connectivity, live camera/audio and
  presentation-length tests have not been performed for this change.
- No release was replaced and no relay infrastructure was deployed.
