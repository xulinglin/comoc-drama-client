# CDTV Comic-Drama Automation Client (comoc-drama-client)

English | [简体中文](README.md)

A local desktop application built with Vue 3, pywebview, Python, and Playwright for automating AI comic-drama production workflows. It brings project management, asset organization, storyboard editing, video generation, and account scheduling into one workspace, using OriginalDoubao browser automation to reduce repetitive setup and submissions. **Project data and assets are stored locally; no backend deployment, Java runtime, or client registration or login is required. OriginalDoubao video generation requires a separate login to that service.**

> 📢 **Welcome to join the QQ group: 1125912862**

> **This project shares code for noncommercial learning and exchange only. It provides no commercial authorization.**
>
> Users bear the consequences of their use of this project. To the extent permitted by applicable law, the project and its authors accept no liability for losses, disputes or other consequences arising from such use. Liability that cannot legally be excluded remains unaffected. See [LICENSE](LICENSE) for the permitted scope; verify third-party service and media permissions independently.

---

## Features

- **Project management**: Project and chapter management, Markdown script editing, real-time saving, and heading anchor navigation.
- **Asset library**: Categorized management and local preview of prompts, characters / scenes / props / white models / audio assets.
- **OriginalDoubao video generation**: Local image selection, prompts, aspect ratio and duration controls, with task progress and results returned to the client; requires a logged-in OriginalDoubao account.
- **Multi-account management**: Each OriginalDoubao account has an independent browser profile and login state; the account list is stored locally.
- **Quota and scheduling**: Daily quota records for legitimately held accounts, in-use locking, and automatic release on completion to prevent duplicate submissions; not intended to bypass provider limits or security checks.
- **Link conversion and video processing**: Existing sharing-link conversion, downloads and watermark-processing features are retained. Verify media rights, provider permissions and content-label requirements before use.

---

## Getting Started

