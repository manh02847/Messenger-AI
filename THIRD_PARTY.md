# Third-party software

The installer downloads `vendor/fbchat_v2-2.3.4-py3-none-any.whl` and the platform bridge as unmodified release artifacts directly from the upstream release. These binaries are not tracked in this Git repository:

- Project: fbchat-v2 by MinhHuyDev / m008v.
- Release: https://github.com/m008v/fbchat-v2/releases/tag/v2.3.4
- Source revision identified by that release: `aa7abd0386ef1d4cabf8ce592d0f2cf308d8f4f6`.
- Source: https://github.com/m008v/fbchat-v2/tree/v2.3.4
- License: Apache-2.0; included as `vendor/LICENSE.fbchat-v2` and inside the wheel.
- The Go E2EE bridge uses mautrix/meta (AGPL-3.0 with upstream exceptions) and other upstream dependencies. Their corresponding source, copyright notices and licenses are available through the release source tree and its pinned `bridge-e2ee/meta` submodule: https://github.com/m008v/fbchat-v2/tree/v2.3.4/bridge-e2ee. The relevant AGPL text is included as `vendor/LICENSE.mautrix-meta`.
- All asset SHA-256 values used by the installer are pinned in `assets.json` from the GitHub release metadata. The installer verifies them before execution.

The bot's Python application files are original integration code and are licensed under MIT (`LICENSE`). The upstream assets retain their original licenses. Groq and Facebook services have their own terms and data policies.
