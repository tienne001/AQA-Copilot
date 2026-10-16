# AQA Copilot desktop shell

Russian React 19 + TypeScript + Vite frontend and Tauri 2 Windows host. Models and user data are external to the installer. No cloud API, remote fonts, telemetry, shell invocation, or webview filesystem permissions.

## Frontend checks

```powershell
npm ci --ignore-scripts
npm test
npm run build
```

For browser development only, set `VITE_API_URL=http://127.0.0.1:17321` and `VITE_API_TOKEN` to the running service token before `npm run dev`. Do not place a real token in committed/bundled environment files. A packaged app obtains a new token directly from the Rust host.

## Native packaging

Use `Setup.ps1 -Mode Build` from the repository root. It prepares the Windows build tools, packages the Python backend, builds the Tauri executable and produces a portable ZIP. Models are prepared separately with `Setup.ps1 -Mode Models`.

The app launches the packaged backend on port 17321 with a random per-launch token. Data is stored in `data` beside the EXE; set `AQACOPILOT_DATA` to an absolute path to override it. Backend output is written to `backend.log` in that directory. The host owns and terminates the backend when the application exits. API requests require a Bearer token, including `/health` and `/events`.

The app has a normal taskbar window. Ctrl+Alt+Space toggles it, Ctrl+Alt+S captures the explicitly selected window, and Ctrl+Alt+X cancels the active answer. Shortcut conflicts are displayed in the app. Changing the selected window clears the old screenshot and OCR attachment; capture alone never attaches or sends it. Raw audio and screenshots are not persisted by this frontend.

Streaming answers use an authenticated fetch SSE reader (including split UTF-8 / CRLF records), an AbortController before response headers arrive, and a request generation gate that rejects stale events. The backend also cancels superseded Ollama requests. The UI has separate microphone/loopback devices, switches, levels and transcript labels. Microphone auto-answer is off by default and controlled separately in settings.

Unsigned local builds may show Windows publisher warnings. End-to-end audio/OCR/model performance and native executable launch must be measured against real hardware and the packaged backend; passing frontend tests does not establish them.
