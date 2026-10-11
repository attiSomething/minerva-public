<p align="center"><img src="packaging/owl-512.png" width="140" alt="Minerva owl"></p>

# Minerva

*A writer's best friend.* Minerva is a desktop app for reviewing, categorizing and managing a body of writing: every draft kept, entries organized into projects, and the original scans one click away.

Everything stays on your computer. Minerva works directly with ordinary folders and `.txt` files, so your writing is still readable without it.

## Download

Grab `Minerva.exe` from the latest [release](../../releases) (or from the **Minerva-windows** artifact of the latest [Build](../../actions/workflows/build.yml) run). It is a single file: double-click it to start. Windows 10 and 11 include the WebView2 runtime it uses for its window; if it is missing, Minerva opens in your web browser instead.

## First run

1. **Choose your library.** Open a folder that already holds your writing, or let Minerva create a new one with Fiction, Nonfiction, Poetry, Misc, Projects and Sources folders. Put scans, images and documents you want to work from in Sources.
2. **AI-assisted scanning (optional).** Pick a provider and paste your own API key if you want an AI model to read handwritten pages and scans.
3. **AI-assisted organizing and editing (optional).** The same, for suggestions about categories, projects, titles and duplicates.

Supported providers are Anthropic (Claude), OpenAI, Google Gemini, and local models through Ollama. Keys are stored in Windows Credential Manager, never in your library, the app's settings file, or this repository.

## Scans

The **Scans** tab turns scanned pages (journals, notebooks, letters, old documents) into entries: transcribe each page with your scanning model, combine the results into a Master transcript, proofread it beside the page, then file entries into your library. **Ask Minerva** in the edit view suggests a title, category and project, or proofreads a draft. Every suggestion waits for you to apply it.

## How a library is laid out

```
Poetry\
  Morning Tide - [SEA]\            entry folder; "- [SEA]" is a project tag
    Morning Tide [C].txt           current draft ([J] = transcribed original)
    Archive\                       every older draft
    Images\                        pictures that belong to the entry
.minerva\                          Minerva's index (hidden)
```

Minerva never deletes anything: saves can archive the previous draft first, restores archive the current one, and merges move the other entry's whole folder into this entry's Archive.

Opening a library that was used with the first version of Minerva (`01A - Minerva\minerva.db`) copies that database once, read-only, so flags, projects and duplicate reviews come along.

## Running from source

```
python -m pip install -r requirements-dev.txt
python run_minerva.py            # native window
python run_minerva.py --browser  # or in your browser
python -m pytest                 # tests
python packaging/build.py        # builds dist/Minerva.exe
```

### Building Minerva.exe on your own computer

To build it yourself, double-click **Build Minerva.bat** in a copy of this repository. It installs what the build needs, runs the tests, builds `dist\Minerva.exe` and runs the app's self-test, the same steps as the GitHub build. It needs Python 3.10 or newer (the GitHub build uses 3.12) installed with "Add python.exe to PATH" ticked.

Tests use a small synthetic library. No real writing belongs in this repository.

