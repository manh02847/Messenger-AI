# Third-party software

The installer downloads `vendor/fbchat_v2-2.3.4-py3-none-any.whl` and the platform bridge from the pinned upstream release. On Linux amd64 it then applies the separately pinned E2EE reaction timestamp fix described in [native/README.md](native/README.md). The wheel is unmodified. Full binaries are not tracked in this Git repository; the Linux bridge delta, corresponding source patch, build instructions and license notices are included:

- Project: fbchat-v2 by MinhHuyDev / m008v.
- Release: https://github.com/m008v/fbchat-v2/releases/tag/v2.3.4
- Source revision identified by that release: `aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6`.
- Source: https://github.com/m008v/fbchat-v2/tree/v2.3.4
- License: Apache-2.0; included as `vendor/LICENSE.fbchat-v2` and inside the wheel.
- The Go E2EE bridge uses mautrix/meta (AGPL-3.0 with upstream exceptions) and other upstream dependencies. Their corresponding source, copyright notices and licenses are available through the release source tree and its pinned `bridge-e2ee/meta` submodule: https://github.com/m008v/fbchat-v2/tree/v2.3.4/bridge-e2ee. The relevant AGPL text is included as `vendor/LICENSE.mautrix-meta`.
- Upstream asset SHA-256 values from GitHub release metadata remain pinned in `assets.json`. The Linux fix has separate pins for the original binary, delta, patched binary and source patch. The installer verifies the applicable checksums before execution. This project's fix is not an upstream release.

The bot's Python application files are original integration code and are licensed under MIT (`LICENSE`). The upstream assets retain their original licenses. Groq and Facebook services have their own terms and data policies.

Reaction validation uses [emoji 2.15.0](https://pypi.org/project/emoji/2.15.0/) (BSD-3-Clause; [source and license](https://github.com/carpedm20/emoji/tree/d26c675190a6b6c0edee959d7b896721a9c3641d)), installed from PyPI. Its Unicode emoji data allows the model to select a single valid emoji, including supported compound sequences, without a fixed reaction menu. No emoji data is downloaded at reply time.
