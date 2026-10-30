# Native E2EE reaction timestamp fix

The pinned fbchat-v2 2.3.4 bridge sends E2EE reactions without `SenderTimestampMS`. Its pinned mautrix-meta connector sets that field when sending reactions. The source patch in this repository adds the current Unix millisecond timestamp and a `hello` capability named `e2eeReactionTimestamp`. Regular Messenger reactions already receive timestamps in `SendReactionTask.Create()` and are unchanged.

This corrects a payload difference found while investigating reactions visible on web but absent in the recipient's mobile app. It has **not yet been verified against a real Messenger mobile app**. An RPC acknowledgement is not proof of delivery or display. No old reactions are replayed. Python also refuses to send a regular reaction for a known encrypted thread lacking an authoritative native message reference.

## Install on the VPS

Stop the text bot, update the repository, and run `python3 setup_bot.py` before starting it again. Normal installation needs Python 3.11+, not a Go compiler or a BSDIFF package. Device files, cookies and conversation history are not replaced.

Only the Linux amd64 bridge has a prebuilt fix. Other platforms retain their upstream binary and use the text fallback for native E2EE reactions until a compatible patched build is available. Regular reactions remain available.

## Pinned inputs and reproduction

- Source: [fbchat-v2 v2.3.4](https://github.com/m008v/fbchat-v2/tree/aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6), commit `aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6`.
- Recursive `bridge-e2ee/meta` submodule: [mautrix/meta](https://github.com/mautrix/meta/tree/cea2e38c9107be591bcd1b7a6562ccc72400ce23), commit `cea2e38c9107be591bcd1b7a6562ccc72400ce23`.
- Corresponding modification and Go tests: [source patch](../patches/fbchat-v2-2.3.4-reaction-timestamp.patch). Other dependency source revisions are in the pinned `go.mod`/`go.sum`.
- Compiler: Go **1.26.10**, Linux amd64, `CGO_ENABLED=0`, `GOTOOLCHAIN=local`.
- Build flags: `-trimpath -buildvcs=false -ldflags '-s -w -buildid='`.
- All SHA-256 pins are in [assets.json](../assets.json), including the source patch and output binary. A second fresh clone/build was verified to produce the same binary hash.

With Git and Go 1.26.10 installed, reproduce from public sources without account credentials:

```bash
python3 scripts/build_reaction_bridge.py --output /tmp/fbchat-reaction-rebuilt
```

The script checks both source commits and the patch hash, applies the patch, runs the Go tests, builds, and checks the output hash **before** installing it at the chosen path. `--go /path/to/go` selects a compiler. Omitting `--output` installs into this repository's `bin/`; stop the bot first if using that destination.

## Distribution and checks

`fbchat-bridge-e2ee-linux-amd64-reaction-v1.bsdiff` is a 114,519-byte BSDIFF40 delta from the original release binary to the reproducible fixed binary. It avoids committing a full 20 MB executable. The installer uses a bounded Python standard-library reader, checks the original/delta/output hashes, and atomically replaces only a recognized original binary. Unknown binaries and corrupt patches are rejected; a matching fixed binary is reused. No additional runtime dependency is required.

The delta was generated with `bsdiff4==1.4.0` from the two verified binaries and independently reconstructed by the installer. Go tests cover reaction protobuf serialization for like, love and removal, and the advertised capability. Python tests cover reconstruction, signed seeks, checksum rejection, atomic installation, capability negotiation and encrypted-thread routing.

## Third-party notices

The patched bridge and its dependencies retain their upstream licenses. This directory includes copies of the relevant notices:

- [fbchat-v2 Apache-2.0](licenses/fbchat-v2-Apache-2.0.txt)
- [mautrix-meta AGPL-3.0](licenses/mautrix-meta.txt) and [upstream exceptions](licenses/mautrix-meta-exceptions.txt)
- [whatsmeow MPL-2.0](licenses/whatsmeow-MPL-2.0.txt)

The pinned public source trees, their submodules, the modification patch and reproduction script above provide the corresponding source for this modification. Additional dependency notices remain available in those source trees. See also [THIRD_PARTY.md](../THIRD_PARTY.md).
