# Sheepin Breeding Agent (hackathon build)

Turns a farmer's spoken or typed note into validated breeding records, a reproductive
calendar and a pedigree, using Meta models for language and deterministic code for decisions.

Files
- tools.json          function contract shared by backend and agent (9 tools)
- system_prompt.txt   agent rules; {NOW_ISO} etc. are filled at runtime
- backend_stub.py     in-memory backend: validation + calendar (replace with the real DB)
- agent.py            tool-calling loop; PROVIDER=baseten (Muse Spark Open) or meta (Muse Spark)
- run_tests.py        runs test_cases.json and scores calls, questions and refusals
- test_cases.json     12 bilingual cases incl. cases that must be refused or questioned
- herd_fixture.json   5-animal demo herd
- calendar_rules.md   reproductive constants and status transitions

Quick start
  pip install openai
  export BASETEN_API_KEY=...        # or META_API_KEY + META_BASE_URL + META_MODEL
  export PROVIDER=baseten
  python backend_stub.py            # offline self-test
  python agent.py "0266 dikawinkan dengan 0931 tadi pagi jam 7"
  AGENT_NOW=2026-10-29T18:00:00 python run_tests.py --out results_baseten.json

Demo server (text + voice)
  pip install fastapi uvicorn python-multipart
  uvicorn app:app --reload --port 8080      # open http://localhost:8080
  - voice: the page records in the browser, converts to 16 kHz WAV, and transcribe.py sends it
    to Muse Spark Open (Baseten) as a base64 audio_url; the transcript is shown for correction
    before the agent records anything
  - app.py keeps one shared demo herd and one agent conversation per browser session
