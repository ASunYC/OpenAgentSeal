# Mobile Companion

The mobile client is the Capacitor Android build of `open_agent/app/web`, with `MobileShell.vue` connecting to a desktop/server OpenAgentSeal instance.

## Build ownership

- `open_agent/app/web/capacitor.config.ts`: Capacitor application and web output mapping.
- `open_agent/app/web/android/`: tracked Gradle/Android host project.
- `package.json` mobile scripts: build/sync/package/open operations.
- `scripts/package-release.mjs`: release selection and APK collection.
- `scripts/build-linux-docker.mjs`: builds Android on the host before Linux Docker artifacts unless skipped.

## Runtime contract

The app stores a normalized server URL, pairs locally through a code, receives a bearer token, then uses mobile summary/chat/history/run/device endpoints. `navigator.onLine` is only a connectivity signal; the app still verifies server health.

Changes to pairing or mobile DTOs must update `app/mobile.py`, frontend `mobileApi`, `MobileShell.vue`/`MobileSettings.vue`, token/storage compatibility, and `tests/test_mobile.py`.

## Boundaries

- Do not embed a desktop-local URL as the only mobile target.
- Do not log or render the bearer token.
- Keep token revocation effective server-side.
- Android generated build outputs remain untracked; edit source Gradle/manifest/resources only when the host integration changes.