1. **Start the client**: run `CDTV.exe` from an existing packaged distribution. To run from source, follow the [development guide](docs/DEVELOPMENT.en.md).
   macOS adaptation code and a separate `.app` build configuration are available; see [macOS instructions](docs/DEVELOPMENT.md#macos-运行与打包). This path has not been tested on a Mac.
2. **Create a project**: organize chapters, edit the Markdown script, and add local assets.
3. **Prepare storyboards**: create a video task and edit shots, or import creation-data JSON as described below.
4. **Set up OriginalDoubao**: add an account under settings and open its browser to log in. Windows automation requires `runtime/chrome-win64/chrome.exe` under the application directory; macOS uses a Mac browser bundle or locally installed Google Chrome.
5. **Generate and review**: attach images, enter the video description, select supported settings, then submit and review the returned task progress.

The client itself needs no login; OriginalDoubao web generation uses a separate OriginalDoubao login. Local project editing and asset management work without model API configuration.

## Local Storage & AI Capability Boundaries

Project data and uploaded files are stored locally by default:

- **Built-in local storage service**: `local_storage.py` uses the standard-library `sqlite3` + `http.server` and serves data and file storage on `127.0.0.1:18081` at startup.
- **Single local account**: the app uses a local user; no registration or login is needed.

The default database is `data/storage/storage.db` (SQLite), and uploaded files live in `data/storage/files/`. A custom storage directory can be selected in settings; generated videos default to `output/`. To back up the workspace, close the client and copy the entire configured storage directory.

> Current implementation: `/ai/image` supports OpenAI-compatible generation and reference-image editing; `/ai/audio` supports MiniMax voice design and preview audio; `/ai/video` supports Seedance submission, polling, and local result storage; `/ai/chat` forwards non-streaming Chat Completions and requests to a full `/messages` endpoint. These routes use the enabled model's API URL, key, and model name from settings. Generated media is saved locally. Image URLs can be a service root, a base ending in `/v1`, or a full `/images/generations` endpoint; use full audio and video endpoints as shown below. OriginalDoubao browser automation remains a separate path requiring internet access and a valid login. MiniMax voice previews do not provide full dialogue dubbing or lip synchronization.

## Model Configuration Examples

Under "Model Management" in settings, you can save **text / image / video / audio** model configurations. All four types share the same form fields; they differ in "Type" and "Model name". Actual generation also requires an implementation of the matching API route, as described above.

The tables below are configuration examples recorded by the project author, not a current compatibility guarantee for the built-in local service. **No API Key is included** — obtain your own key from each provider; keys are not interchangeable between providers.

### Optional: third-party relay (TeamoRouter)

To call multiple providers with a single API Key, you can use the third-party relay **TeamoRouter**: sign up and create an API Key in the dashboard (it starts with `sk-teamo-`).

Click to sign up: [https://teamorouter.com/?i=e7ffaa0c8d](https://teamorouter.com/?i=e7ffaa0c8d)

### Image model

| Type | Display name | Provider | Model name (API param) | API URL |
| --- | --- | --- | --- | --- |
| Image model | `gpt-image-2-精品线` | `teamorouter` | `gpt-image-2` | `https://api.teamorouter.cn` |

### Text model

| Type | Display name | Provider | Model name (API param) | API URL |
| --- | --- | --- | --- | --- |
| Text model | `deepseek-v4-flash` | `DeepSeek` | `deepseek-v4-flash` | `https://api.deepseek.com` |
| Text model | `deepseek-v4-pro` | `DeepSeek` | `deepseek-v4-pro` | `https://api.deepseek.com` |
| Text model | `GLM-5.2` | `智普AI` | `GLM-5.2` | `https://open.bigmodel.cn/api/paas/v4` |

### Video model

| Type | Display name | Provider | Model name (API param) | API URL |
| --- | --- | --- | --- | --- |
| Video model | `Seedance-2.0-fast` | `Seedance` | `doubao-seedance-2-0-fast-260128` | `https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks` |

### Audio model

| Type | Display name | Provider | Model name (API param) | API URL |
| --- | --- | --- | --- | --- |
| Audio model | `speech-2.8-hd` | `MiniMax` | `speech-2.8-hd` | `https://api.minimaxi.com/v1/voice_design` |

Notes:

- **All API Keys in the tables are intentionally left blank**; fill in your own key on first setup. For an already-configured model, an **empty API Key keeps the existing key**.
- Display name, order, SVG icon, and the enabled flag are all customizable; order determines the display order on the generation page.
- **The model name (API param) must match the provider exactly** or the call will fail; fill the API URL as the provider requires (some need a path, see the tables).
- These third-party services have no affiliation with this project; registration, billing, and availability follow the provider's terms. Please assess their compliance yourself.

---

## AI Creation Data & Importing Third-Party JSON

The project ships a `SKILL/` directory — a set of **reference specifications** for AI storyboard creation (`SKILL.md` plus `references/` data models and rule documents) — that you can consult when turning a script into structured, verifiable comic-drama storyboard data.

For JSON from external tools, first inspect its fields. Files that already match the supported asset and shot structure can be imported; otherwise map the fields before importing. You can refer to the structure in [`SKILL/references/json-schema.md`](SKILL/references/json-schema.md) and map the source fields over (title, visual description, duration, character / scene / prop / voice entries, etc.).

Importing is a **format conversion only**: it does not change the plot, dialogue, or shot order already fixed by the source, and missing information follows the facts provided by the user. `SKILL/` is a reference spec and example, not a mandatory workflow — you can also convert in your own way, as long as the result matches this project's JSON structure. See [`SKILL/SKILL.md`](SKILL/SKILL.md) for the creation workflow and [client integration](SKILL/references/client-integration.md) for actual imported fields and validation boundaries. This repository includes reference documents, without the external `duanju` compiler or validator scripts. Successful import does not mean the complete H3 generation configuration was preserved.

---

## Multi-Account Management

Here "multi-account" refers to **OriginalDoubao accounts**: each OriginalDoubao account logs in to the OriginalDoubao web UI independently, with its own browser profile and its own daily generation quota, with separate local quota tracking and task scheduling.

1. Click "Add OriginalDoubao account" in the top-right corner and enter an identifiable name.
2. Select the account, click "Open OriginalDoubao and log in this account", log in manually in the browser window that opens, then close it.
3. Repeat the above steps to add more accounts.

Each account's login state is stored independently in `data/accounts/<account-id>/profile`; browser profile files are stored locally; the browser uses the account's login credentials when accessing doubao.

The client maintains a local daily video quota per account (default 3; this is a client setting, not a guarantee of the platform's quota): account management shows "remaining today / daily limit", deducted automatically on each successful generation and reset the next day; an account is locked as "in use" while generating, released automatically when the task ends, and can also be released or marked manually in the settings center.

---

## Development, Build & Packaging

For running from source, requirements, frontend development mode, packaging as an exe, and the directory structure, see [docs/DEVELOPMENT.en.md](docs/DEVELOPMENT.en.md).

## License

The project uses the [PolyForm Noncommercial License 1.0.0](LICENSE), making source code available for noncommercial purposes. This is a source-available license, not an open-source license under the OSI definition.

Noncommercial study, personal research, modification and sharing are permitted within the license terms. Commercial development, paid customization, sales, integration into commercial products and commercial services are not granted by this license; the full terms control permitted purposes and exceptions. When sharing any part of the software, provide the license text or URL and the required copyright notice.

Third-party dependencies and assets retain their own licenses. The new license does not automatically change previously licensed releases or withdraw permissions already granted by third parties or contributors. Before release, confirm the necessary rights to license the affected code under these terms.

## Support this project

Maintaining this project takes time. If it helps you, you are welcome to buy the author a coffee ☕

![WeChat QR code](assets/sponsor-wechat-240.png)

Thank you for your support — it is the greatest motivation for me to keep updating and maintaining this project!
