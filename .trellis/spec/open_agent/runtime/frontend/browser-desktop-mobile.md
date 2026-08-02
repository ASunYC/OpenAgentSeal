# Browser, Desktop and Mobile Frontend

## Runtime detection and endpoints

`src/api/index.ts` detects Tauri using `__TAURI_INTERNALS__` and Capacitor using `Capacitor.isNativePlatform()`.

- Tauri uses `http://127.0.0.1:9998/api` and the matching WebSocket base.
- Browser development/served UI uses relative `/api` and the current host for WebSocket.
- Native mobile resolves a configurable server URL and uses token-authenticated `/api/mobile` operations.

Preserve URL normalization, query/path encoding, and storage-key compatibility.

## Shells

- `src/main.ts` mounts Vue/Pinia.
- `App.vue` chooses the application surface.
- `DesktopApp.vue` owns the full desktop/browser workspace experience.
- `MobileShell.vue` owns pairing, chats, conversation, tasks and device status optimized for mobile.

Do not assume a desktop component is mounted on mobile. Shared behavior belongs in API/types/models/composables when both shells need it.

## Native bridges

- Tauri-only commands are dynamically imported/invoked and must fail gracefully in browser mode.
- Capacitor mobile persists server/token/agent state and reacts to online/offline status.
- Browser APIs such as clipboard/localStorage require availability checks where code may execute outside a normal browser context.
- Timers, network listeners and sockets must be cleared on teardown.

Packaged static assets use Vite `base: './'`; changing it can break Tauri file loading even if the dev server works.
